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
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import AuditAction, EventType, ReviewStatus, Severity, Verdict
from app.services import audit, clock
from app.services.dedup import DedupService, find_similar_text
from app.services.fusion_engine import FusionEngine, decide_verdict, source_reliability_score
from app.services import severity_rules
from app.services.corroboration import effective_reporters, news_corroboration
from app.services.evidence import (
    PARTIAL_TYPES,
    RAIN_FAMILY_TYPES,
    Evidence,
    Window,
    combine_weather,
    contradicted,
    evidence_window,
    find_contradiction,
    group_stations,
    model_evidence,
    offline,
    station_evidence,
)
from app.services.official_warnings import official_warning_evidence
from app.services.event_typing import decide_event_type
from app.services.hazards import family_of, types_in_family
from app.services.geo_clustering import GeoClusteringService, family_params
from app.services.report_flags import CREDIBILITY_FLOOR, FLAGS
from app.services.geocoding import reverse_geocode
from app.services.ml_adapter import analyze_stored_event_group, analyze_stored_report
from app.services.text_processing import core_text, extract_metadata
from app.services.weather import fetch_air_quality, fetch_hourly, rainfall_to_score, weather_score

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

# Positions the spatial pipeline may use (raw_reports.place_precision, 0015):
# a device's GPS fix, or a post's single named district. A state centroid and
# "no place" are never clustered.
CLUSTERABLE_PRECISIONS = {"gps", "district"}

# Source types a poller collects (Phase 2): Mastodon posts, news headlines.
# They take their own dedup path, _feed_duplicate, never the citizen one.
FEED_SOURCE_TYPES = {"SOCIAL_MEDIA", "NEWS_MEDIA"}
# The most recent posts compared by text for one new post: bounds the model's
# work on a busy day.
FEED_TEXT_CANDIDATES = 200

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

# Why the last process_report() in this task failed, or None (Phase 2 T8).
#
# process_report never raises — a pipeline crash must not kill the consumer
# loop, and every caller relies on that. But "returned None" covers both "no
# event, correctly" and "crashed", and only the second should count towards
# the dead-letter topic. The consumer calls take_failure() straight after, in
# the same task, to tell them apart. A ContextVar, so concurrent tasks never
# see each other's failures.
_last_failure: ContextVar[Optional[str]] = ContextVar("pipeline_last_failure", default=None)


def take_failure() -> Optional[str]:
    """The last failure in this task, cleared as it is read; None if it succeeded."""
    failure = _last_failure.get()
    _last_failure.set(None)
    return failure


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


def _derive_severity(
    report_texts: Sequence[str],
    cluster_size: int,
    *,
    event_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Severity from what the reports say, not just how many there are.

        severity = max(content_axis, count_axis, impact_floor)

    Replaces a rule that graded a disaster by cluster size alone, so one report
    saying "water two metres deep" was MODERATE while twelve saying "small
    puddle" was HIGH.

    **The content axis depends on the hazard** (Phase 3 T7,
    services/severity_rules.py): depth or rainfall for water, temperature for
    heat and cold, visibility for fog, wind for the convective family, each on
    IMD's or Beaufort's published cuts. Impact words ("stranded", "died", "roof
    blown off") set a floor whatever the measure says. `event_type=None` grades
    a flood, as every event was before Phase 3.

    Pure: extract_metadata is a regex pass with no I/O, no clock and no sampling,
    so the same cluster always yields the same severity. Every maximum is
    order-independent, which matters because the texts arrive in whatever order
    Postgres returns them.

    Returns {"severity", "provenance", "basis"}. `basis` goes into the receipt so
    the reading is auditable: a commander can see that it was the phrase "46
    degree" or "knee deep" that set the grade, and override it knowing what they
    override.
    """
    metas = [extract_metadata(body or "") for body in report_texts]
    depths: List[tuple] = [
        (int(m["depth_cm"]), m["depth_basis"]) for m in metas if m["depth_cm"] is not None
    ]
    max_depth_cm, depth_basis = max(depths, default=(None, None))

    content = severity_rules.content_axis(event_type, metas)
    floor = severity_rules.impact_floor(report_texts, event_type)
    count_axis = _count_severity(cluster_size)
    severity = severity_rules.highest(
        content["severity"], count_axis, floor["severity"] if floor else Severity.ADVISORY
    )

    if content["axis"] == "water_depth":
        provenance = "rule_based_depth_and_count" if depths else "rule_based_count_only"
    elif content["value"] is not None:
        provenance = f"rule_based_{content['axis']}_and_count"
    else:
        provenance = "rule_based_count_only"
    if floor and severity == floor["severity"] and severity != max(
        content["severity"], count_axis, key=SEVERITY_ORDER.index
    ):
        provenance = "rule_based_impact_words"

    return {
        "severity": severity,
        "provenance": provenance,
        "basis": {
            "rule": "max(content_axis, count_axis, impact_floor)",
            "axis": content["axis"],
            "value": content["value"],
            "phrase": content["phrase"],
            "content_axis": content["severity"].value,
            "count_axis": count_axis.value,
            "impact_floor": (
                {"severity": floor["severity"].value, "phrase": floor["phrase"]} if floor else None
            ),
            "event_type": event_type,
            "report_count": cluster_size,
            # The depth reading, kept for every reader of the pre-Phase-3 receipt.
            "max_depth_cm": max_depth_cm,
            "depth_basis": depth_basis,
            "reports_with_depth": len(depths),
            "depth_axis": _depth_severity(max_depth_cm).value,
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


def _density_score(cluster_size: float) -> float:
    """
    Report Density: how much independent corroboration a cluster has.

    Since Phase 3 T8 the input is the cluster's effective independent reporters
    (services/corroboration.py), a float: five reports from one device are one
    witness, a spam report is a fifth of one. A plain report count still works.

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


def _coherence_score(max_pairwise_km: float, eps_km: Optional[float] = None) -> float:
    """
    Spatial Coherence: a tight cluster is more likely to be one real event
    than a diffuse one. Scored on the cluster's diameter d against the DBSCAN
    search diameter D = 2 × eps with a raised cosine, where eps is the hazard
    family's clustering radius (Phase 3 T5: 5 km for water, 25 km for a
    heatwave; DBSCAN_EPS_KM, 5 km, when not given):

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
    span = max((eps_km or settings.DBSCAN_EPS_KM) * 2.0, 0.001)
    d = max(0.0, float(max_pairwise_km))
    if d >= span:
        return 0.0
    return round(0.5 * (1.0 + math.cos(math.pi * d / span)), 4)


def review_caps(
    event_type: Optional[str], source_types: Sequence[Any], verdict: Optional[Any] = None
) -> List[str]:
    """
    Why an event may not be auto-published, whatever its confidence. Defined
    with the review gate in fusion_engine.review_caps (Phase 4 T4): contradicted,
    unclassified, posts_only.
    """
    from app.services.fusion_engine import review_caps as _caps

    return _caps(event_type, source_types, verdict)


def capped(review_status: ReviewStatus, caps: Sequence[str]) -> ReviewStatus:
    """AUTO_PUBLISHED becomes PENDING_HUMAN_REVIEW when a cap applies."""
    if caps and review_status is ReviewStatus.AUTO_PUBLISHED:
        return ReviewStatus.PENDING_HUMAN_REVIEW
    return review_status


def _legacy_evidence(
    event_type: Optional[str],
    weather: Optional[float],
    rainfall_mm: Optional[float],
    weather_source: str,
) -> Dict[str, Any]:
    """
    The evidence bundle for a caller that passes only the old rainfall pair
    (a pure test, a script): the rain family's 24 h figure and nothing else.
    The official factor is offline, since no feed was read.
    """
    from app.services.evidence import MODEL_UNAVAILABLE, RAIN_24H_TYPES

    etype = event_type or "URBAN_FLOOD"
    rain_type = etype in RAIN_24H_TYPES or etype == "CLOUDBURST"
    if weather is not None and rain_type:
        where = (
            "polled station reading" if weather_source == "station_reading"
            else "Open-Meteo modelled precipitation"
        )
        reason = (
            f"{rainfall_mm:.1f} mm rainfall in past 24 h ({where})"
            if rainfall_mm is not None else "Weather Station Corroboration data integrated"
        )
        weather_ev = Evidence(
            float(weather), "computed", "24 h precipitation", rainfall_mm,
            source="open_meteo_model", reason=reason,
            detail={"rain_24h_mm": rainfall_mm},
        )
    elif rain_type:
        # The rainfall request answered nothing: the same line the pipeline
        # prints when Open-Meteo is down.
        weather_ev = offline(MODEL_UNAVAILABLE, variable="24 h precipitation")
    else:
        weather_ev = offline("no weather evidence was gathered for this call")
    return {
        "window": None,
        "weather": weather_ev,
        "model": weather_ev,
        "station": None,
        "stations_seen": 0,
        "official": offline("no official-warning lookup was made for this call"),
        "contradiction": None,
        "news": None,
        "rainfall_mm": rainfall_mm if weather is not None else None,
        "weather_source": weather_source,
    }


def score_cluster(
    stats: Dict[str, Any],
    source_types: Sequence[Any],
    weather: Optional[float] = None,
    rainfall_mm: Optional[float] = None,
    *,
    report_texts: Sequence[str],
    weather_source: str = "open_meteo_live",
    event_type: Optional[str] = None,
    event_type_basis: Optional[Dict[str, Any]] = None,
    density: Optional[Dict[str, Any]] = None,
    eps_km: Optional[float] = None,
    cluster_basis: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Pure scoring step: cluster geometry + source mix + evidence + report text →
    receipt v2, verdict, severity, quadrant and review status.

    **Phase 4** passes `evidence`, _gather_evidence()'s bundle: the weather
    factor for this hazard (station or model, T1–T2), the official warning
    (T4), the contradiction (T3) and the news publisher count (T6). A caller
    that passes only the old `weather` / `rainfall_mm` pair gets the rain
    family's 24 h figure as the weather factor and the official factor offline.

    Phase 3 added, all keyword-only and optional:

    * `event_type` and its `event_type_basis` (T6): the hazard's own severity
      axis (T7) and the review caps;
    * `density` — effective_reporters() (T8): Report Density scores n_eff, not
      the report count, and the receipt shows the arithmetic;
    * `eps_km` — the family's radius, for Spatial Coherence (T5);
    * `cluster_basis` — how the cluster was found (family, window, candidates).

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
    if evidence is None:
        evidence = _legacy_evidence(event_type, weather, rainfall_mm, weather_source)

    density_input = density["n_eff"] if density is not None else stats["count"]
    density_score = _density_score(density_input)
    eps = eps_km or settings.DBSCAN_EPS_KM
    coherence = _coherence_score(stats["max_pairwise_km"], eps)

    news = evidence.get("news")
    news_score = news["score"] if news else None
    reliability = source_reliability_score(source_types, news_score)

    # A contradiction scores the weather factor 0.0, online, whatever it read
    # (T3): the reason goes first on its line.
    contradiction = evidence.get("contradiction")
    weather_ev: Evidence = evidence["weather"]
    if contradiction:
        weather_ev = contradicted(weather_ev, contradiction)
    official_ev: Evidence = evidence["official"]
    contradictions = [contradiction] if contradiction else []

    receipt = fusion.compute_receipt(
        weather_score=weather_ev.score,
        official_score=official_ev.score,
        report_density_score=density_score,
        spatial_score=coherence,
        # Image and anomaly models produce separate advisory ML evidence, but
        # they are layer 4, frozen, and not calibrated fusion factors. They are
        # permanently offline here: excluded from the weighted mean, and
        # visible in `factor_coverage` and provenance below.
        vision_score=None,
        reliability_score=reliability,
        anomaly_score=None,
    )
    confidence = receipt["confidence_score"]

    # Replace the generic evidence text with what was actually measured.
    distinct_sources = sorted({str(getattr(t, "value", t)) for t in source_types})
    if density is not None:
        basis = density["basis"]
        density_text = (
            f"{basis['reports']} report(s), {density['n_eff']:g} independent witness(es) "
            f"from {basis['distinct_reporters']} reporter(s)"
        )
    else:
        density_text = f"{stats['count']} corroborating report(s) in cluster"
    reliability_text = None
    if reliability is not None:
        reliability_text = f"highest-reliability source among {', '.join(distinct_sources)}"
        if news and news["score"] is not None:
            reliability_text += f"; news {news['score']:.2f}, {news['line']}"
    evidence_text = {
        "report_density": density_text,
        "spatial_coherence": (
            f"cluster diameter {stats['max_pairwise_km']:.2f} km "
            f"against {eps * 2:.0f} km search diameter"
        ),
        "source_reliability": reliability_text,
        "weather_station": weather_ev.reason or None,
        "official_warning": official_ev.reason or None,
        "vision_analysis": "layer 4 (AI/ML) is out of scope: permanently offline",
        "anomaly_detection": "layer 4 (AI/ML) is out of scope: permanently offline",
    }
    sources = {
        "weather_station": weather_ev.source,
        "official_warning": official_ev.source,
    }
    for factor in receipt["factors"]:
        text_ = evidence_text.get(factor["key"])
        if text_:
            factor["evidence"] = text_
        if factor["key"] in sources:
            factor["source"] = sources[factor["key"]]
        if factor["key"] == "weather_station" and weather_ev.contradiction:
            factor["contradiction"] = True

    # The count axis uses stats["count"] (geometry-derived, consistent with the
    # density factor) rather than len(report_texts): a report with no geom_point
    # can still contribute its depth but must not contribute corroboration.
    decided = _derive_severity(report_texts, stats["count"], event_type=event_type)
    severity = decided["severity"]
    quadrant = fusion.assign_quadrant(severity, confidence)

    verdict = decide_verdict(contradictions, official_ev.score, weather_ev.score)
    caps = review_caps(event_type, source_types, verdict["verdict"])
    review_status = fusion.determine_review_status(
        confidence,
        settings.AUTO_PUBLISH_THRESHOLD,
        settings.HUMAN_REVIEW_THRESHOLD,
        severity=severity,
        caps=caps,
    )

    def _state(value: Optional[float]) -> str:
        return "computed" if value is not None else "offline"

    # Be explicit in the stored receipt about what is real and what is not,
    # so nobody downstream mistakes a missing signal for a measurement.
    receipt["provenance"] = {
        "report_density": "computed",
        "spatial_coherence": "computed",
        "weather_station": _state(weather_ev.score),
        "official_warning": _state(official_ev.score),
        "vision_analysis": "offline",
        "source_reliability": _state(reliability),
        "anomaly_detection": "offline",
        # rule_based_depth_and_count | rule_based_count_only — which evidence
        # actually graded this event. Overwritten with "human_override" further
        # down if a commander has set a severity_override.
        "severity": decided["provenance"],
    }
    # The evidence behind each independent factor, whole: its source (an
    # airport's METAR, the Open-Meteo model, a SACHET warning), its window,
    # its lines and the numbers they were read from.
    receipt["evidence"] = {
        "weather_station": weather_ev.as_dict(),
        "official_warning": official_ev.as_dict(),
    }
    if evidence.get("window") is not None:
        receipt["evidence_window"] = evidence["window"].as_dict()
    receipt["contradictions"] = [
        {"factor": c["factor"], "rule": c["rule"], "reason": c["reason"]} for c in contradictions
    ]
    receipt["verdict"] = {"value": verdict["verdict"].value, **verdict["basis"]}
    if news and news["count"]:
        receipt["news_basis"] = news
    # Severity as auditable as confidence: which axis won, what depth was found
    # and what phrase it came from. A new top-level block rather than more keys
    # under provenance, whose key set is asserted exactly by the determinism test.
    receipt["severity_basis"] = decided["basis"]
    receipt["routing"] = _routing(severity, confidence, review_status, caps)
    receipt["cluster"] = {
        "size": stats["count"],
        "centroid_lat": stats["centroid_lat"],
        "centroid_lng": stats["centroid_lng"],
        "max_pairwise_km": stats["max_pairwise_km"],
        "radius_km": stats["radius_km"],
        "source_types": distinct_sources,
        "eps_km": eps,
    }
    if cluster_basis is not None:
        receipt["cluster"]["clustering"] = cluster_basis
    if event_type_basis is not None:
        receipt["event_type_basis"] = event_type_basis
    if density is not None:
        receipt["density_basis"] = density["basis"]
    if evidence.get("rainfall_mm") is not None:
        receipt["weather"] = {
            "rainfall_24h_mm": evidence["rainfall_mm"],
            "provider": "open-meteo",
            "source": evidence.get("weather_source") or weather_source,
        }

    return {
        "receipt": receipt,
        "confidence": confidence,
        "severity": severity,
        "quadrant": quadrant,
        "review_status": review_status,
        "caps": caps,
        "verdict": verdict["verdict"],
        "contradictions": contradictions,
    }


def _routing(
    severity: Severity,
    confidence: float,
    review_status: ReviewStatus,
    caps: Sequence[str] = (),
) -> Dict[str, Any]:
    """
    Why the event is where it is, for the receipt. "severity" means a HIGH or
    CRITICAL event below the review gate that went to a human instead of into
    quarantine (BUG-067); an operator seeing a 0.45 event in the queue should
    be able to read why. "cap" means the confidence cleared the auto-publish
    gate but a cap (review_caps) held it for a human.
    """
    by_severity = (
        confidence < settings.HUMAN_REVIEW_THRESHOLD
        and review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    )
    by_cap = (
        bool(caps)
        and confidence >= settings.AUTO_PUBLISH_THRESHOLD
        and review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    )
    return {
        "review_status": review_status.value,
        "basis": "cap" if by_cap else ("severity" if by_severity else "confidence"),
        "caps": list(caps),
        "auto_publish_threshold": settings.AUTO_PUBLISH_THRESHOLD,
        "human_review_threshold": settings.HUMAN_REVIEW_THRESHOLD,
    }


async def _load_report(db: AsyncSession, report_id: UUID) -> Optional[Dict[str, Any]]:
    """
    Re-read the stored row — the authority on this report's coordinates.

    Since Phase 2 a report may have no coordinates (a post that names no
    place) or coordinates without a geometry (a state centroid): `latitude`
    and `longitude` are then None, `has_geom` False, and the pipeline measures
    no distance from it.
    """
    row = (
        await db.execute(
            text("""
                SELECT id, raw_text, latitude, longitude, created_at, event_id,
                       duplicate_of, CAST(source_type AS text) AS source_type, place_precision,
                       platform, source_meta, observed_at,
                       geom_point IS NOT NULL AS has_geom, district, state,
                       hazard_primary, hazard_family, COALESCE(flags, '{}'::text[]),
                       citizen_hazard, reporter_hash, credibility_score
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
        "latitude": float(row[2]) if row[2] is not None else None,
        "longitude": float(row[3]) if row[3] is not None else None,
        "created_at": row[4],
        "event_id": row[5],
        "duplicate_of": row[6],
        "source_type": row[7],
        "place_precision": row[8] or "gps",
        "platform": row[9],
        "source_meta": row[10] or {},
        "observed_at": row[11],
        "has_geom": bool(row[12]),
        "district": row[13],
        "state": row[14],
        # Phase 3 (0017): what the text is about, and its flags.
        "hazard_primary": row[15],
        "hazard_family": row[16],
        "flags": list(row[17] or []),
        "citizen_hazard": row[18],
        "reporter_hash": row[19],
        "credibility": float(row[20]) if row[20] is not None else None,
    }


async def _dedup_candidates(db: AsyncSession, report: Dict[str, Any]):
    """
    Recent nearby reports, with the spatial and temporal gates pushed into SQL.

    Doing the filtering here rather than loading every recent report into Python
    keeps local duplicate comparisons to a handful of nearby candidates.
    DedupService then applies the frozen Phase 19 similarity decision.

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
                  -- Reports people filed only. A post placed at a district
                  -- centroid is not "within 1 km" of anyone: it has its own
                  -- dedup path (_feed_duplicate), and citizen dedup stays
                  -- exactly as measured (BUG-013).
                  AND COALESCE(place_precision, 'gps') = 'gps'
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


async def _feed_duplicate(db: AsyncSession, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    The earlier post or headline this one repeats, as {"original", "basis"}, or
    None. Phase 2 T7: re-sharing is not witnessing — "crowd volume is not
    independent confirmation" — so one story shared twenty times counts once.

    Two rules, checked in order, against earlier SOCIAL_MEDIA and NEWS_MEDIA
    reports only:

    1. **The same article.** Both link to the same page once URLs are
       canonicalised (tracking parameters, `www.`, AMP paths and trailing
       slashes removed at collection), within FEED_DEDUP_LINK_WINDOW_HOURS.
    2. **The same text about the same place.** Same district (or the same
       state for a state-level post, or both placed nowhere), observed within
       FEED_DEDUP_TEXT_WINDOW_HOURS of each other, and the same words: an
       identical headline key, or local edit similarity on the text without
       its links and hashtag tail. This is how a news
       outlet's Mastodon post and its own RSS item become one.

    Citizen dedup keeps its separate 1 km / 15 min gates and frozen matcher.
    """
    params = {"id": str(report["id"]), "created_at": report["created_at"]}

    links = [l for l in (report["source_meta"].get("links") or []) if isinstance(l, str)]
    if links:
        row = (await db.execute(
            text("""
                SELECT COALESCE(duplicate_of, id)
                FROM raw_reports
                WHERE id <> CAST(:id AS uuid)
                  AND CAST(source_type AS text) IN ('SOCIAL_MEDIA', 'NEWS_MEDIA')
                  AND created_at <= CAST(:created_at AS timestamptz)
                  AND created_at > CAST(:created_at AS timestamptz)
                                   - make_interval(hours => CAST(:hours AS int))
                  AND jsonb_typeof(source_meta->'links') = 'array'
                  AND jsonb_exists_any(source_meta->'links', CAST(:links AS text[]))
                ORDER BY created_at, id
                LIMIT 1
            """),
            {**params, "hours": settings.FEED_DEDUP_LINK_WINDOW_HOURS, "links": links},
        )).first()
        if row is not None:
            return {"original": row[0], "basis": {"rule": "shared_link"}}

    observed = report["observed_at"] or report["created_at"]
    rows = (await db.execute(
        text("""
            SELECT COALESCE(duplicate_of, id), raw_text, source_meta->>'headline_key'
            FROM raw_reports
            WHERE id <> CAST(:id AS uuid)
              AND CAST(source_type AS text) IN ('SOCIAL_MEDIA', 'NEWS_MEDIA')
              AND created_at <= CAST(:created_at AS timestamptz)
              AND COALESCE(observed_at, created_at)
                    BETWEEN CAST(:observed AS timestamptz) - make_interval(hours => CAST(:hours AS int))
                        AND CAST(:observed AS timestamptz) + make_interval(hours => CAST(:hours AS int))
              AND district IS NOT DISTINCT FROM CAST(:district AS varchar)
              AND state IS NOT DISTINCT FROM CAST(:state AS varchar)
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
        """),
        {
            **params,
            "observed": observed,
            "hours": settings.FEED_DEDUP_TEXT_WINDOW_HOURS,
            "district": report["district"],
            "state": report["state"],
            "limit": FEED_TEXT_CANDIDATES,
        },
    )).fetchall()
    if not rows:
        return None
    # Oldest first, so the earliest copy is the one matched.
    rows = list(reversed(rows))

    key = report["source_meta"].get("headline_key")
    if key:
        for original, _text, candidate_key in rows:
            if candidate_key == key:
                return {"original": original, "basis": {"rule": "same_headline"}}

    mine = core_text(report["raw_text"])
    theirs = [core_text(r[1]) for r in rows]
    match = await asyncio.to_thread(find_similar_text, mine, theirs)
    if match is None:
        return None
    index, similarity, method = match
    return {
        "original": rows[index][0],
        "basis": {"rule": "same_text_same_place", "similarity": similarity, "method": method},
    }


async def _find_mergeable_event(
    db: AsyncSession, lat: float, lng: float, family: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    The nearest recent event whose footprint already covers this location.

    Matches within the event's own impact radius plus one DBSCAN eps, so a
    cluster that DBSCAN would have merged had all the reports arrived together
    is merged after the fact too. Rejected events are excluded — an operator
    dismissing an event must not have it silently resurrected.

    **By family** (Phase 3 T6): a cluster merges only into an event of its own
    hazard family, over that family's radius and window (a heatwave report
    never joins a flood event next door). An untagged cluster (family None)
    may join an event of any family, and any cluster may join an UNCLASSIFIED
    event, which the merge then re-types by majority. **An event a commander
    re-typed** also takes clusters of the family its reports voted for (the
    receipt's `override.machine_vote`): people keep calling it what they called
    it, and splitting the incident in two would undo the correction on the map.

    The window is measured from `updated_at`, not `verified_at`. `verified_at`
    is an insert-time default that means "created", and merging into an event
    rewrites its score and receipt without touching it, so keying the window
    there closed an event to new reports two hours after it was born however
    recently it had absorbed one. That is how a report 50 m from a live
    event's centroid came to be dropped (BUG-035): an ongoing flood stops
    accepting corroboration while it is still flooding.
    """
    params = family_params(family)
    row = (
        await db.execute(
            text("""
                SELECT id, event_code
                FROM verified_events
                WHERE COALESCE(updated_at, verified_at)
                          > NOW() - make_interval(mins => CAST(:window AS int))
                  AND review_status <> 'REJECTED'
                  AND center_point IS NOT NULL
                  AND (CAST(:family AS text) IS NULL
                       OR hazard_family IS NULL
                       OR hazard_family = CAST(:family AS text)
                       OR verification_receipt->'event_type_basis'->'override'->>'machine_vote'
                          = ANY(CAST(:family_types AS text[])))
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
                # The longer of the old two-hour window and the family's own:
                # a heatwave event stays open for a day.
                "window": max(MERGE_WINDOW_MINUTES, params.window_hours * 60),
                "lat": lat,
                "lng": lng,
                "eps": params.eps_km,
                "family": family,
                "family_types": types_in_family(family) if family else [],
            },
        )
    ).fetchone()

    if row is None:
        return None
    return {"id": row[0], "event_code": row[1]}


async def _cluster_reports(db: AsyncSession, report_ids: Sequence[UUID]) -> List[Dict[str, Any]]:
    """
    Every non-duplicate report in a cluster, with what the type vote (T6), the
    severity (T7) and the independent-reporter count (T8, T9) read: text,
    source, tagged hazard, the citizen's pick, reporter, credibility, flags and
    a news item's publisher. Oldest first, so every derived list is stable.
    """
    ids = [str(rid) for rid in report_ids]
    if not ids:
        return []
    rows = (
        await db.execute(
            text("""
                SELECT id, raw_text, CAST(source_type AS text), hazard_primary, citizen_hazard,
                       reporter_hash, credibility_score, COALESCE(flags, '{}'::text[]),
                       COALESCE(source_meta->>'publisher_domain', source_meta->>'publisher'),
                       COALESCE(observed_at, created_at),
                       source_meta->>'publisher_domain', source_meta->>'publisher'
                FROM raw_reports
                WHERE id = ANY(CAST(:ids AS uuid[]))
                  AND duplicate_of IS NULL
                ORDER BY created_at, id
            """),
            {"ids": ids},
        )
    ).fetchall()
    return [
        {
            "id": r[0],
            "raw_text": r[1] or "",
            "source_type": r[2],
            "hazard_primary": r[3],
            "citizen_hazard": r[4],
            "reporter_hash": r[5],
            "credibility": float(r[6]) if r[6] is not None else 0.0,
            "flags": list(r[7] or []),
            "publisher": r[8],
            # Phase 4: when it was observed (the evidence window), and the
            # publisher's domain and name apart (T6 counts domains, prints names).
            "at": r[9],
            "publisher_domain": r[10],
            "publisher_name": r[11],
        }
        for r in rows
    ]


# ── Phase 4: what the evidence queries read ────────────────────────────────────

async def _metar_observations(
    db: AsyncSession, lat: float, lng: float, start: datetime, end: datetime
) -> List[Dict[str, Any]]:
    """
    Every airport observation within 50 km of a point between start and end,
    with its distance and, from the station table, whether the aerodrome is
    civil and its elevation (T2). Empty on any failure, which is "no station",
    never an error: the model evidence still applies.
    """
    from app.services.evidence import STATION_MAX_KM
    from app.workers.metar_poller import station_table

    try:
        async with db.begin_nested():
            rows = (await db.execute(
                text("""
                    SELECT station_code, station_name, recorded_at, temperature_c, wind_kmh,
                           gust_kmh, visibility_m, COALESCE(weather_codes, '{}'::text[]),
                           COALESCE(convective_cloud, false),
                           ST_Distance(
                               station_location::geography,
                               ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                           ) / 1000.0
                    FROM station_readings
                    WHERE feed = 'metar'
                      AND station_location IS NOT NULL
                      AND recorded_at BETWEEN CAST(:start AS timestamptz) AND CAST(:end AS timestamptz)
                      AND ST_DWithin(
                            station_location::geography,
                            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                            :metres
                          )
                    ORDER BY 10, recorded_at
                """),
                {"lat": lat, "lng": lng, "start": start, "end": end,
                 "metres": STATION_MAX_KM * 1000.0},
            )).fetchall()
    except Exception as e:
        logger.warning(f"METAR lookup failed, model evidence only: {type(e).__name__}: {e}")
        return []

    table = station_table()
    out = []
    for r in rows:
        known = table.get(r[0]) or {}
        out.append({
            "station_code": r[0],
            "station_name": r[1],
            "recorded_at": r[2],
            "temperature_c": r[3],
            "wind_kmh": r[4],
            "gust_kmh": r[5],
            "visibility_m": r[6],
            "weather_codes": list(r[7] or []),
            "convective_cloud": bool(r[8]),
            "distance_km": float(r[9]),
            "civil": bool(known.get("civil")),
            "elevation_m": known.get("elevation_m"),
        })
    return out


# How many district headlines T6 reads at most for one event.
NEWS_CONTEXT_LIMIT = 200


async def _district_warning_news(
    db: AsyncSession,
    *,
    exclude_ids: Sequence[UUID],
    family: Optional[str],
    district: Optional[str],
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    """
    Warning-tense headlines of the event's hazard family and district inside
    the evidence window that are not in its cluster (T6): news context the
    clustering rightly kept out of the event's geometry. Empty without a
    family or a district, or on failure.
    """
    if not family or not district:
        return []
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                text("""
                    SELECT source_meta->>'publisher_domain', source_meta->>'publisher'
                    FROM raw_reports
                    WHERE CAST(source_type AS text) = 'NEWS_MEDIA'
                      AND duplicate_of IS NULL
                      AND hazard_family = :family
                      AND lower(district) = lower(:district)
                      AND 'not_an_observation' = ANY(COALESCE(flags, '{}'::text[]))
                      AND COALESCE(observed_at, created_at)
                            BETWEEN CAST(:start AS timestamptz) AND CAST(:end AS timestamptz)
                      AND NOT (id = ANY(CAST(:ids AS uuid[])))
                    ORDER BY created_at
                    LIMIT :limit
                """),
                {
                    "family": family, "district": district, "start": start, "end": end,
                    "ids": [str(i) for i in exclude_ids], "limit": NEWS_CONTEXT_LIMIT,
                },
            )).fetchall()
    except Exception as e:
        logger.warning(f"District news lookup failed: {type(e).__name__}: {e}")
        return []
    return [
        {"publisher_domain": r[0], "publisher": r[1], "forecast": True, "in_cluster": False}
        for r in rows
    ]


# Phase 3 T8: `coordinated`. The same text from this many different reporters
# within the window is a campaign, not a crowd. Texts shorter than the minimum
# (after normalising) are skipped: three people really do write "heavy rain
# here" in the same ten minutes.
COORDINATED_MIN_REPORTERS = 3
COORDINATED_WINDOW_MINUTES = 10
COORDINATED_MIN_CHARS = 30

# Lower case, punctuation to spaces, whitespace collapsed: the same message
# with a different emoji or full stop is the same message.
_NORMALISED_TEXT_SQL = (
    "btrim(regexp_replace(regexp_replace(lower({col}), '[[:punct:][:space:]]+', ' ', 'g'), '\\s+', ' ', 'g'))"
)


async def _mark_coordinated(db: AsyncSession, report: Dict[str, Any]) -> List[UUID]:
    """
    Flag `coordinated` on this report and its copies when the same normalised
    text arrives from COORDINATED_MIN_REPORTERS or more different reporters
    within COORDINATED_WINDOW_MINUTES (a missing reporter id counts as its own
    reporter). Each flagged report's credibility is halved once, floored at
    0.05 (report_flags.FLAGS). Runs in the caller's transaction.

    Citizen dedup (1 km, 15 min) already suppresses copies close together; this
    catches the same message sent from far apart, which dedup never sees.
    Returns the ids newly flagged.
    """
    norm_me = _NORMALISED_TEXT_SQL.format(col="me.raw_text")
    norm_r = _NORMALISED_TEXT_SQL.format(col="r.raw_text")
    rows = (
        await db.execute(
            text(f"""
                WITH me AS (
                    SELECT raw_text, created_at FROM raw_reports WHERE id = CAST(:id AS uuid)
                )
                SELECT r.id, COALESCE(r.reporter_hash, CAST(r.id AS text)),
                       'coordinated' = ANY(COALESCE(r.flags, '{{}}'::text[]))
                FROM raw_reports r, me
                WHERE length({norm_me}) >= :min_chars
                  AND r.created_at BETWEEN me.created_at - make_interval(mins => CAST(:window AS int))
                                       AND me.created_at + make_interval(mins => CAST(:window AS int))
                  AND {norm_r} = {norm_me}
            """),
            {
                "id": str(report["id"]),
                "window": COORDINATED_WINDOW_MINUTES,
                "min_chars": COORDINATED_MIN_CHARS,
            },
        )
    ).fetchall()
    if len({r[1] for r in rows}) < COORDINATED_MIN_REPORTERS:
        return []
    fresh = [r[0] for r in rows if not r[2]]
    if not fresh:
        return []
    await db.execute(
        text("""
            UPDATE raw_reports SET
                flags = array_append(COALESCE(flags, '{}'::text[]), 'coordinated'),
                credibility_score = GREATEST(CAST(:floor AS double precision),
                    CAST(round(CAST(credibility_score * CAST(:factor AS double precision) AS numeric), 4)
                         AS double precision)),
                analysis = CASE WHEN analysis IS NULL THEN NULL ELSE
                    jsonb_set(
                        jsonb_set(analysis, '{flags}',
                                  COALESCE(analysis->'flags', '[]'::jsonb) || '["coordinated"]'::jsonb),
                        '{flag_basis}',
                        COALESCE(analysis->'flag_basis', '{}'::jsonb)
                            || jsonb_build_object('coordinated', CAST(:basis AS text))
                    )
                END
            WHERE id = ANY(CAST(:ids AS uuid[]))
              AND NOT 'coordinated' = ANY(COALESCE(flags, '{}'::text[]))
        """),
        {
            "ids": [str(i) for i in fresh],
            "floor": CREDIBILITY_FLOOR,
            "factor": FLAGS["coordinated"],
            "basis": (
                f"the same text from {len({r[1] for r in rows})} reporters within "
                f"{COORDINATED_WINDOW_MINUTES} minutes"
            ),
        },
    )
    logger.info(f"Pipeline: {len(fresh)} report(s) flagged coordinated with {report['id']}")
    return fresh


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


# ── Phase 4: gathering the evidence for one cluster ────────────────────────────

# Types whose evidence reads the 24 h rainfall path above (the rain family, and
# a cyclone, whose rain is partial evidence).
EVIDENCE_RAIN_TYPES = frozenset(RAIN_FAMILY_TYPES | {"CYCLONE"})
# Types whose evidence reads the hourly model series (T1): everything but the
# plain rain family, which reads its 24 h figure only, and UNCLASSIFIED.
EVIDENCE_HOURLY_TYPES = frozenset({
    "CLOUDBURST", "CYCLONE", "CYCLONE_INUNDATION", "HEATWAVE", "COLD_WAVE", "FOG",
    "STRONG_WIND", "THUNDERSTORM", "LIGHTNING", "HAILSTORM", "DUST_STORM",
})


def observed_span(reports: Sequence[Dict[str, Any]], fallback: datetime):
    """
    (first, last) observation time of a cluster: its observations, or every
    report when all of them are forecasts, or `fallback` twice with none.
    """
    observed = [r["at"] for r in reports if r.get("at") and "not_an_observation" not in r["flags"]]
    times = observed or [r["at"] for r in reports if r.get("at")]
    if not times:
        return fallback, fallback
    return min(times), max(times)


async def _gather_evidence(
    db: AsyncSession,
    *,
    event_type: Optional[str],
    lat: float,
    lng: float,
    reports: Sequence[Dict[str, Any]],
    report_ids: Optional[Sequence[UUID]] = None,
    event_id: Optional[UUID] = None,
    district: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Everything independent of the reports that speaks to this event (T1–T6),
    ready for score_cluster(evidence=…):

    * `window` — where the evidence is read (services/evidence.py);
    * `weather` — the Weather Station Corroboration factor: the airport's
      measurement where one is near, the model otherwise;
    * `official` — the official-warning factor (SACHET);
    * `contradiction` — the published rule the weather broke, or None;
    * `news` — the publisher count (T6);
    * `rainfall_mm`, `weather_source` — the rain family's 24 h figure and
      where it came from, for the receipt's `weather` block as before.

    I/O happens here and only here; each source that fails is offline, never
    an exception.
    """
    now = clock.now()
    span_start, span_end = observed_span(reports, now)
    window = evidence_window(event_type, span_start, span_end, now)

    rain_score = rainfall_mm = None
    weather_source = "not_applicable"
    if event_type is None or event_type in EVIDENCE_RAIN_TYPES:
        rain_score, rainfall_mm, weather_source = await _weather_for_cluster(db, lat, lng)

    series = air = None
    if event_type in EVIDENCE_HOURLY_TYPES:
        series = await fetch_hourly(lat, lng)
        if event_type == "DUST_STORM":
            air = await fetch_air_quality(lat, lng)

    model = model_evidence(
        event_type, window, series, air=air,
        rainfall_mm=rainfall_mm, rainfall_origin=weather_source, rain_score=rain_score,
    )
    stations: List[Dict[str, Any]] = []
    station = None
    if event_type != EventType.UNCLASSIFIED.value:
        observations = await _metar_observations(db, lat, lng, window.start, window.end)
        stations = group_stations(observations, window)
        hill_hint = model.detail.get("hill") if series is not None else None
        station = station_evidence(event_type, stations, window, hill_hint=hill_hint)
    weather = combine_weather(event_type, model, station)

    official, cyclone_nearby = await official_warning_evidence(
        db, event_type, now=now, lat=lat, lng=lng,
        report_ids=report_ids, event_id=event_id, district=district,
    )
    contradiction = find_contradiction(
        event_type, weather, model, stations, window, cyclone_warning_nearby=cyclone_nearby,
    )

    news_items = [
        {
            "publisher_domain": r.get("publisher_domain"),
            "publisher": r.get("publisher_name") or r.get("publisher"),
            "forecast": "not_an_observation" in r["flags"],
            "in_cluster": True,
        }
        for r in reports
        if r.get("source_type") == "NEWS_MEDIA"
    ]
    news_items += await _district_warning_news(
        db, exclude_ids=[r["id"] for r in reports], family=family_of(event_type),
        district=district, start=window.start, end=window.end,
    )

    return {
        "now": now,
        "window": window,
        "weather": weather,
        "model": model,
        "station": station,
        "stations_seen": len(stations),
        "official": official,
        "contradiction": contradiction,
        "news": news_corroboration(news_items),
        "rainfall_mm": rainfall_mm,
        "weather_source": weather_source,
    }


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
                              -- A forecast linked as context (Phase 3 T8) is
                              -- not where the event is.
                              AND NOT 'not_an_observation' = ANY(COALESCE(flags, '{}'::text[]))
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


async def write_snapshot(
    db: AsyncSession,
    event_id: UUID,
    *,
    confidence: float,
    factor_coverage: Optional[float],
    report_count: Optional[int],
    verdict: Optional[str],
    review_status: str,
    severity: Optional[str],
    trigger: str,
    receipt_version: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    One `event_snapshots` row (Phase 4 T7), in the caller's transaction, so
    the snapshot commits with the score it records or not at all. `at` is the
    verification clock's now, so a replayed day's history reads as that day.
    """
    await db.execute(
        text("""
            INSERT INTO event_snapshots
                (id, event_id, at, confidence, factor_coverage, report_count, verdict,
                 review_status, severity, trigger, receipt_version, details)
            VALUES
                (CAST(:id AS uuid), CAST(:event_id AS uuid), :at, :confidence, :coverage,
                 :report_count, :verdict, :status, :severity, :trigger, :version,
                 CAST(:details AS jsonb))
        """),
        {
            "id": str(uuid4()),
            "event_id": str(event_id),
            "at": clock.now(),
            "confidence": confidence,
            "coverage": factor_coverage,
            "report_count": report_count,
            "verdict": verdict,
            "status": review_status,
            "severity": severity,
            "trigger": trigger[:160],
            "version": receipt_version,
            "details": json.dumps(details) if details is not None else None,
        },
    )


async def _next_event_code(db: AsyncSession) -> str:
    """
    Sequential, human-readable code: INDRA-YYYYMMDD-NNN.

    Derived from the count of events already created today. Two events created
    in the same millisecond could collide; event_code is UNIQUE so the insert
    would fail loudly rather than corrupt anything. Acceptable at
    single-process volume.
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
    (duplicate, uncorroborated, or a handled error). A handled error is also
    recorded for take_failure(), so the consumer can retry and dead-letter it.
    """
    _last_failure.set(None)
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

        # ── 1b. Posts and headlines: their own dedup, then clustered ────────
        # Phase 2 T7, T8. A post repeating an earlier post or headline is
        # suppressed exactly as a citizen duplicate is: duplicate_of, and never
        # counted again. Since Phase 3 T9 what is left clusters within its
        # hazard family like a citizen report (SOCIAL_CLUSTERING_ENABLED, on by
        # default), capped so posts alone never auto-publish; a headline that
        # was already old when collected is never clustered.
        if stored["source_type"] in FEED_SOURCE_TYPES:
            duplicate = await _feed_duplicate(db, stored)
            if duplicate is not None:
                await db.execute(
                    text("""
                        UPDATE raw_reports
                        SET duplicate_of = CAST(:original AS uuid),
                            source_meta = COALESCE(source_meta, '{}'::jsonb)
                                          || jsonb_build_object('duplicate_basis', CAST(:basis AS jsonb))
                        WHERE id = CAST(:id AS uuid)
                    """),
                    {
                        "original": str(duplicate["original"]),
                        "basis": json.dumps(duplicate["basis"]),
                        "id": str(report_id),
                    },
                )
                await _mark_processed(db, report_id)
                await db.commit()
                logger.info(
                    f"Pipeline: {stored['source_type']} {report_id} suppressed as a copy of "
                    f"{duplicate['original']} ({duplicate['basis']['rule']})"
                )
                return None

            stale = bool(stored["source_meta"].get("stale"))
            if stale or not get_settings().SOCIAL_CLUSTERING_ENABLED:
                logger.info(
                    f"Pipeline: {stored['source_type']} {report_id} stored and held "
                    f"({'stale' if stale else 'social clustering is off'})"
                )
                await _mark_processed(db, report_id)
                await db.commit()
                return None

        # ── 1a. No point, no spatial pipeline ───────────────────────────────
        # A post that names no place, or only a state, has nothing to measure a
        # distance from: it is stored and shown, never deduplicated on distance
        # and never clustered (Phase 2 T4, T6).
        # Coordinates, not geom_point: a row stored without a geometry gets one
        # backfilled at step 3, as it always has.
        if (
            stored["latitude"] is None
            or stored["longitude"] is None
            or stored["place_precision"] not in CLUSTERABLE_PRECISIONS
        ):
            logger.info(
                f"Pipeline: report {report_id} has no clusterable position "
                f"({stored['place_precision']}) — stored, not clustered"
            )
            await _mark_processed(db, report_id)
            await db.commit()
            return None

        # ── 2. Deduplication ────────────────────────────────────────────────
        # A suppressed report is marked, not just skipped: duplicate_of keeps it
        # out of every later clustering run, so it is never counted as
        # corroboration by the reports that arrive after it.
        # Posts reaching here (clustering on, Phase 3) already had their own.
        if stored["source_type"] in FEED_SOURCE_TYPES:
            original_ids, candidates = [], []
        else:
            original_ids, candidates = await _dedup_candidates(db, stored)
        # Inference is advisory. Persist its six typed component outcomes even
        # for a lone report or a duplicate that will not create an event.
        # The adapter owns PostGIS history reads and JSONB writes; ML owns none.
        await analyze_stored_report(
            db, stored, candidate_ids=original_ids, candidates=candidates
        )
        if candidates:
            # Off the event loop, via a worker thread.
            #
            # The frozen local matcher performs synchronous feature transforms;
            # keep them off the event loop, including the first artifact load.
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

        # ── 2b. The same message from many reporters (Phase 3 T8) ───────────
        # A copy close by is a duplicate (above); the same text from three or
        # more reporters anywhere within ten minutes is `coordinated`, and each
        # copy's credibility is halved before anything counts it.
        await _mark_coordinated(db, stored)

        # ── 3. Spatial preparation ──────────────────────────────────────────
        geo = GeoClusteringService(db)
        await geo.update_geom_points()
        await geo.assign_h3_cells()

        # ── 4. Clustering — find the cluster this report belongs to ─────────
        # Local, time-limited and within the report's hazard family (Phase 3
        # T5): the candidates are this report's neighbourhood, never the table.
        cluster = await geo.cluster_around(stored)
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
                db, stored["latitude"], stored["longitude"], stored["hazard_family"]
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
            cluster = {
                "cluster_id": -1,
                "report_ids": [report_id],
                "size": 1,
                "family": stored["hazard_family"],
                "basis": None,
            }

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
            db, stats["centroid_lat"], stats["centroid_lng"], cluster.get("family")
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
        reports = await _cluster_reports(db, scoring_ids)
        source_types = await _source_types(db, scoring_ids)
        report_texts = [r["raw_text"] for r in reports]

        # Forecasts and warnings ride along as context (T8): they are linked and
        # shown, but the event sits where the observations are, and only
        # observations count towards its geometry.
        observed_ids = [r["id"] for r in reports if "not_an_observation" not in r["flags"]]
        if observed_ids and len(observed_ids) < len(reports):
            stats = await geo.get_cluster_stats(observed_ids)

        # The type is a published count of what the reports say (T6), and the
        # density a count of independent witnesses, not of reports (T8, T9).
        typed = decide_event_type(reports)
        event_type = typed["event_type"]
        event_type_basis = typed["basis"]
        density = effective_reporters(reports)

        # Where the event is, in words. Named here rather than at step 7
        # because the official-warning factor (Phase 4 T4) and the district's
        # news (T6) are matched on the district.
        place = reverse_geocode(stats["centroid_lat"], stats["centroid_lng"])
        district = place.district if place else None
        footprint_ids = observed_ids or list(scoring_ids)

        # The evidence depends on the type (a heatwave reads temperature, fog
        # visibility), so it is gathered per type: a commander's override
        # below re-scores under the type they gave.
        evidence_by_type: Dict[Optional[str], Dict[str, Any]] = {}

        async def _score(etype: str, etype_basis: Dict[str, Any]) -> Dict[str, Any]:
            if etype not in evidence_by_type:
                evidence_by_type[etype] = await _gather_evidence(
                    db,
                    event_type=etype,
                    lat=stats["centroid_lat"],
                    lng=stats["centroid_lng"],
                    reports=reports,
                    report_ids=footprint_ids,
                    district=district,
                )
            return score_cluster(
                stats,
                source_types,
                report_texts=report_texts,
                event_type=etype,
                event_type_basis=etype_basis,
                density=density,
                eps_km=family_params(family_of(etype)).eps_km,
                cluster_basis=cluster.get("basis"),
                evidence=evidence_by_type[etype],
            )

        scored = await _score(event_type, event_type_basis)
        receipt = scored["receipt"]
        ml_event_grouping = await analyze_stored_event_group(db, scoring_ids)
        receipt["ml_event_grouping"] = ml_event_grouping
        confidence = scored["confidence"]
        severity = scored["severity"]
        quadrant = scored["quadrant"]
        review_status = scored["review_status"]
        caps = scored["caps"]
        verdict = scored["verdict"]

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

            # A commander's type stands (T6): the reports keep voting, and the
            # receipt shows both the vote and the override, but the event keeps
            # the type a human gave it. Re-scored under that type, since the
            # type decides the severity axis and the caps.
            override_type = (human_review or {}).get("event_type_override")
            if override_type and override_type != event_type:
                event_type_basis = {
                    **event_type_basis,
                    "override": {
                        "event_type": override_type,
                        "machine_vote": event_type,
                        "operator_id": human_review.get("operator_id"),
                    },
                }
                event_type = override_type
                scored = await _score(event_type, event_type_basis)
                receipt = scored["receipt"]
                receipt["ml_event_grouping"] = ml_event_grouping
                confidence = scored["confidence"]
                severity = scored["severity"]
                caps = scored["caps"]
                verdict = scored["verdict"]

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
                # Routing depends on severity too (BUG-067), so a commander's
                # override to HIGH keeps the event in front of a human; and the
                # caps (contradicted, unclassified, posts only) hold on a merge
                # as on a create.
                review_status = FusionEngine().determine_review_status(
                    confidence, severity=severity, caps=caps
                )
            receipt["routing"] = _routing(severity, confidence, review_status, caps)
            if human_review:
                receipt["human_review"] = human_review

        # Name the centroid (resolved at step 6). This goes in its own receipt
        # block rather than into `provenance`, which test_scoring_determinism
        # pins key-for-key because it is the record of which factors ran.
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
            "etype": event_type,
            "family": family_of(event_type),
            "verdict": verdict.value,
        }

        if existing is not None:
            await db.execute(
                text("""
                    UPDATE verified_events SET
                        -- Re-typed when a merge changes the majority (T6),
                        -- unless a commander set the type (applied above).
                        event_type = CAST(:etype AS event_type_enum),
                        hazard_family = :family,
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
                        verdict = CAST(:verdict AS verdict_enum),
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
                         hazard_family, verdict, updated_at)
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
                         :family, CAST(:verdict AS verdict_enum), NOW())
                """),
                {**common, "code": event_code},
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

        # The event's history (T7): every score write is a snapshot, so the
        # dashboard can draw confidence over time.
        await write_snapshot(
            db,
            event_id,
            confidence=confidence,
            factor_coverage=receipt.get("factor_coverage"),
            report_count=report_count,
            verdict=verdict.value,
            review_status=review_status.value,
            severity=severity.value,
            trigger="created" if existing is None else "merge",
            receipt_version=receipt.get("receipt_version"),
            details={"report_id": str(report_id), "linked": linked},
        )

        # The audit trail records decisions, not traffic: one row when an event
        # is created, one when a merge changes its status, none otherwise.
        if review_status.value != prior_status:
            await audit.record(
                db,
                event_id=event_id,
                operator_id=audit.SYSTEM_PIPELINE_OPERATOR,
                action=PIPELINE_AUDIT_ACTIONS[review_status],
                reason=(
                    f"{event_code} {action}: {event_type}, confidence {confidence} over "
                    f"{report_count} reports, {verdict.value} -> {review_status.value}"
                ),
                details={
                    "from_status": prior_status,
                    "to_status": review_status.value,
                    "confidence_score": confidence,
                    "report_count": report_count,
                    "severity": severity.value,
                    "event_type": event_type,
                    "verdict": verdict.value,
                    "caps": caps,
                },
            )

        await _mark_processed(db, report_id, *cluster["report_ids"])
        await db.commit()

        logger.info(
            f"Pipeline: {action} {event_code} ({event_id}) with {report_count} reports — "
            f"severity={severity.value} confidence={confidence} verdict={verdict.value} "
            f"status={review_status.value}"
        )

        return {
            "id": str(event_id),
            "event_code": event_code,
            "event_type": event_type,
            "severity": severity.value,
            "confidence_score": confidence,
            "review_status": review_status.value,
            "quadrant": quadrant.value,
            "verdict": verdict.value,
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
        _last_failure.set(f"{type(e).__name__}: {e}"[:1000])
        try:
            await db.rollback()
        except Exception:
            pass
        return None


# ── Late corroboration: re-score an event when evidence arrives (Phase 4 T5) ───

def _state_of(confidence: Any, verdict: Any, review_status: Any, severity: Any) -> Dict[str, Any]:
    return {
        "confidence_score": float(confidence) if confidence is not None else None,
        "verdict": str(getattr(verdict, "value", verdict)) if verdict is not None else None,
        "review_status": str(getattr(review_status, "value", review_status)),
        "severity": str(getattr(severity, "value", severity)) if severity is not None else None,
    }


async def rescore_event(
    db: AsyncSession,
    event_id: UUID,
    *,
    trigger: str,
    trigger_detail: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Re-score one existing event over its current reports and the evidence as it
    stands now, with the pure score_cluster(). IMD often issues or upgrades a
    warning after the first reports arrive: an event scored at 10:00 should
    rise when the warning lands at 10:20.

    * **Human decisions stand.** HUMAN_APPROVED keeps its status and a severity
      or type override keeps its value; confidence and verdict still update, and
      the ledger shows it. A REJECTED event is never touched.
    * **Only a change is written.** If confidence, verdict, status and severity
      all come out as stored, nothing is written and None is returned, so the
      same trigger processed twice changes nothing.
    * **A change writes three things, in one transaction:** the event, a
      snapshot (`late:<trigger>`) and a `LATE_CORROBORATION` ledger row with
      `{trigger, before, after}`. The caller broadcasts `VERIFIED_EVENT`.
    * `updated_at` is left alone: it keys the merge window (BUG-035), and new
      evidence about an event is not a new report of it.

    Returns the event, as process_report returns it, when it changed.
    """
    try:
        row = (await db.execute(
            text("""
                SELECT event_code, CAST(review_status AS text), verification_receipt,
                       CAST(event_type AS text), CAST(severity AS text), confidence_score,
                       CAST(verdict AS text), impact_radius_km
                FROM verified_events
                WHERE id = CAST(:id AS uuid)
                FOR UPDATE
            """),
            {"id": str(event_id)},
        )).fetchone()
        if row is None or row[1] == ReviewStatus.REJECTED.value:
            await db.rollback()
            return None
        event_code, prior_status, old_receipt, stored_type, stored_severity, stored_conf, \
            stored_verdict, impact_radius = row
        old_receipt = old_receipt or {}
        human_review = old_receipt.get("human_review") or None
        before = _state_of(stored_conf, stored_verdict, prior_status, stored_severity)

        report_ids = await _event_report_ids(db, event_id)
        reports = await _cluster_reports(db, report_ids)
        if not reports:
            await db.rollback()
            return None
        source_types = await _source_types(db, report_ids)
        report_texts = [r["raw_text"] for r in reports]
        observed_ids = [r["id"] for r in reports if "not_an_observation" not in r["flags"]]

        geo = GeoClusteringService(db)
        stats = await geo.get_cluster_stats(observed_ids or report_ids)
        if not stats["count"] or stats["centroid_lat"] is None:
            await db.rollback()
            return None

        typed = decide_event_type(reports)
        event_type, event_type_basis = typed["event_type"], typed["basis"]
        override_type = (human_review or {}).get("event_type_override")
        if override_type and override_type != event_type:
            event_type_basis = {
                **event_type_basis,
                "override": {
                    "event_type": override_type,
                    "machine_vote": event_type,
                    "operator_id": human_review.get("operator_id"),
                },
            }
            event_type = override_type
        density = effective_reporters(reports)
        place = reverse_geocode(stats["centroid_lat"], stats["centroid_lng"])

        evidence = await _gather_evidence(
            db,
            event_type=event_type,
            lat=stats["centroid_lat"],
            lng=stats["centroid_lng"],
            reports=reports,
            report_ids=observed_ids or report_ids,
            district=place.district if place else None,
        )
        scored = score_cluster(
            stats,
            source_types,
            report_texts=report_texts,
            event_type=event_type,
            event_type_basis=event_type_basis,
            density=density,
            eps_km=family_params(family_of(event_type)).eps_km,
            cluster_basis=(old_receipt.get("cluster") or {}).get("clustering"),
            evidence=evidence,
        )
        receipt = scored["receipt"]
        confidence = scored["confidence"]
        severity = scored["severity"]
        verdict = scored["verdict"]
        caps = scored["caps"]

        if human_review and human_review.get("severity_override"):
            severity = Severity(human_review["severity_override"])
            receipt["provenance"]["severity"] = "human_override"
        if prior_status == ReviewStatus.HUMAN_APPROVED.value:
            review_status = ReviewStatus.HUMAN_APPROVED
            quadrant = FusionEngine.human_approved_quadrant(severity)
        else:
            quadrant = FusionEngine().assign_quadrant(severity, confidence)
            review_status = FusionEngine().determine_review_status(
                confidence, severity=severity, caps=caps
            )
        receipt["routing"] = _routing(severity, confidence, review_status, caps)
        if human_review:
            receipt["human_review"] = human_review
        # Kept from the stored receipt: advisory ML output (layer 4, frozen) is
        # not recomputed here, and the place is the one the event was stored at.
        for key in ("ml_event_grouping", "location"):
            if key in old_receipt:
                receipt[key] = old_receipt[key]

        after = _state_of(confidence, verdict, review_status, severity)
        if after == before:
            await db.rollback()
            return None

        receipt["late_corroboration"] = {
            "trigger": trigger,
            "detail": trigger_detail or {},
            "at": clock.now().isoformat(),
            "before": before,
        }
        await db.execute(
            text("""
                UPDATE verified_events SET
                    event_type = CAST(:etype AS event_type_enum),
                    hazard_family = :family,
                    severity = CAST(:sev AS severity_enum),
                    confidence_score = :conf,
                    review_status = CAST(:status AS review_status_enum),
                    quadrant = CAST(:quad AS quadrant_enum),
                    verdict = CAST(:verdict AS verdict_enum),
                    verification_receipt = CAST(:receipt AS jsonb)
                WHERE id = CAST(:id AS uuid)
            """),
            {
                "id": str(event_id),
                "etype": event_type,
                "family": family_of(event_type),
                "sev": severity.value,
                "conf": confidence,
                "status": review_status.value,
                "quad": quadrant.value,
                "verdict": verdict.value,
                "receipt": json.dumps(receipt),
            },
        )
        report_count = len(report_ids)
        await write_snapshot(
            db,
            event_id,
            confidence=confidence,
            factor_coverage=receipt.get("factor_coverage"),
            report_count=report_count,
            verdict=verdict.value,
            review_status=review_status.value,
            severity=severity.value,
            trigger=f"late:{trigger}",
            receipt_version=receipt.get("receipt_version"),
            details=trigger_detail,
        )
        await audit.record(
            db,
            event_id=event_id,
            operator_id=audit.SYSTEM_PIPELINE_OPERATOR,
            action=AuditAction.LATE_CORROBORATION,
            reason=(
                f"{event_code} re-scored by {trigger}: confidence {before['confidence_score']} -> "
                f"{confidence}, {before['verdict']} -> {verdict.value}, "
                f"{before['review_status']} -> {review_status.value}"
            ),
            details={"trigger": trigger, "trigger_detail": trigger_detail or {},
                     "before": before, "after": after},
        )
        await db.commit()
        logger.info(
            f"Late corroboration: {event_code} re-scored by {trigger} — "
            f"{before['confidence_score']} -> {confidence}, verdict {verdict.value}, "
            f"status {review_status.value}"
        )
        return {
            "id": str(event_id),
            "event_code": event_code,
            "event_type": event_type,
            "severity": severity.value,
            "confidence_score": confidence,
            "review_status": review_status.value,
            "quadrant": quadrant.value,
            "verdict": verdict.value,
            "impact_radius_km": impact_radius,
            "lat": stats["centroid_lat"],
            "lng": stats["centroid_lng"],
            "report_count": report_count,
            "merged": False,
            "late_corroboration": {"trigger": trigger, "before": before},
            "verification_receipt": receipt,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Late corroboration of {event_id} by {trigger} failed: {e}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
