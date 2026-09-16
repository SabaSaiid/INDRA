"""
INDRA Platform — Verification Pipeline Orchestrator

Turns one incoming raw report into (at most) one verified event:

    dedup → geo-cluster → cluster stats → fusion scoring → persist → link

This lives in its own module rather than inside the Kafka consumer so that the
consumer stays thin, the pipeline is unit-testable without a broker, and Day 4's
reprocess endpoint can re-run it over existing rows.

Design notes
------------
* **The message is a trigger, not a source of truth.** `api/reports.py` used to
  store the *sanitised* coordinates but publish the *raw* ones; since 17 Sep it
  publishes exactly what it stored. The pipeline still re-reads the row from
  Postgres by id and uses the stored values for every spatial decision — it
  costs one primary-key lookup and protects against any other producer on the
  topic.
* **Not every report becomes an event.** A duplicate, or a lone report that
  DBSCAN treats as noise, correctly produces no event. That is the system
  working, not failing.
* **Fail soft.** Everything is wrapped so that one bad report cannot kill the
  consumer loop, matching the convention in `api/reports.py::reports_trend`.
"""

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import AuditAction, EventType, ReviewStatus, Severity
from app.services import audit
from app.services.dedup import DedupService
from app.services.fusion_engine import FusionEngine, source_reliability_score
from app.services.geo_clustering import GeoClusteringService
from app.services.weather import weather_score

logger = logging.getLogger("indra.services.pipeline")
settings = get_settings()

# Severity thresholds by corroboration count. Crude and deliberately explicit —
# this is a stand-in for the NLP severity classifier, and the receipt says so.
SEVERITY_CRITICAL_REPORTS = 25
SEVERITY_HIGH_REPORTS = 10

# Dedup candidate window, mirroring DedupService's own gates.
DEDUP_WINDOW_MINUTES = 15
DEDUP_RADIUS_METRES = 1000

# Reports arrive one at a time, so a cluster reaches DBSCAN_MIN_SAMPLES long
# before every report about an incident has landed. Without merging, the first
# two reports create one event and the next three create a rival event a few
# hundred metres away — the exact fragmentation this platform exists to remove.
# So a new cluster that lands on top of a recent event joins it and raises its
# corroboration instead of competing with it.
MERGE_WINDOW_MINUTES = 120

# The pipeline's audit action for each status it can decide on its own.
# HUMAN_APPROVED and REJECTED are never machine decisions.
PIPELINE_AUDIT_ACTIONS = {
    ReviewStatus.AUTO_PUBLISHED: AuditAction.AUTO_VERIFY,
    ReviewStatus.PENDING_HUMAN_REVIEW: AuditAction.ESCALATE,
    ReviewStatus.QUARANTINED: AuditAction.QUARANTINE,
}


def _derive_severity(cluster_size: int) -> Severity:
    """
    Severity from corroboration count. Still a heuristic — there is no NLP
    severity classifier — and the receipt's provenance block says so.
    """
    if cluster_size >= SEVERITY_CRITICAL_REPORTS:
        return Severity.CRITICAL
    if cluster_size >= SEVERITY_HIGH_REPORTS:
        return Severity.HIGH
    return Severity.MODERATE


# Report density saturates at the CRITICAL count (25), shaped so a 10-report
# cluster already scores ~0.80. See _density_score.
DENSITY_SATURATION_REPORTS = SEVERITY_CRITICAL_REPORTS
DENSITY_CURVE_SCALE = 6.5


def _density_score(cluster_size: int) -> float:
    """
    Report Density: how much independent corroboration a cluster has.

        score(n) = (1 − e^(−n / 6.5)) / (1 − e^(−25 / 6.5)),  clamped to [0, 1]

    Why this shape, and why 25 rather than 10:

    * Each additional report adds less than the one before — the fifth witness
      matters more than the twentieth — so the curve is concave, not linear.
    * It reaches ~0.80 at 10 reports: ten reports from one neighbourhood inside
      the time window is already strong corroboration, so a moderate event
      still scores well.
    * It only reaches 1.0 at 25, the CRITICAL threshold, leaving headroom so a
      major event scores distinctly above a moderate one. A linear ramp
      saturating at 10 made 10 and 100 reports indistinguishable.

    Reference points: 1 → 0.15, 3 → 0.38, 5 → 0.55, 10 → 0.80, 25+ → 1.0.
    """
    if cluster_size <= 0:
        return 0.0
    norm = 1.0 - math.exp(-DENSITY_SATURATION_REPORTS / DENSITY_CURVE_SCALE)
    raw = (1.0 - math.exp(-cluster_size / DENSITY_CURVE_SCALE)) / norm
    return round(max(0.0, min(1.0, raw)), 4)


def _coherence_score(max_pairwise_km: float) -> float:
    """
    Spatial Coherence: a tight cluster is more likely to be one real event
    than a diffuse one. Scored on the cluster's diameter d against the DBSCAN
    search diameter D = 2 × DBSCAN_EPS_KM (10 km by default) with a raised
    cosine:

        score(d) = ½ · (1 + cos(π · d / D)),  and 0 for d ≥ D

    Why a raised cosine rather than the earlier linear ramp:

    * **Flat near zero.** Phone GPS error and people reporting from either end
      of the same flooded street spread a genuine incident over a few hundred
      metres to ~1 km. That spread is noise, not doubt, so it should cost
      almost nothing — linear charged 10% for 1 km; this charges ~2%.
    * **Midpoint at eps.** A cluster as wide as one DBSCAN radius scores 0.5,
      the natural "could be one event, could be two" point.
    * **Flat near D.** Beyond ~8 km the cluster is already implausible as one
      incident; further spread adds little new information.

    Reference points (eps = 5 km): 0 km → 1.0, 1 km → 0.98, 4 km → 0.65,
    5 km → 0.5, 10 km → 0.0.
    """
    span = max(settings.DBSCAN_EPS_KM * 2.0, 0.001)
    d = max(0.0, float(max_pairwise_km))
    if d >= span:
        return 0.0
    return round(0.5 * (1.0 + math.cos(math.pi * d / span)), 4)


def score_cluster(
    stats: Dict[str, Any],
    source_types: Sequence[Any],
    weather: Optional[float],
    rainfall_mm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Pure scoring step: cluster geometry + source mix + weather → receipt,
    severity, quadrant and review status.

    No I/O, no sampling, no clock — the same inputs always give the same
    output, which is what tests/test_scoring_determinism.py pins down. Every
    factor is either computed from those inputs or passed as None and marked
    offline; nothing is invented.
    """
    fusion = FusionEngine()

    density = _density_score(stats["count"])
    coherence = _coherence_score(stats["max_pairwise_km"])
    reliability = source_reliability_score(source_types)

    receipt = fusion.compute_receipt(
        weather_score=weather,
        report_density_score=density,
        spatial_score=coherence,
        # No image classifier and no anomaly model ship this sprint. Passing
        # None scores them 0.0 as "Telemetry factor offline" — an honest,
        # visible cost of 0.20 confidence rather than a plausible fake.
        vision_score=None,
        reliability_score=reliability,
        anomaly_score=None,
    )
    confidence = receipt["confidence_score"]

    # Replace the generic evidence text with what was actually measured.
    distinct_sources = sorted({str(getattr(t, "value", t)) for t in source_types})
    evidence = {
        "Report Density Analysis": f"{stats['count']} corroborating report(s) in cluster",
        "Spatial Coherence Score": (
            f"cluster diameter {stats['max_pairwise_km']:.2f} km "
            f"against {settings.DBSCAN_EPS_KM * 2:.0f} km search diameter"
        ),
    }
    if reliability is not None:
        evidence["Source Reliability Index"] = (
            f"highest-reliability source among {', '.join(distinct_sources)}"
        )
    if weather is not None and rainfall_mm is not None:
        evidence["Weather Station Corroboration"] = (
            f"{rainfall_mm:.1f} mm rainfall in past 24 h (Open-Meteo modelled precipitation)"
        )
    for factor in receipt["factors"]:
        if factor["factor"] in evidence:
            factor["evidence"] = evidence[factor["factor"]]

    severity = _derive_severity(stats["count"])
    quadrant = fusion.assign_quadrant(severity, confidence)
    review_status = fusion.determine_review_status(
        confidence,
        settings.AUTO_PUBLISH_THRESHOLD,
        settings.HUMAN_REVIEW_THRESHOLD,
    )

    def _state(value: Optional[float]) -> str:
        return "computed" if value is not None else "offline"

    # Be explicit in the stored receipt about what is real and what is not,
    # so nobody downstream mistakes a missing signal for a measurement.
    receipt["provenance"] = {
        "report_density": "computed",
        "spatial_coherence": "computed",
        "weather_station": _state(weather),
        "vision_analysis": "offline",
        "source_reliability": _state(reliability),
        "anomaly_detection": "offline",
        "severity": "heuristic_from_cluster_size",
    }
    receipt["cluster"] = {
        "size": stats["count"],
        "centroid_lat": stats["centroid_lat"],
        "centroid_lng": stats["centroid_lng"],
        "max_pairwise_km": stats["max_pairwise_km"],
        "radius_km": stats["radius_km"],
        "source_types": distinct_sources,
    }
    if rainfall_mm is not None:
        receipt["weather"] = {"rainfall_24h_mm": rainfall_mm, "provider": "open-meteo"}

    return {
        "receipt": receipt,
        "confidence": confidence,
        "severity": severity,
        "quadrant": quadrant,
        "review_status": review_status,
    }


async def _load_report(db: AsyncSession, report_id: UUID) -> Optional[Dict[str, Any]]:
    """Re-read the stored row — the authority on this report's coordinates."""
    row = (
        await db.execute(
            text("""
                SELECT id, raw_text, latitude, longitude, created_at, event_id
                FROM raw_reports
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(report_id)},
        )
    ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "raw_text": row[1],
        "latitude": float(row[2]),
        "longitude": float(row[3]),
        "created_at": row[4],
        "event_id": row[5],
    }


async def _dedup_candidates(db: AsyncSession, report: Dict[str, Any]):
    """
    Recent nearby reports, with the spatial and temporal gates pushed into SQL.

    Doing the filtering here rather than loading every recent report into Python
    keeps the embedding model — the expensive part — to a handful of comparisons.
    DedupService then applies the text-similarity gate over the survivors.
    """
    rows = (
        await db.execute(
            text("""
                SELECT raw_text, latitude, longitude, created_at
                FROM raw_reports
                WHERE id <> CAST(:id AS uuid)
                  AND created_at > CAST(:created_at AS timestamptz)
                                   - make_interval(mins => CAST(:window AS int))
                  AND created_at <= CAST(:created_at AS timestamptz)
                  AND geom_point IS NOT NULL
                  AND ST_DWithin(
                        geom_point::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        :radius
                      )
            """),
            {
                "id": str(report["id"]),
                "created_at": report["created_at"],
                "window": DEDUP_WINDOW_MINUTES,
                "lat": report["latitude"],
                "lng": report["longitude"],
                "radius": DEDUP_RADIUS_METRES,
            },
        )
    ).fetchall()

    return [(r[0], float(r[1]), float(r[2]), r[3]) for r in rows]


async def _find_mergeable_event(
    db: AsyncSession, lat: float, lng: float
) -> Optional[Dict[str, Any]]:
    """
    The nearest recent event whose footprint already covers this location.

    Matches within the event's own impact radius plus one DBSCAN eps, so a
    cluster that DBSCAN would have merged had all the reports arrived together
    is merged after the fact too. Rejected events are excluded — an operator
    dismissing an event must not have it silently resurrected.
    """
    row = (
        await db.execute(
            text("""
                SELECT id, event_code
                FROM verified_events
                WHERE verified_at > NOW() - make_interval(mins => CAST(:window AS int))
                  AND review_status <> 'REJECTED'
                  AND center_point IS NOT NULL
                  AND ST_DWithin(
                        center_point::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        (COALESCE(impact_radius_km, 0) + :eps) * 1000
                      )
                ORDER BY ST_Distance(
                    center_point::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                )
                LIMIT 1
            """),
            {
                "window": MERGE_WINDOW_MINUTES,
                "lat": lat,
                "lng": lng,
                "eps": settings.DBSCAN_EPS_KM,
            },
        )
    ).fetchone()

    if row is None:
        return None
    return {"id": row[0], "event_code": row[1]}


async def _event_report_ids(db: AsyncSession, event_id: UUID):
    """Every report currently linked to an event."""
    rows = (
        await db.execute(
            text("SELECT id FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
            {"e": str(event_id)},
        )
    ).fetchall()
    return [r[0] for r in rows]


async def _source_types(db: AsyncSession, report_ids: Sequence[UUID]) -> List[str]:
    """The source_type of every report in a cluster, for Source Reliability."""
    ids = [str(rid) for rid in report_ids]
    if not ids:
        return []
    rows = (
        await db.execute(
            text("SELECT source_type FROM raw_reports WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": ids},
        )
    ).fetchall()
    return [str(getattr(r[0], "value", r[0])) for r in rows]


async def _next_event_code(db: AsyncSession) -> str:
    """
    Sequential, human-readable code: INDRA-YYYYMMDD-NNN.

    Derived from the count of events already created today. Two events created
    in the same millisecond could collide; event_code is UNIQUE so the insert
    would fail loudly rather than corrupt anything. Fine at demo volume.
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count = (
        await db.execute(
            text("""
                SELECT COUNT(*) FROM verified_events
                WHERE event_code LIKE :prefix
            """),
            {"prefix": f"INDRA-{today}-%"},
        )
    ).scalar() or 0
    return f"INDRA-{today}-{count + 1:03d}"


async def process_report(db: AsyncSession, report: dict) -> Optional[dict]:
    """
    Run one report through the verification pipeline.

    Returns the created event as a dict, or None when no event should be created
    (duplicate, uncorroborated, or a handled error).
    """
    try:
        raw_id = report.get("id")
        if not raw_id:
            logger.warning("Pipeline: message has no report id — skipping")
            return None

        try:
            report_id = UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"Pipeline: malformed report id {raw_id!r} — skipping")
            return None

        # ── 1. Authority pass: use the stored row, not the message payload ──
        stored = await _load_report(db, report_id)
        if stored is None:
            logger.warning(f"Pipeline: report {report_id} not found in DB — skipping")
            return None

        if stored["event_id"] is not None:
            logger.info(f"Pipeline: report {report_id} already linked to an event — skipping")
            return None

        # ── 2. Deduplication ────────────────────────────────────────────────
        candidates = await _dedup_candidates(db, stored)
        if candidates:
            is_dupe = DedupService().is_duplicate(
                stored["raw_text"],
                stored["latitude"],
                stored["longitude"],
                stored["created_at"],
                candidates,
            )
            if is_dupe:
                logger.info(
                    f"Pipeline: report {report_id} suppressed as duplicate "
                    f"({len(candidates)} nearby candidates)"
                )
                return None

        # ── 3. Spatial preparation ──────────────────────────────────────────
        geo = GeoClusteringService(db)
        await geo.update_geom_points()
        await geo.assign_h3_cells()

        # ── 4. Clustering — find the cluster this report belongs to ─────────
        clusters = await geo.cluster_unassigned_reports()
        cluster = next(
            (c for c in clusters if report_id in c["report_ids"]),
            None,
        )
        if cluster is None:
            # No cluster can mean two very different things.
            #
            # Once a burst of reports has been absorbed into an event, the next
            # report about that same incident has no *unassigned* neighbours
            # left to cluster with — every one of them already belongs to the
            # event. Dropping it would silently discard corroboration for a
            # confirmed incident, so if it lands inside a known event's
            # footprint it joins that event on its own.
            #
            # Otherwise it really is a lone, uncorroborated report, and a single
            # report is not yet an event.
            nearby = await _find_mergeable_event(
                db, stored["latitude"], stored["longitude"]
            )
            if nearby is None:
                logger.info(
                    f"Pipeline: report {report_id} is in no cluster and near no "
                    "known event — a single uncorroborated report is not yet an event"
                )
                return None

            logger.info(
                f"Pipeline: lone report {report_id} joins existing {nearby['event_code']}"
            )
            cluster = {"cluster_id": -1, "report_ids": [report_id], "size": 1}

        # ── 5. Cluster geometry ─────────────────────────────────────────────
        stats = await geo.get_cluster_stats(cluster["report_ids"])
        if not stats["count"] or stats["centroid_lat"] is None:
            logger.warning(f"Pipeline: cluster for {report_id} has no usable geometry")
            return None

        # ── 5a. Merge into a recent overlapping event, if there is one ──────
        # Decided before scoring, because a merge scores over the union of both
        # report sets rather than over this cluster alone. Nothing is committed
        # until step 7: the report links, the event write and its audit row
        # land together or not at all.
        existing = await _find_mergeable_event(
            db, stats["centroid_lat"], stats["centroid_lng"]
        )

        if existing is not None:
            event_id = existing["id"]
            event_code = existing["event_code"]
            linked = await geo.assign_reports_to_event(
                cluster["report_ids"], event_id, commit=False
            )
            all_report_ids = await _event_report_ids(db, event_id)
            stats = await geo.get_cluster_stats(all_report_ids)
            logger.info(
                f"Pipeline: merging {linked} reports into existing {event_code} "
                f"— now {stats['count']} reports"
            )
        else:
            event_id = uuid4()
            event_code = None  # allocated at insert time
            linked = 0
            all_report_ids = cluster["report_ids"]

        # ── 6. Scoring ──────────────────────────────────────────────────────
        scoring_ids = all_report_ids if existing is not None else cluster["report_ids"]
        source_types = await _source_types(db, scoring_ids)
        weather, rainfall_mm = await weather_score(
            stats["centroid_lat"], stats["centroid_lng"]
        )

        scored = score_cluster(stats, source_types, weather, rainfall_mm)
        receipt = scored["receipt"]
        confidence = scored["confidence"]
        severity = scored["severity"]
        quadrant = scored["quadrant"]
        review_status = scored["review_status"]

        # ── 7. Persist, with the decision's audit row, in one transaction ───
        impact_radius = max(stats["radius_km"], 0.5)
        prior_status: Optional[str] = None

        if existing is not None:
            # Lock the event against a concurrent review (PATCH .../review takes
            # the same row lock), then honour whatever a human decided since.
            current = (
                await db.execute(
                    text("""
                        SELECT review_status, verification_receipt->'human_review'
                        FROM verified_events
                        WHERE id = CAST(:id AS uuid)
                        FOR UPDATE
                    """),
                    {"id": str(event_id)},
                )
            ).fetchone()
            prior_status = str(current[0])
            human_review = current[1] or None

            if prior_status == ReviewStatus.REJECTED.value:
                # Rejected between _find_mergeable_event and the lock. Leave the
                # event alone; the reports stay unlinked.
                await db.rollback()
                logger.info(
                    f"Pipeline: {event_code} was rejected while report {report_id} "
                    "was being processed — not merging"
                )
                return None

            # The machine keeps re-scoring as evidence accumulates, but it never
            # overwrites a human decision: an approval keeps its status, and a
            # severity override keeps its severity. confidence_score, the
            # factors and the footprint still update — the evidence is real.
            if human_review and human_review.get("severity_override"):
                severity = Severity(human_review["severity_override"])
                receipt["provenance"]["severity"] = "human_override"
            if prior_status == ReviewStatus.HUMAN_APPROVED.value:
                review_status = ReviewStatus.HUMAN_APPROVED
                quadrant = FusionEngine.human_approved_quadrant(severity)
            else:
                quadrant = FusionEngine().assign_quadrant(severity, confidence)
            if human_review:
                receipt["human_review"] = human_review

        common = {
            "id": str(event_id),
            "sev": severity.value,
            "conf": confidence,
            "status": review_status.value,
            "quad": quadrant.value,
            "radius": impact_radius,
            "lat": stats["centroid_lat"],
            "lng": stats["centroid_lng"],
            "receipt": json.dumps(receipt),
        }

        if existing is not None:
            await db.execute(
                text("""
                    UPDATE verified_events SET
                        severity = CAST(:sev AS severity_enum),
                        confidence_score = :conf,
                        review_status = CAST(:status AS review_status_enum),
                        quadrant = CAST(:quad AS quadrant_enum),
                        impact_radius_km = :radius,
                        center_point = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                        verification_receipt = CAST(:receipt AS jsonb)
                    WHERE id = CAST(:id AS uuid)
                """),
                common,
            )
            action = "updated"
        else:
            event_code = await _next_event_code(db)
            await db.execute(
                text("""
                    INSERT INTO verified_events
                        (id, event_code, event_type, severity, confidence_score,
                         review_status, quadrant, impact_radius_km, center_point,
                         verification_receipt)
                    VALUES
                        (CAST(:id AS uuid), :code,
                         CAST(:etype AS event_type_enum),
                         CAST(:sev AS severity_enum),
                         :conf,
                         CAST(:status AS review_status_enum),
                         CAST(:quad AS quadrant_enum),
                         :radius,
                         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                         CAST(:receipt AS jsonb))
                """),
                {**common, "code": event_code, "etype": EventType.URBAN_FLOOD.value},
            )
            # Link only after the event row exists — event_id is an FK.
            linked = await geo.assign_reports_to_event(
                cluster["report_ids"], event_id, commit=False
            )
            action = "created"

        report_count = (
            await db.execute(
                text("SELECT COUNT(*) FROM raw_reports WHERE event_id = CAST(:e AS uuid)"),
                {"e": str(event_id)},
            )
        ).scalar() or linked

        # The audit trail records decisions, not traffic: one row when an event
        # is created, one when a merge changes its status, none otherwise.
        if review_status.value != prior_status:
            await audit.record(
                db,
                event_id=event_id,
                operator_id=audit.SYSTEM_PIPELINE_OPERATOR,
                action=PIPELINE_AUDIT_ACTIONS[review_status],
                reason=(
                    f"{event_code} {action}: confidence {confidence} over "
                    f"{report_count} reports -> {review_status.value}"
                ),
                details={
                    "from_status": prior_status,
                    "to_status": review_status.value,
                    "confidence_score": confidence,
                    "report_count": report_count,
                    "severity": severity.value,
                },
            )

        await db.commit()

        logger.info(
            f"Pipeline: {action} {event_code} ({event_id}) with {report_count} reports — "
            f"severity={severity.value} confidence={confidence} status={review_status.value}"
        )

        return {
            "id": str(event_id),
            "event_code": event_code,
            "event_type": EventType.URBAN_FLOOD.value,
            "severity": severity.value,
            "confidence_score": confidence,
            "review_status": review_status.value,
            "quadrant": quadrant.value,
            "impact_radius_km": impact_radius,
            "lat": stats["centroid_lat"],
            "lng": stats["centroid_lng"],
            "report_count": report_count,
            "merged": existing is not None,
            "verification_receipt": receipt,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        # Fail soft: a pipeline crash must never kill the consumer loop.
        logger.error(f"Pipeline failed for report {report.get('id', 'unknown')}: {e}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
