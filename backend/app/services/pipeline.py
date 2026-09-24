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

import asyncio
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
from app.services.geocoding import reverse_geocode
from app.services.text_processing import extract_metadata
from app.services.weather import rainfall_to_score, weather_score

logger = logging.getLogger("indra.services.pipeline")
settings = get_settings()

# ── Severity: content first, corroboration second ─────────────────────────────
# Two independent axes; the event takes the higher of the two.
#
#   Depth   what the reports actually say about the water. This is the axis that
#           decides whether a boat is needed, and it is available from a single
#           report — one person saying "chest deep" is a more serious fact than
#           twenty people saying "wet road".
#   Count   how many independent reports there are. A large number of reports
#           about shallow water is still a real incident worth raising, even when
#           nobody quotes a depth.
#
# The depth cuts are operational, not learned: 20 cm stops a two-wheeler, 60 cm
# floats a small car and is above most plinths, 120 cm is above an adult's waist
# and turns wading into a rescue. These are published numbers a nodal officer can
# argue with, which is the point — there is no severity model here and the
# receipt's provenance says which axis decided.
#
# Extraction and its measured accuracy live in text_processing.extract_metadata
# and tests/test_text_processing.py.
SEVERITY_DEPTH_CRITICAL_CM = 120
SEVERITY_DEPTH_HIGH_CM = 60
SEVERITY_DEPTH_MODERATE_CM = 20

SEVERITY_COUNT_HIGH_REPORTS = 10
SEVERITY_COUNT_MODERATE_REPORTS = 5

# Ordering for "the higher of the two axes". Severity is a str enum, so max()
# over the members themselves compares alphabetically and CRITICAL < HIGH — this
# tuple is not decoration, it is what makes the comparison mean what it says.
SEVERITY_ORDER = (
    Severity.ADVISORY,
    Severity.MODERATE,
    Severity.HIGH,
    Severity.CRITICAL,
)

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


def _depth_severity(depth_cm: Optional[float]) -> Severity:
    """Severity from the deepest water any report in the cluster describes."""
    if depth_cm is None:
        return Severity.ADVISORY
    if depth_cm >= SEVERITY_DEPTH_CRITICAL_CM:
        return Severity.CRITICAL
    if depth_cm >= SEVERITY_DEPTH_HIGH_CM:
        return Severity.HIGH
    if depth_cm >= SEVERITY_DEPTH_MODERATE_CM:
        return Severity.MODERATE
    return Severity.ADVISORY


def _count_severity(cluster_size: int) -> Severity:
    """
    Severity from corroboration alone.

    Never reaches CRITICAL: a count is evidence that something is happening, not
    evidence of how bad it is. Calling an event CRITICAL because it was popular
    is the bug this whole rule replaces.
    """
    if cluster_size >= SEVERITY_COUNT_HIGH_REPORTS:
        return Severity.HIGH
    if cluster_size >= SEVERITY_COUNT_MODERATE_REPORTS:
        return Severity.MODERATE
    return Severity.ADVISORY


def _derive_severity(report_texts: Sequence[str], cluster_size: int) -> Dict[str, Any]:
    """
    Severity from what the reports say, not just how many there are.

    Replaces a rule that graded a disaster by cluster size alone, so one report
    saying "water two metres deep" was MODERATE while twelve saying "small
    puddle" was HIGH.

    Pure: extract_metadata is a regex pass with no I/O, no clock and no sampling,
    so the same cluster always yields the same severity. The maximum is
    order-independent, which matters because the texts arrive in whatever order
    Postgres returns them.

    Returns {"severity", "provenance", "basis"}. `basis` goes into the receipt so
    the reading is auditable: a commander can see that it was the phrase "knee
    deep" that made this MODERATE, and override it knowing what they override.
    """
    depths: List[tuple] = []
    for body in report_texts:
        meta = extract_metadata(body or "")
        if meta["depth_cm"] is not None:
            depths.append((int(meta["depth_cm"]), meta["depth_basis"]))

    max_depth_cm, depth_basis = max(depths, default=(None, None))

    depth_axis = _depth_severity(max_depth_cm)
    count_axis = _count_severity(cluster_size)
    severity = max(depth_axis, count_axis, key=SEVERITY_ORDER.index)

    return {
        "severity": severity,
        "provenance": (
            "rule_based_depth_and_count" if depths else "rule_based_count_only"
        ),
        "basis": {
            "rule": "max(depth_axis, count_axis)",
            "max_depth_cm": max_depth_cm,
            "depth_basis": depth_basis,
            "reports_with_depth": len(depths),
            "report_count": cluster_size,
            "depth_axis": depth_axis.value,
            "count_axis": count_axis.value,
        },
    }


# Report density saturates at 25 reports, shaped so a 10-report cluster already
# scores ~0.80. 25 is a property of this curve, not of any severity rule — it
# buys headroom so a 25-report event scores distinctly above a 10-report one. It
# used to alias the old count-based CRITICAL severity threshold, which no longer
# exists now that severity is derived from content.
# See _density_score; tests/test_scoring_curves.py pins density(25) == 1.0.
DENSITY_SATURATION_REPORTS = 25
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
    * It only reaches 1.0 at 25, leaving headroom so a major event scores
      distinctly above a moderate one. A linear ramp saturating at 10 made 10 and
      100 reports indistinguishable. (25 was once also the count at which
      severity became CRITICAL; severity is derived from report content now, so
      this number belongs to the curve alone.)

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
    *,
    report_texts: Sequence[str],
    weather_source: str = "open_meteo_live",
) -> Dict[str, Any]:
    """
    Pure scoring step: cluster geometry + source mix + weather + report text →
    receipt, severity, quadrant and review status.

    `report_texts` is keyword-only and deliberately has **no default**. Severity
    is derived from what the reports say, so a caller that forgot to pass them
    would silently grade every event on corroboration count alone — the exact bug
    this argument exists to fix, reintroduced invisibly and with no test failure.
    Better a TypeError at the call site.

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
        # No image classifier and no anomaly model ship this sprint, and after
        # the 20 Sep scope change they never will. Passing None excludes them
        # from the weighted mean instead of scoring them 0.0, so they no longer
        # cap a fully corroborated flood at 0.80. The cost stays visible and
        # honest in the receipt's `factor_coverage` (0.80, not 1.0) and in the
        # provenance block below — never as a plausible fake score.
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
        # Which path produced the number is part of the evidence, not a detail:
        # a stored reading came from this platform's own polled feed, a live one
        # from a request made while scoring.
        origin = (
            "polled station reading"
            if weather_source == "station_reading"
            else "Open-Meteo modelled precipitation"
        )
        evidence["Weather Station Corroboration"] = (
            f"{rainfall_mm:.1f} mm rainfall in past 24 h ({origin})"
        )
    for factor in receipt["factors"]:
        if factor["factor"] in evidence:
            factor["evidence"] = evidence[factor["factor"]]

    # The count axis uses stats["count"] (geometry-derived, consistent with the
    # density factor) rather than len(report_texts): a report with no geom_point
    # can still contribute its depth but must not contribute corroboration.
    decided = _derive_severity(report_texts, stats["count"])
    severity = decided["severity"]
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
        # rule_based_depth_and_count | rule_based_count_only — which evidence
        # actually graded this event. Overwritten with "human_override" further
        # down if a commander has set a severity_override.
        "severity": decided["provenance"],
    }
    # Severity as auditable as confidence: which axis won, what depth was found
    # and what phrase it came from. A new top-level block rather than more keys
    # under provenance, whose key set is asserted exactly by the determinism test.
    receipt["severity_basis"] = decided["basis"]
    receipt["cluster"] = {
        "size": stats["count"],
        "centroid_lat": stats["centroid_lat"],
        "centroid_lng": stats["centroid_lng"],
        "max_pairwise_km": stats["max_pairwise_km"],
        "radius_km": stats["radius_km"],
        "source_types": distinct_sources,
    }
    if rainfall_mm is not None:
        receipt["weather"] = {
            "rainfall_24h_mm": rainfall_mm,
            "provider": "open-meteo",
            "source": weather_source,
        }

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
                SELECT id, raw_text, latitude, longitude, created_at, event_id,
                       duplicate_of
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
        "duplicate_of": row[6],
    }


async def _dedup_candidates(db: AsyncSession, report: Dict[str, Any]):
    """
    Recent nearby reports, with the spatial and temporal gates pushed into SQL.

    Doing the filtering here rather than loading every recent report into Python
    keeps the embedding model — the expensive part — to a handful of comparisons.
    DedupService then applies the text-similarity gate over the survivors.

    Returns (original_ids, candidates): candidates are the (text, lat, lng,
    created_at) tuples DedupService takes, oldest first, and original_ids[i]
    is the report candidate i stands for. Earlier duplicates stay candidates —
    a third copy still matches — but they resolve to *their* original, so
    duplicate_of always points at an original and never at another duplicate.
    """
    rows = (
        await db.execute(
            text("""
                SELECT COALESCE(duplicate_of, id), raw_text, latitude, longitude, created_at
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
                ORDER BY created_at, id
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

    original_ids = [r[0] for r in rows]
    candidates = [(r[1], float(r[2]), float(r[3]), r[4]) for r in rows]
    return original_ids, candidates


async def _find_mergeable_event(
    db: AsyncSession, lat: float, lng: float
) -> Optional[Dict[str, Any]]:
    """
    The nearest recent event whose footprint already covers this location.

    Matches within the event's own impact radius plus one DBSCAN eps, so a
    cluster that DBSCAN would have merged had all the reports arrived together
    is merged after the fact too. Rejected events are excluded — an operator
    dismissing an event must not have it silently resurrected.

    The window is measured from `updated_at`, not `verified_at`. `verified_at`
    is an insert-time default that means "created", and merging into an event
    rewrites its score and receipt without touching it, so keying the window
    there closed an event to new reports two hours after it was born however
    recently it had absorbed one. That is how a report 50 m from a live
    event's centroid came to be dropped (BUG-035): an ongoing flood stops
    accepting corroboration while it is still flooding.
    """
    row = (
        await db.execute(
            text("""
                SELECT id, event_code
                FROM verified_events
                WHERE COALESCE(updated_at, verified_at)
                          > NOW() - make_interval(mins => CAST(:window AS int))
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


async def _weather_for_cluster(
    db: AsyncSession, lat: float, lng: float
) -> tuple[Optional[float], Optional[float], str]:
    """
    (score, rainfall_mm, source) for the Weather Station Corroboration factor,
    preferring the platform's own polled data over a live request.

    A stored reading is used when it is fresh enough and near enough
    (STATION_READING_MAX_AGE_MINUTES, STATION_READING_MAX_DISTANCE_KM); on a miss
    the behaviour is exactly what it was before Day 6. Two reasons to prefer the
    stored row: it is a measurement this platform holds and can show, and it lets
    an event be scored with the network unplugged.

    The curve is the same either way — only where the millimetres came from
    changes, and the receipt says which.
    """
    try:
        from app.workers.station_poller import latest_reading_near

        stored = await latest_reading_near(db, lat, lng)
    except Exception as e:
        logger.warning(f"Station reading lookup failed, falling back to live: {e}")
        stored = None

    if stored is not None:
        rainfall_mm, _recorded_at, _code = stored
        return rainfall_to_score(rainfall_mm), rainfall_mm, "station_reading"

    score, rainfall_mm = await weather_score(lat, lng)
    return score, rainfall_mm, "open_meteo_live"


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


async def _report_texts(db: AsyncSession, report_ids: Sequence[UUID]) -> List[str]:
    """
    The raw text of every report in a cluster, for content-derived severity.

    `duplicate_of IS NULL` is belt-and-braces: a suppressed duplicate never gets
    an event_id and is excluded from clustering, so it cannot reach here anyway.
    The guard is explicit because the severity rule takes a *maximum* over
    depths — without it, one reposted "chest deep water" could grade an event
    CRITICAL twice over, which is precisely the popularity-grading the rule
    exists to remove. (`_source_types` above has no such guard; harmless today
    because it takes a max over a bounded reliability table, but the asymmetry is
    deliberate, not an oversight.)
    """
    ids = [str(rid) for rid in report_ids]
    if not ids:
        return []
    rows = (
        await db.execute(
            text("""
                SELECT raw_text FROM raw_reports
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND duplicate_of IS NULL
            """),
            {"ids": ids},
        )
    ).fetchall()
    return [r[0] or "" for r in rows]


async def _set_boundary_polygon(db: AsyncSession, event_id: UUID) -> bool:
    """
    Recompute `verified_events.boundary_polygon` from the event's linked reports.

    The footprint an operator sees on the map: a hull around the reporting points,
    buffered by 250 m so it covers the street rather than just the pins.

        ST_Buffer(ST_ConcaveHull(ST_Collect(geom_point), 0.8)::geography, 250)

    Three things about that expression are load-bearing:

    * **The ::geography cast.** SRID 4326 is degrees, so buffering the geometry
      directly would take 250 *degrees*. Measured in metres only via geography.
    * **The hull of 1-2 points is not a polygon.** On GEOS 3.9 one point yields
      ST_Point and two yield ST_LineString (verified against this database). The
      buffer absorbs both into a polygon, which is why a lone report still gets a
      footprint — a 250 m disc of area ~195,000 m².
    * **The column is geometry(Polygon,4326).** A MULTIPOLYGON or a bare
      LINESTRING would be rejected outright, so the CASE falls back to a convex
      hull if a concave one ever returns something else.

    Duplicates are excluded: a suppressed repost must not stretch the footprint.

    Called after reports are linked, for both the create and merge paths, since
    on create the FK means linking can only happen once the event row exists.

    Returns True if a polygon was written. A failure here is logged and left NULL
    rather than raised: the event and its score are the product, and a missing
    map outline must not cost the operator the alert.

    **Runs inside a SAVEPOINT, and that is not optional.** Catching the Python
    exception is not enough — a server-side failure (a GEOS error on a degenerate
    hull, say) aborts the whole Postgres transaction, so every later statement in
    step 7 would fail with "current transaction is aborted", the blanket handler
    in process_report would roll back, and the event would be silently lost. The
    savepoint confines the damage to this one statement, which is the difference
    between "the map outline is missing" and "the alert never existed". Verified
    against this database: after a server-side error a plain session cannot run
    another statement, and a nested one can.
    """
    try:
        async with db.begin_nested():
            result = await db.execute(
                text("""
                    UPDATE verified_events SET boundary_polygon = hull.poly
                    FROM (
                        SELECT CASE
                            WHEN GeometryType(concave) = 'POLYGON' THEN concave
                            ELSE convex
                        END AS poly
                        FROM (
                            SELECT
                                ST_Buffer(
                                    ST_ConcaveHull(ST_Collect(geom_point), 0.8)::geography,
                                    250
                                )::geometry AS concave,
                                ST_Buffer(
                                    ST_ConvexHull(ST_Collect(geom_point))::geography,
                                    250
                                )::geometry AS convex
                            FROM raw_reports
                            WHERE event_id = CAST(:e AS uuid)
                              AND duplicate_of IS NULL
                              AND geom_point IS NOT NULL
                        ) shapes
                    ) hull
                    WHERE verified_events.id = CAST(:e AS uuid)
                      AND hull.poly IS NOT NULL
                      AND GeometryType(hull.poly) = 'POLYGON'
                """),
                {"e": str(event_id)},
            )
        return (result.rowcount or 0) > 0
    except Exception as e:
        logger.warning(
            f"Pipeline: could not compute boundary_polygon for event {event_id}, "
            f"leaving it NULL: {e}"
        )
        return False


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


async def _mark_processed(db: AsyncSession, *report_ids: UUID) -> None:
    """
    Record that the pipeline has finished with these reports, whatever it decided.

    Without it a report the pipeline looked at and found alone was
    indistinguishable from one it never saw, and the citizen's docket could not
    say which (migration 0012). Runs in the caller's transaction, so the stamp
    commits with the outcome or not at all; the first stamp stands. A pipeline
    crash leaves it unset, which is the truth: that report was not processed.

    When a run links a whole cluster into an event, every report it linked is
    finished with, not only the one whose message started the run: the others'
    own messages will find them linked and skip them.
    """
    await db.execute(
        text("""
            UPDATE raw_reports
            SET processed_at = COALESCE(processed_at, NOW())
            WHERE id = ANY(CAST(:ids AS uuid[]))
        """),
        {"ids": [str(r) for r in report_ids]},
    )


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

        if stored["duplicate_of"] is not None:
            logger.info(f"Pipeline: report {report_id} already suppressed as a duplicate — skipping")
            return None

        # ── 2. Deduplication ────────────────────────────────────────────────
        # A suppressed report is marked, not just skipped: duplicate_of keeps it
        # out of every later clustering run, so it is never counted as
        # corroboration by the reports that arrive after it.
        original_ids, candidates = await _dedup_candidates(db, stored)
        if candidates:
            # Off the event loop, via a worker thread.
            #
            # find_duplicate is synchronous and MiniLM's encode() is blocking,
            # CPU-bound work. Called directly from this coroutine it stalled the
            # whole uvicorn loop for the duration — about 13 s on the first report,
            # while the model loaded. The T14 cold-start rehearsal found this the
            # hard way: GET /api/events timed out completely, then answered in
            # 0.03 s once the model was in memory. Nothing could be served in that
            # window: not the API, not /healthz, not the WebSocket, on a cold start,
            # which is exactly when a demo begins.
            #
            # to_thread fixes the class of problem rather than the first instance —
            # every dedup check was serialising the loop for its own duration, not
            # just the first.
            match = await asyncio.to_thread(
                DedupService().find_duplicate,
                stored["raw_text"],
                stored["latitude"],
                stored["longitude"],
                stored["created_at"],
                candidates,
            )
            if match is not None:
                original_id = original_ids[match]
                await db.execute(
                    text("""
                        UPDATE raw_reports
                        SET duplicate_of = CAST(:original AS uuid)
                        WHERE id = CAST(:id AS uuid)
                    """),
                    {"original": str(original_id), "id": str(report_id)},
                )
                await _mark_processed(db, report_id)
                await db.commit()
                logger.info(
                    f"Pipeline: report {report_id} suppressed as duplicate of {original_id} "
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
                await _mark_processed(db, report_id)
                await db.commit()
                return None

            logger.info(
                f"Pipeline: lone report {report_id} joins existing {nearby['event_code']}"
            )
            cluster = {"cluster_id": -1, "report_ids": [report_id], "size": 1}

        # ── 5. Cluster geometry ─────────────────────────────────────────────
        stats = await geo.get_cluster_stats(cluster["report_ids"])
        if not stats["count"] or stats["centroid_lat"] is None:
            logger.warning(f"Pipeline: cluster for {report_id} has no usable geometry")
            await _mark_processed(db, report_id)
            await db.commit()
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
        report_texts = await _report_texts(db, scoring_ids)
        weather, rainfall_mm, weather_source = await _weather_for_cluster(
            db, stats["centroid_lat"], stats["centroid_lng"]
        )

        scored = score_cluster(
            stats,
            source_types,
            weather,
            rainfall_mm,
            report_texts=report_texts,
            weather_source=weather_source,
        )
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
                await _mark_processed(db, report_id)
                await db.commit()
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

        # Name the centroid. This goes in its own receipt block rather than
        # into `provenance`, which test_scoring_determinism pins key-for-key
        # because it is the record of which factors ran.
        place = reverse_geocode(stats["centroid_lat"], stats["centroid_lng"])
        receipt["location"] = {
            "district": place.district if place else None,
            "state": place.state if place else None,
            "precision": place.precision if place else "unresolved",
            "distance_km": place.distance_km if place else None,
            "basis": "nearest district in data/geo/india_districts.csv",
        }

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
            # Resolved from the centroid the event is actually being stored at,
            # so the name and the point can never disagree. None when the
            # resolver declines, which leaves the columns NULL rather than
            # asserting a place we could not identify.
            "district": place.district if place else None,
            "state": place.state if place else None,
            "precision": place.precision if place else None,
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
                        verification_receipt = CAST(:receipt AS jsonb),
                        district = :district,
                        state = :state,
                        place_precision = :precision,
                        -- Without this the merge window is keyed on creation
                        -- time and an active event stops accepting reports.
                        updated_at = NOW()
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
                         verification_receipt, district, state, place_precision,
                         updated_at)
                    VALUES
                        (CAST(:id AS uuid), :code,
                         CAST(:etype AS event_type_enum),
                         CAST(:sev AS severity_enum),
                         :conf,
                         CAST(:status AS review_status_enum),
                         CAST(:quad AS quadrant_enum),
                         :radius,
                         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                         CAST(:receipt AS jsonb),
                         :district, :state, :precision,
                         NOW())
                """),
                {**common, "code": event_code, "etype": EventType.URBAN_FLOOD.value},
            )
            # Link only after the event row exists — event_id is an FK.
            linked = await geo.assign_reports_to_event(
                cluster["report_ids"], event_id, commit=False
            )
            action = "created"

        # The event's footprint, from the reports now linked to it. Runs for both
        # paths and after linking, so a merge widens the polygon to cover the
        # reports it just absorbed.
        await _set_boundary_polygon(db, event_id)

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

        await _mark_processed(db, report_id, *cluster["report_ids"])
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
