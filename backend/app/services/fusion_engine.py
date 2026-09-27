"""
INDRA Platform — FusionEngine
Computes the Verification Receipt as a weighted 7-factor confidence score
(receipt v2, Phase 4 T4), decides the event's verdict, and assigns quadrant and
review_status to verified events.
"""

import logging
from typing import Dict, Any, Iterable, List, Mapping, Optional, Sequence

from app.core.config import get_settings
from app.models.enums import EventType, Severity, ReviewStatus, Quadrant, SourceType, Verdict

logger = logging.getLogger("indra.services.fusion_engine")


# ── Factor weights: receipt v2 ─────────────────────────────────────────────────
#
# Phase 4 T4 adds the official warning (IMD and SDMA, via SACHET) and
# rebalances so the weights still sum to 1.00:
#
#   factor               v1     v2
#   weather_station      0.25   0.20
#   official_warning       —    0.10
#   report_density       0.20   0.20
#   spatial_coherence    0.20   0.15
#   vision_analysis      0.15   0.15   (offline: layer 4, permanently)
#   source_reliability   0.15   0.15
#   anomaly_detection    0.05   0.05   (offline: layer 4, permanently)
#
# With vision and anomaly offline, factor_coverage is still exactly 0.80, so
# nothing the dashboard or the Q&A says about coverage changes; with SACHET
# stale as well it is 0.70.
RECEIPT_VERSION = 2

FACTORS = {
    "weather_station": {"weight": 0.20, "label": "Weather Station Corroboration"},
    "official_warning": {"weight": 0.10, "label": "Official Warning (IMD/SDMA via SACHET)"},
    "report_density": {"weight": 0.20, "label": "Report Density Analysis"},
    "spatial_coherence": {"weight": 0.15, "label": "Spatial Coherence Score"},
    "vision_analysis": {"weight": 0.15, "label": "Computer Vision Analysis"},
    "source_reliability": {"weight": 0.15, "label": "Source Reliability Index"},
    "anomaly_detection": {"weight": 0.05, "label": "Anomaly Detection Signal"},
}


# ── Source reliability ─────────────────────────────────────────────────────────
# A fixed prior on how far a single report from each source can be trusted.
# These values are a judgement call, not a fitted model — which is exactly why
# they are written down here rather than drawn as placeholder noise.
#
#   OFFICIAL_DISPATCH  1.00  A field dispatch from NDRF/SDRF/district control is
#                            the ground truth the platform is trying to reach.
#   CWC_GAUGE          0.95  Central Water Commission river gauge: a calibrated
#                            instrument, but it measures river level, not
#                            street flooding, so it corroborates rather than
#                            proves an urban event.
#   AWS_SENSOR         0.90  IMD Automatic Weather Station: calibrated, but a
#                            station can be several km from the incident and
#                            sensors do drop out or stick.
#   CITIZEN_APP        0.60  First-hand and geotagged, but unverified: one
#                            person, possibly mistaken, possibly exaggerating.
#   TWITTER_IMD        0.50  Social posts: frequently second-hand, reshared
#                            from elsewhere, or geotagged to the poster rather
#                            than the incident.
#   SOCIAL_MEDIA       0.50  The same kind of evidence from the platform it
#                            actually came from (Mastodon, Phase 2), so the same
#                            prior as TWITTER_IMD, for the same reasons.
#   NEWS_MEDIA         0.55  Edited and attributed, which a post is not, but
#                            almost always second-hand: a reporter relaying what
#                            officials or residents said, often hours later.
#                            Above a post, below a first-hand geotagged report.
SOURCE_RELIABILITY: Dict[SourceType, float] = {
    SourceType.OFFICIAL_DISPATCH: 1.00,
    SourceType.CWC_GAUGE: 0.95,
    SourceType.AWS_SENSOR: 0.90,
    SourceType.CITIZEN_APP: 0.60,
    SourceType.NEWS_MEDIA: 0.55,
    SourceType.TWITTER_IMD: 0.50,
    SourceType.SOCIAL_MEDIA: 0.50,
}


def source_reliability_score(source_types: Iterable[Any]) -> Optional[float]:
    """
    The Source Reliability factor for a cluster: the *maximum* reliability
    among its reports' sources.

    Maximum rather than mean, because one official gauge reading corroborating
    five citizen reports should lift the event — averaging would let the
    citizen reports dilute the strongest evidence present.

    Accepts SourceType members or their string values. Returns None when no
    report carries a recognised source, which compute_receipt() scores as an
    offline factor rather than inventing a value.
    """
    scores = []
    for raw in source_types:
        try:
            scores.append(SOURCE_RELIABILITY[SourceType(raw)])
        except (ValueError, KeyError):
            logger.warning(f"Unknown source_type {raw!r} ignored for source reliability")
    return max(scores) if scores else None


# ── The verdict (Phase 4 T4) ───────────────────────────────────────────────────

CORROBORATION_THRESHOLD = 0.6


def decide_verdict(
    contradictions: Sequence[Mapping[str, Any]],
    official_score: Optional[float],
    weather_score: Optional[float],
) -> Dict[str, Any]:
    """
    {"verdict", "basis"}: what the independent evidence says about the event.

    * **CONTRADICTED** if any contradiction is recorded. It wins over
      everything, including an official warning: a thermometer reading 26 °C
      is a fact about this place that a district-wide warning does not undo.
      It never means rejected; a human decides.
    * **CORROBORATED** if there is no contradiction and either the official
      warning or the weather/station evidence scores at least 0.6.
    * **UNCONFIRMED** otherwise: nothing independent either way.
    """
    if contradictions:
        verdict = Verdict.CONTRADICTED
        why = "a contradiction is recorded: " + "; ".join(
            str(c.get("reason", "")) for c in contradictions
        )
    elif (official_score or 0.0) >= CORROBORATION_THRESHOLD:
        verdict = Verdict.CORROBORATED
        why = f"official warning {official_score:.2f} ≥ {CORROBORATION_THRESHOLD}"
    elif (weather_score or 0.0) >= CORROBORATION_THRESHOLD:
        verdict = Verdict.CORROBORATED
        why = f"weather evidence {weather_score:.2f} ≥ {CORROBORATION_THRESHOLD}"
    else:
        verdict = Verdict.UNCONFIRMED
        why = "no contradiction, and neither the official warning nor the weather reaches 0.6"
    return {
        "verdict": verdict,
        "basis": {
            "rule": (
                "CONTRADICTED if any contradiction; else CORROBORATED if official_warning "
                "or weather ≥ 0.6; else UNCONFIRMED"
            ),
            "reason": why,
            "official_warning": official_score,
            "weather": weather_score,
            "contradictions": len(contradictions),
        },
    }


# ── Review caps (Phase 3 T6, T9; Phase 4 T4) ───────────────────────────────────
# Why an event may not be auto-published, whatever its confidence. Each holds
# it at PENDING_HUMAN_REVIEW at most, so a human sees it:
#
#   contradicted   the evidence says the opposite (T3): ten coordinated reports
#                  cannot auto-publish against a thermometer
#   unclassified   nothing says what hazard it is
#   posts_only     every report is a post or a headline: posts corroborate, they
#                  do not verify on their own

FEED_SOURCE_TYPES = frozenset({"SOCIAL_MEDIA", "NEWS_MEDIA"})


def review_caps(
    event_type: Optional[str],
    source_types: Sequence[Any],
    verdict: Optional[Any] = None,
) -> List[str]:
    caps = []
    if verdict is not None and str(getattr(verdict, "value", verdict)) == Verdict.CONTRADICTED.value:
        caps.append("contradicted")
    if event_type == EventType.UNCLASSIFIED.value:
        caps.append("unclassified")
    sources = {str(getattr(t, "value", t)) for t in source_types}
    if sources and sources <= FEED_SOURCE_TYPES:
        caps.append("posts_only")
    return caps


def _is_high(severity: Any) -> bool:
    """True for HIGH or CRITICAL, given a Severity or its value; False for anything else."""
    try:
        return Severity(severity) in (Severity.HIGH, Severity.CRITICAL)
    except ValueError:
        return False


class FusionEngine:
    """
    Computes the multi-factor verification receipt and assigns quadrant + status.
    """

    def compute_receipt(
        self,
        weather_score: Optional[float] = None,
        report_density_score: Optional[float] = None,
        spatial_score: Optional[float] = None,
        vision_score: Optional[float] = None,
        reliability_score: Optional[float] = None,
        anomaly_score: Optional[float] = None,
        official_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compute the verification receipt.

        Confidence is the weighted mean over the factors that actually
        reported:

            confidence = Σ_online (w · s) / Σ_online w

        A factor that never reported is not evidence against the event. No
        image classifier and no anomaly model ship this sprint, and charging
        every event their combined 0.20 capped a fully corroborated flood at
        0.80 — the platform was quarantining real events on behalf of models it
        had chosen not to build. So an offline factor is excluded from the mean,
        and the receipt publishes `factor_coverage`: the share of the model's
        designed weight that reported. A 0.59 over 0.80 coverage must never be
        mistaken for a 0.59 over full coverage, so the number the receipt
        claims and the evidence behind it stay separable.

        An explicit 0.0 is a measurement, not a gap: zero rainfall is a real
        reading and costs the weather factor its full weight (0.20 in v2).
        Only None is offline.

        `weight_pct` stays nominal (20.0, 10.0, …) — it is the *design* weight,
        identical on every receipt, so the offline rows keep showing what the
        model wanted and did not get. Re-normalising it per factor would print
        "weather 31.25%" on one receipt and "25%" on another, leaving a reader
        unable to tell whether the model changed or the telemetry did. The
        self-explaining arithmetic lives instead in one visible division that a
        person can check with a calculator:

            total_weighted / factor_coverage = confidence_score

        For that to be literally true of the *printed* numbers, each row's
        weighted_points is rounded before being summed, so the points column
        adds up to total_weighted exactly. A receipt whose line items do not add
        to its total is a bug in a receipt.

        Returns {"receipt_version", "confidence_score", "factor_coverage",
                 "factors", "total_weighted"}. Each factor row also carries
        its `key` (weather_station, official_warning, …), which the pipeline
        uses to attach the evidence behind it.
        """
        scores = {
            "weather_station": weather_score,
            "official_warning": official_score,
            "report_density": report_density_score,
            "spatial_coherence": spatial_score,
            "vision_analysis": vision_score,
            "source_reliability": reliability_score,
            "anomaly_detection": anomaly_score,
        }

        factors: List[Dict[str, Any]] = []
        total_weighted = 0.0
        coverage = 0.0

        for key, meta in FACTORS.items():
            raw_score = scores.get(key)
            online = raw_score is not None

            if online:
                raw_score = max(0.0, min(1.0, float(raw_score)))
                evidence = f"{meta['label']} data integrated"
                coverage += meta["weight"]
            else:
                raw_score = 0.0
                evidence = "Telemetry factor offline"

            # Rounded per row, then summed, so the points column in the stored
            # receipt adds up to total_weighted exactly.
            weighted_points = round(raw_score * meta["weight"], 4)
            total_weighted += weighted_points

            factors.append({
                "key": key,
                "factor": meta["label"],
                "weight_pct": meta["weight"] * 100,
                # "computed" | "offline" — the same vocabulary the pipeline's
                # provenance block uses. This is what distinguishes a score of
                # 0.0 that was measured from one that was never reported;
                # `score` stays 0.0 rather than null so the receipt renderers
                # (which multiply it) cannot throw.
                "state": "computed" if online else "offline",
                "score": round(raw_score, 4),
                "weighted_points": weighted_points,
                "evidence": evidence,
            })

        total_weighted = round(total_weighted, 4)
        factor_coverage = round(coverage, 4)

        # Σ_online w == 0: nothing reported, so there is nothing to be confident
        # about and nothing to divide by. Unreachable from the pipeline (report
        # density and spatial coherence are always computed from the cluster's
        # own geometry); guarded for every other caller.
        if factor_coverage > 0.0:
            confidence = round(total_weighted / factor_coverage, 4)
        else:
            confidence = 0.0
        # A mean of values in [0, 1] cannot leave [0, 1]; this clamp is what
        # keeps verified_events.ck_confidence_range true even if rounding or a
        # future factor misbehaves.
        confidence = max(0.0, min(1.0, confidence))

        return {
            "receipt_version": RECEIPT_VERSION,
            "confidence_score": confidence,
            "factor_coverage": factor_coverage,
            "factors": factors,
            "total_weighted": total_weighted,
        }

    def assign_quadrant(
        self,
        severity: Severity,
        confidence: float,
        auto_threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
    ) -> Quadrant:
        """
        Quadrant assignment based on severity and confidence.

        - severity ∈ {HIGH, CRITICAL} & C ≥ auto_threshold → "Critical Verified Event"
        - severity ∈ {HIGH, CRITICAL} & C < auto_threshold → "Unverified Threat"
        - severity ∈ {ADVISORY, MODERATE} & C ≥ review_threshold → "Confirmed Minor Event"
        - else → "Noise"
        - Default (can't determine) → "Unverified Threat" (fail-safe)

        The two thresholds default to the same settings determine_review_status()
        uses, and that shared default is the point. They used to be hard-coded
        0.90 / 0.70 here while the review gate was configurable, so lowering
        HUMAN_REVIEW_THRESHOLD to 0.60 on 20 Sep would have put an event at 0.62
        into PENDING_HUMAN_REVIEW while this method still called it "Noise" — the
        Intelligence Matrix labelling the very event it was asking an operator to
        review as noise. One gate, one number, read from one place.
        """
        try:
            settings = get_settings()
            if auto_threshold is None:
                auto_threshold = settings.AUTO_PUBLISH_THRESHOLD
            if review_threshold is None:
                review_threshold = settings.HUMAN_REVIEW_THRESHOLD

            high_severities = {Severity.HIGH, Severity.CRITICAL}
            low_severities = {Severity.ADVISORY, Severity.MODERATE}

            if severity in high_severities:
                if confidence >= auto_threshold:
                    return Quadrant.CRITICAL_VERIFIED
                else:
                    return Quadrant.UNVERIFIED_THREAT

            if severity in low_severities:
                if confidence >= review_threshold:
                    return Quadrant.CONFIRMED_MINOR
                else:
                    return Quadrant.NOISE

            # Fail-safe: default to Unverified Threat
            return Quadrant.UNVERIFIED_THREAT

        except Exception:
            return Quadrant.UNVERIFIED_THREAT

    @staticmethod
    def human_approved_quadrant(severity: Severity) -> Quadrant:
        """
        Quadrant for an event a commander has approved.

        assign_quadrant() is score-based, so a human-approved 0.43 event would
        still read "Noise" — contradicting the approval. Once a human has
        verified the event, only its severity decides the quadrant.
        """
        if severity in {Severity.HIGH, Severity.CRITICAL}:
            return Quadrant.CRITICAL_VERIFIED
        return Quadrant.CONFIRMED_MINOR

    def determine_review_status(
        self,
        confidence: float,
        auto_threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
        severity: Optional[Any] = None,
        caps: Sequence[str] = (),
    ) -> ReviewStatus:
        """
        Route event to the appropriate review status.

        - C ≥ auto_threshold → AUTO_PUBLISHED, unless a cap applies
        - C ≥ review_threshold → PENDING_HUMAN_REVIEW
        - severity HIGH or CRITICAL → PENDING_HUMAN_REVIEW, however low C is
        - else → QUARANTINED

        **Every cap lives here** (Phase 4 T4): `caps` is review_caps()'s list
        (contradicted, unclassified, posts_only), and any one of them holds an
        event that cleared the auto-publish gate at PENDING_HUMAN_REVIEW. The
        0.90 and 0.60 gates themselves are unchanged. A cap never pushes an
        event down: a quarantined event stays quarantined, and the review
        queue's `contradicted` tab (T7) is where a human finds it.

        **A High or Critical claim is never quarantined** (BUG-067, 24 Sep). It
        still needs 0.90 to publish on its own, but below the review gate it goes
        to a human rather than out of sight: one uncorroborated report of a dam
        breach is exactly the event an operator must see. The same asymmetry
        lowered the review gate on 20 Sep (BUG-018): a quarantined real disaster
        is invisible, while an escalated weak signal costs an operator ten
        seconds. ADVISORY and MODERATE events are routed on confidence alone.

        Both thresholds default to settings, exactly as assign_quadrant's do, so
        the two methods can never disagree about where a gate is. They used to
        carry hard-coded 0.90 / 0.70 literals, which meant a caller that omitted
        them silently applied a different policy from the pipeline.
        """
        settings = get_settings()
        if auto_threshold is None:
            auto_threshold = settings.AUTO_PUBLISH_THRESHOLD
        if review_threshold is None:
            review_threshold = settings.HUMAN_REVIEW_THRESHOLD

        if confidence >= auto_threshold:
            if caps:
                return ReviewStatus.PENDING_HUMAN_REVIEW
            return ReviewStatus.AUTO_PUBLISHED
        elif confidence >= review_threshold:
            return ReviewStatus.PENDING_HUMAN_REVIEW
        elif _is_high(severity):
            return ReviewStatus.PENDING_HUMAN_REVIEW
        else:
            return ReviewStatus.QUARANTINED
