"""
INDRA Platform — GeoClusteringService
Uses PostGIS ST_ClusterDBSCAN to cluster unassigned raw_reports and assigns H3 cell indexes.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

logger = logging.getLogger("indra.services.geo_clustering")
settings = get_settings()


class GeoClusteringService:
    """Spatial clustering over unassigned raw_reports using PostGIS DBSCAN."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.eps_km = settings.DBSCAN_EPS_KM
        self.min_samples = settings.DBSCAN_MIN_SAMPLES
        self.h3_resolution = settings.H3_HEX_RESOLUTION

    async def cluster_unassigned_reports(self) -> List[Dict[str, Any]]:
        """
        Run ST_ClusterDBSCAN over raw_reports WHERE event_id IS NULL.

        Returns the cluster → report mapping so the caller can act on it:
            [{"cluster_id": int, "report_ids": [UUID, ...], "size": int}, ...]

        This deliberately does NOT write event_id back. event_id is an FK to a
        verified_events row that does not exist until the fusion step has run,
        so the pipeline owns that write via assign_reports_to_event().

        Only reports with event_id IS NULL are considered, which is what makes
        the operation idempotent: once the pipeline has linked a cluster to an
        event, those reports drop out of the candidate set and are never
        re-clustered or re-scored.

        NOTE (accuracy): eps is converted to degrees with a flat 0.009 deg/km
        factor, which is the value at the equator. At Patna's latitude (~25.6N)
        a degree of longitude is about 10% shorter, so the effective search
        radius is slightly wider east-west than north-south. Day 2 should switch
        this query to ST_ClusterDBSCAN over geography, or project to a metric
        SRID, rather than clustering in degrees.
        """
        eps_degrees = self.eps_km * 0.009  # rough conversion — see NOTE above

        query = text("""
            WITH clusters AS (
                SELECT
                    id,
                    ST_ClusterDBSCAN(geom_point, eps := :eps, minpoints := :min_samples)
                        OVER () AS cluster_id
                FROM raw_reports
                WHERE event_id IS NULL
                  AND geom_point IS NOT NULL
            )
            SELECT cluster_id, array_agg(id) as report_ids
            FROM clusters
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
            ORDER BY cluster_id
        """)

        result = await self.db.execute(
            query, {"eps": eps_degrees, "min_samples": self.min_samples}
        )
        rows = result.fetchall()

        clusters: List[Dict[str, Any]] = []
        total_assigned = 0

        for cluster_id, report_ids in rows:
            report_ids = list(report_ids or [])
            total_assigned += len(report_ids)
            clusters.append({
                "cluster_id": int(cluster_id),
                "report_ids": report_ids,
                "size": len(report_ids),
            })
            logger.info(f"Cluster {cluster_id}: {len(report_ids)} reports")

        logger.info(
            f"Clustering complete: {len(clusters)} clusters, {total_assigned} reports clustered"
        )
        return clusters

    async def get_cluster_stats(self, report_ids: Sequence[UUID]) -> Dict[str, Any]:
        """
        Spatial summary of one cluster, used by the fusion step.

        Returns {"count", "centroid_lat", "centroid_lng", "max_pairwise_km",
                 "radius_km"}.

        Distances are computed in geography (metres) so they are true ground
        distances, not degrees. max_pairwise_km is the diameter of the cluster
        (the widest separation between any two reports); radius_km is the
        farthest any report sits from the centroid, which is what the event's
        impact_radius_km is derived from.

        The pipeline scores the Report Density and Spatial Coherence factors
        from count and max_pairwise_km.
        """
        ids = [str(rid) for rid in report_ids]
        if not ids:
            return {
                "count": 0,
                "centroid_lat": None,
                "centroid_lng": None,
                "max_pairwise_km": 0.0,
                "radius_km": 0.0,
            }

        query = text("""
            WITH pts AS (
                SELECT id, geom_point
                FROM raw_reports
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND geom_point IS NOT NULL
            ),
            centroid AS (
                SELECT ST_Centroid(ST_Collect(geom_point)) AS c FROM pts
            )
            SELECT
                (SELECT COUNT(*) FROM pts)                              AS count,
                ST_Y((SELECT c FROM centroid))                          AS centroid_lat,
                ST_X((SELECT c FROM centroid))                          AS centroid_lng,
                COALESCE((
                    SELECT MAX(ST_Distance(a.geom_point::geography, b.geom_point::geography))
                    FROM pts a CROSS JOIN pts b
                ), 0.0)                                                 AS max_pairwise_m,
                COALESCE((
                    SELECT MAX(ST_Distance(p.geom_point::geography, (SELECT c FROM centroid)::geography))
                    FROM pts p
                ), 0.0)                                                 AS radius_m
        """)

        row = (await self.db.execute(query, {"ids": ids})).fetchone()
        if row is None or row[0] == 0:
            return {
                "count": 0,
                "centroid_lat": None,
                "centroid_lng": None,
                "max_pairwise_km": 0.0,
                "radius_km": 0.0,
            }

        count, lat, lng, max_pairwise_m, radius_m = row
        return {
            "count": int(count),
            "centroid_lat": float(lat) if lat is not None else None,
            "centroid_lng": float(lng) if lng is not None else None,
            "max_pairwise_km": round(float(max_pairwise_m or 0.0) / 1000.0, 4),
            "radius_km": round(float(radius_m or 0.0) / 1000.0, 4),
        }

    async def assign_reports_to_event(
        self, report_ids: Sequence[UUID], event_id: UUID, commit: bool = True
    ) -> int:
        """
        Link a set of reports to the verified_event created from them.

        Returns the number of rows updated. Only unassigned reports are touched,
        so a concurrent run cannot steal reports already linked to another event.
        The pipeline passes commit=False so the link, the event write and the
        event's audit row land in one transaction.
        """
        ids = [str(rid) for rid in report_ids]
        if not ids:
            return 0

        result = await self.db.execute(
            text("""
                UPDATE raw_reports
                SET event_id = CAST(:event_id AS uuid)
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND event_id IS NULL
            """),
            {"ids": ids, "event_id": str(event_id)},
        )
        if commit:
            await self.db.commit()
        count = result.rowcount or 0
        logger.info(f"Linked {count} reports to event {event_id}")
        return count

    async def assign_h3_cells(self) -> int:
        """Assign H3 cell indexes to reports that don't have one yet."""
        try:
            import h3

            query = text("""
                SELECT id, latitude, longitude
                FROM raw_reports
                WHERE h3_res8 IS NULL
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()

            count = 0
            for row in rows:
                report_id, lat, lng = row
                h3_cell = h3.latlng_to_cell(lat, lng, self.h3_resolution)
                await self.db.execute(
                    text("UPDATE raw_reports SET h3_res8 = :h3 WHERE id = :id"),
                    {"h3": h3_cell, "id": report_id},
                )
                count += 1

            await self.db.commit()
            logger.info(f"H3 cell assignment: {count} reports updated")
            return count

        except ImportError:
            logger.warning("h3 library not available — skipping H3 cell assignment")
            return 0

    async def update_geom_points(self) -> int:
        """Populate geom_point from lat/lng for reports missing it."""
        result = await self.db.execute(text("""
            UPDATE raw_reports
            SET geom_point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
            WHERE geom_point IS NULL
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
        """))
        await self.db.commit()
        count = result.rowcount or 0
        logger.info(f"Geom point backfill: {count} reports updated")
        return count
