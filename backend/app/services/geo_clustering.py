"""
INDRA Platform — GeoClusteringService
Uses PostGIS ST_ClusterDBSCAN to cluster unassigned raw_reports and assigns H3 cell indexes.
"""

import logging
from typing import Optional

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

    async def cluster_unassigned_reports(self) -> int:
        """
        Run ST_ClusterDBSCAN over raw_reports WHERE event_id IS NULL.
        Returns number of reports that were assigned to a cluster.

        Uses eps in degrees (approximate: 1km ≈ 0.009 degrees at equator).
        """
        eps_degrees = self.eps_km * 0.009  # rough conversion

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
        """)

        result = await self.db.execute(
            query, {"eps": eps_degrees, "min_samples": self.min_samples}
        )
        clusters = result.fetchall()
        total_assigned = 0

        for row in clusters:
            cluster_id = row[0]
            report_ids = row[1]
            total_assigned += len(report_ids)
            logger.info(
                f"Cluster {cluster_id}: {len(report_ids)} reports"
            )

        logger.info(f"Clustering complete: {len(clusters)} clusters, {total_assigned} reports assigned")
        return total_assigned

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
