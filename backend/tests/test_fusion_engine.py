"""
T7 — Unit tests for FusionEngine.

Pure math, no database. This is the scoring claim the whole pitch rests on:
if a judge asks "how do you know the confidence score is right?", this file is
the answer.

Weights (from fusion_engine.FACTORS):
    weather_station    0.25
    report_density     0.20
    spatial_coherence  0.20
    vision_analysis    0.15
    source_reliability 0.15
    anomaly_detection  0.05
"""

import pytest

from app.models.enums import Quadrant, ReviewStatus, Severity
from app.services.fusion_engine import FACTORS

ALL_FACTOR_KWARGS = (
    "weather_score",
    "report_density_score",
    "spatial_score",
    "vision_score",
    "reliability_score",
    "anomaly_score",
)


def _all(value):
    """Build a compute_receipt kwargs dict with every factor set to `value`."""
    return {name: value for name in ALL_FACTOR_KWARGS}


# ── compute_receipt() ──────────────────────────────────────────────────────────

def test_all_factors_perfect_scores_one(fusion):
    receipt = fusion.compute_receipt(**_all(1.0))
    assert receipt["confidence_score"] == 1.0


def test_all_factors_offline_scores_zero(fusion):
    receipt = fusion.compute_receipt(**_all(None))
    assert receipt["confidence_score"] == 0.0
    assert len(receipt["factors"]) == 6
    for factor in receipt["factors"]:
        assert factor["evidence"] == "Telemetry factor offline"
        assert factor["score"] == 0.0


def test_known_vector_scores_exactly_070(fusion):
    """0.9*.25 + 0.8*.20 + 0.85*.20 + 0.0*.15 + 0.8*.15 + 0.5*.05 = 0.70"""
    receipt = fusion.compute_receipt(
        weather_score=0.9,
        report_density_score=0.8,
        spatial_score=0.85,
        vision_score=0.0,
        reliability_score=0.8,
        anomaly_score=0.5,
    )
    assert receipt["confidence_score"] == pytest.approx(0.70)


def test_scores_above_one_are_clamped(fusion):
    receipt = fusion.compute_receipt(**_all(1.5))
    assert receipt["confidence_score"] == 1.0
    assert all(f["score"] == 1.0 for f in receipt["factors"])


def test_scores_below_zero_are_clamped(fusion):
    receipt = fusion.compute_receipt(**_all(-0.5))
    assert receipt["confidence_score"] == 0.0
    assert all(f["score"] == 0.0 for f in receipt["factors"])


def test_weights_sum_to_one_hundred_percent(fusion):
    receipt = fusion.compute_receipt(**_all(0.5))
    assert sum(f["weight_pct"] for f in receipt["factors"]) == pytest.approx(100.0)


def test_receipt_shape_is_stable(fusion):
    """The frontend and the stored JSONB both depend on this shape."""
    receipt = fusion.compute_receipt(**_all(0.5))
    assert set(receipt) == {"confidence_score", "factors", "total_weighted"}
    assert len(receipt["factors"]) == 6
    for factor in receipt["factors"]:
        assert set(factor) == {
            "factor",
            "weight_pct",
            "score",
            "weighted_points",
            "evidence",
        }


def test_a_single_offline_factor_costs_exactly_its_weight(fusion):
    """Everything perfect except vision (0.15) → 0.85, not a silent zero."""
    kwargs = _all(1.0)
    kwargs["vision_score"] = None
    receipt = fusion.compute_receipt(**kwargs)
    assert receipt["confidence_score"] == pytest.approx(1.0 - FACTORS["vision_analysis"]["weight"])


# ── assign_quadrant() ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "severity,confidence,expected",
    [
        (Severity.CRITICAL, 0.95, Quadrant.CRITICAL_VERIFIED),
        (Severity.CRITICAL, 0.90, Quadrant.CRITICAL_VERIFIED),      # boundary, inclusive
        (Severity.CRITICAL, 0.8999, Quadrant.UNVERIFIED_THREAT),    # just below
        (Severity.HIGH, 0.50, Quadrant.UNVERIFIED_THREAT),
        (Severity.MODERATE, 0.70, Quadrant.CONFIRMED_MINOR),        # boundary, inclusive
        (Severity.MODERATE, 0.6999, Quadrant.NOISE),                # just below
        (Severity.ADVISORY, 0.95, Quadrant.CONFIRMED_MINOR),
        (Severity.ADVISORY, 0.10, Quadrant.NOISE),
    ],
)
def test_assign_quadrant(fusion, severity, confidence, expected):
    assert fusion.assign_quadrant(severity, confidence) is expected


def test_unknown_severity_fails_safe_to_unverified_threat(fusion):
    """An unrecognised severity must never silently become Noise and get dropped."""
    assert fusion.assign_quadrant("NOT_A_SEVERITY", 0.99) is Quadrant.UNVERIFIED_THREAT


# ── determine_review_status() ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "confidence,expected",
    [
        (1.0, ReviewStatus.AUTO_PUBLISHED),
        (0.90, ReviewStatus.AUTO_PUBLISHED),            # boundary, inclusive
        (0.8999, ReviewStatus.PENDING_HUMAN_REVIEW),    # just below
        (0.70, ReviewStatus.PENDING_HUMAN_REVIEW),      # boundary, inclusive
        (0.6999, ReviewStatus.QUARANTINED),             # just below
        (0.0, ReviewStatus.QUARANTINED),
    ],
)
def test_determine_review_status(fusion, confidence, expected):
    assert fusion.determine_review_status(confidence) is expected


def test_review_thresholds_are_overridable(fusion):
    """The pipeline passes settings.AUTO_PUBLISH_THRESHOLD / HUMAN_REVIEW_THRESHOLD."""
    assert (
        fusion.determine_review_status(0.85, auto_threshold=0.80, review_threshold=0.60)
        is ReviewStatus.AUTO_PUBLISHED
    )


# ── The one that matters most ──────────────────────────────────────────────────

def test_high_severity_at_085_goes_to_a_human_not_to_publish_or_bin(fusion):
    """
    The 'single dam-break report' story: a HIGH-severity event at 0.85 confidence
    must be routed to a human — never auto-published, never dropped as noise.
    """
    severity, confidence = Severity.HIGH, 0.85

    assert fusion.assign_quadrant(severity, confidence) is Quadrant.UNVERIFIED_THREAT
    assert fusion.determine_review_status(confidence) is ReviewStatus.PENDING_HUMAN_REVIEW


# ── generate_heuristic_scores() — the Day 2 replacement target ─────────────────

def test_heuristic_scores_cover_every_factor_and_stay_in_range(fusion):
    scores = fusion.generate_heuristic_scores()
    assert set(scores) == set(ALL_FACTOR_KWARGS)
    assert all(0.0 <= v <= 1.0 for v in scores.values())
