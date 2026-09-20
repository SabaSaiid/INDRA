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

from app.models.enums import Quadrant, ReviewStatus, Severity, SourceType
from app.services.fusion_engine import (
    FACTORS,
    SOURCE_RELIABILITY,
    source_reliability_score,
)

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
    """
    Nothing reported, so there is no mean to take: 0/0 is 0.0, never a crash.

    This is the division-by-zero guard. Confidence is Σ_online(w·s) / Σ_online w,
    so a receipt with no online factor has an empty denominator — it must answer
    0.0 with 0.0 coverage rather than raising.
    """
    receipt = fusion.compute_receipt(**_all(None))
    assert receipt["confidence_score"] == 0.0
    assert receipt["factor_coverage"] == 0.0
    assert len(receipt["factors"]) == 6
    for factor in receipt["factors"]:
        assert factor["evidence"] == "Telemetry factor offline"
        assert factor["state"] == "offline"
        assert factor["score"] == 0.0


def test_known_vector_scores_exactly_070(fusion):
    """
    0.9*.25 + 0.8*.20 + 0.85*.20 + 0.0*.15 + 0.8*.15 + 0.5*.05 = 0.70

    Also the anchor for the rule that **an explicit 0.0 is online**: vision is
    passed 0.0, not None, so it is a measurement of "no signal" and still costs
    its full 0.15. Coverage is therefore 1.0 and the arithmetic is unchanged by
    re-normalisation. If this test ever starts needing a divisor, someone has
    confused "scored zero" with "did not report".
    """
    receipt = fusion.compute_receipt(
        weather_score=0.9,
        report_density_score=0.8,
        spatial_score=0.85,
        vision_score=0.0,
        reliability_score=0.8,
        anomaly_score=0.5,
    )
    assert receipt["confidence_score"] == pytest.approx(0.70)
    assert receipt["factor_coverage"] == 1.0


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


def test_weight_pct_stays_nominal_when_a_factor_is_offline(fusion):
    """
    `weight_pct` is the *design* weight and never re-normalised.

    This is the guard against a future refactor "helpfully" rescaling the column.
    If vision's row ever reads 0.0% — or weather's reads 31.25% — the receipt has
    stopped saying "we designed a flood-image classifier at 15% weight and do not
    have one", which is the single most important claim it makes. Re-normalised
    weights would also mean the same factor printed a different percentage on
    different receipts, leaving a reader unable to tell whether the model changed
    or the telemetry did.
    """
    kwargs = _all(1.0)
    kwargs["vision_score"] = None
    receipt = fusion.compute_receipt(**kwargs)

    by_label = {f["factor"]: f for f in receipt["factors"]}
    vision = by_label[FACTORS["vision_analysis"]["label"]]
    weather = by_label[FACTORS["weather_station"]["label"]]

    assert vision["weight_pct"] == 15.0
    assert vision["state"] == "offline"
    assert weather["weight_pct"] == 25.0
    assert sum(f["weight_pct"] for f in receipt["factors"]) == pytest.approx(100.0)


def test_the_points_column_adds_up_to_the_published_total(fusion):
    """
    A receipt whose line items do not add to its total is a bug in a receipt.

    `weighted_points` is rounded per row and then summed, so a nodal officer can
    add the printed column, divide by the printed `factor_coverage`, and land on
    the printed `confidence_score` exactly. That one visible division is how the
    receipt explains re-normalisation without re-scaling the weight column.
    """
    receipt = fusion.compute_receipt(
        weather_score=0.35,
        report_density_score=0.5483,
        spatial_score=0.9135,
        reliability_score=0.60,
    )
    column = sum(f["weighted_points"] for f in receipt["factors"])
    assert round(column, 4) == receipt["total_weighted"]
    assert (
        round(receipt["total_weighted"] / receipt["factor_coverage"], 4)
        == receipt["confidence_score"]
    )


def test_receipt_shape_is_stable(fusion):
    """The frontend and the stored JSONB both depend on this shape."""
    receipt = fusion.compute_receipt(**_all(0.5))
    assert set(receipt) == {
        "confidence_score",
        "factor_coverage",
        "factors",
        "total_weighted",
    }
    assert len(receipt["factors"]) == 6
    for factor in receipt["factors"]:
        assert set(factor) == {
            "factor",
            "weight_pct",
            "state",
            "score",
            "weighted_points",
            "evidence",
        }


def test_a_single_offline_factor_costs_nothing_but_lowers_coverage(fusion):
    """
    A model we did not build is not evidence against the flood.

    This test asserts the **opposite** of what it asserted before 20 Sep, and the
    reversal is deliberate. Previously vision being offline cost the event its
    full 0.15, so six perfect signals scored 0.85 and two permanently offline
    factors held 20% of the scale hostage — the platform quarantining real events
    on behalf of models it had chosen never to build.

    Now an offline factor leaves the mean alone and is charged to
    `factor_coverage` instead: this event is a 1.0, measured over 85% of the
    designed model, and the receipt says both numbers out loud.
    """
    kwargs = _all(1.0)
    kwargs["vision_score"] = None
    receipt = fusion.compute_receipt(**kwargs)

    assert receipt["confidence_score"] == 1.0
    expected_coverage = 1.0 - FACTORS["vision_analysis"]["weight"]
    assert receipt["factor_coverage"] == pytest.approx(expected_coverage)
    assert receipt["total_weighted"] == pytest.approx(expected_coverage)


@pytest.mark.parametrize(
    "online,expected_coverage",
    [
        (("weather_score",), 0.25),
        (("weather_score", "report_density_score"), 0.45),
        (("vision_score", "anomaly_score"), 0.20),
        (
            (
                "weather_score",
                "report_density_score",
                "spatial_score",
                "reliability_score",
            ),
            0.80,
        ),
        (ALL_FACTOR_KWARGS, 1.0),
    ],
)
def test_coverage_is_the_sum_of_reporting_weights(fusion, online, expected_coverage):
    """`factor_coverage` is exactly Σ w over the factors that reported."""
    kwargs = _all(None)
    for name in online:
        kwargs[name] = 1.0
    receipt = fusion.compute_receipt(**kwargs)
    assert receipt["factor_coverage"] == pytest.approx(expected_coverage)
    assert receipt["confidence_score"] == 1.0


def test_confidence_stays_in_range_at_every_coverage(fusion):
    """
    All 63 non-empty online subsets keep confidence inside [0, 1].

    verified_events carries CHECK (confidence_score BETWEEN 0 AND 1); an INSERT
    that violates it is swallowed by process_report's blanket `except` and
    silently becomes "no event" — a lost disaster report with no error anywhere.
    This walks every combination of reporting factors at both extremes so that
    cannot happen.

    Deliberately one test with an internal loop rather than 126 parametrised
    cases: it is a single property, and inflating the suite count with it would
    misrepresent how much was actually covered today.
    """
    for subset_bits in range(1, 64):
        for value in (0.0, 1.0):
            kwargs = _all(None)
            for i, name in enumerate(ALL_FACTOR_KWARGS):
                if subset_bits & (1 << i):
                    kwargs[name] = value
            receipt = fusion.compute_receipt(**kwargs)
            online = [f for f in receipt["factors"] if f["state"] == "computed"]

            assert 0.0 <= receipt["confidence_score"] <= 1.0, (subset_bits, value)
            assert 0.0 < receipt["factor_coverage"] <= 1.0, (subset_bits, value)
            assert len(online) == bin(subset_bits).count("1"), (subset_bits, value)
            # A uniform set of scores must average to exactly that score,
            # whatever the coverage.
            assert receipt["confidence_score"] == pytest.approx(value), (
                subset_bits,
                value,
            )


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


# ── source_reliability_score() — Day 2 T5 ──────────────────────────────────────

@pytest.mark.parametrize(
    "sources, expected",
    [
        (["CITIZEN_APP"] * 4, 0.60),
        (["TWITTER_IMD"] * 3, 0.50),
        (["CITIZEN_APP"] * 5 + ["CWC_GAUGE"], 0.95),
        (["CITIZEN_APP"] * 5 + ["OFFICIAL_DISPATCH"], 1.0),
        (["AWS_SENSOR"], 0.90),
    ],
)
def test_source_reliability_table(sources, expected):
    assert source_reliability_score(sources) == pytest.approx(expected)


def test_source_reliability_accepts_enum_members():
    assert source_reliability_score([SourceType.CWC_GAUGE]) == pytest.approx(0.95)


def test_source_reliability_with_no_known_source_is_offline_not_invented():
    assert source_reliability_score([]) is None
    assert source_reliability_score(["NOT_A_SOURCE"]) is None


def test_every_source_type_has_a_documented_reliability():
    assert set(SOURCE_RELIABILITY) == set(SourceType)


def test_vision_offline_does_not_move_a_uniform_score(fusion):
    """
    Taking a factor offline does not move the mean when it agreed with the rest.

    Replaces Day 2 T7's `test_vision_offline_costs_exactly_its_weight`, which
    asserted a 0.15 drop. Under coverage-aware scoring the mean of five 0.5s is
    the same as the mean of six 0.5s, so the delta is exactly **zero** — and
    stating it as an invariance says the new semantics far more sharply than any
    non-zero delta could.

    The base is deliberately uniform (all 0.5, vision included) so the expected
    delta is exact rather than an artefact of which factor happened to be
    strongest. What is *not* zero is the coverage: that is where the missing
    classifier is now accounted for.
    """
    base = _all(0.5)
    offline = dict(base, vision_score=None)

    base_receipt = fusion.compute_receipt(**base)
    offline_receipt = fusion.compute_receipt(**offline)

    assert base_receipt["confidence_score"] == pytest.approx(0.5)
    assert offline_receipt["confidence_score"] == pytest.approx(0.5)
    assert (
        offline_receipt["confidence_score"] - base_receipt["confidence_score"]
    ) == pytest.approx(0.0)

    # The cost moved from the score to the coverage, where it belongs.
    assert base_receipt["factor_coverage"] == 1.0
    assert offline_receipt["factor_coverage"] == pytest.approx(0.85)

    factor = next(
        f for f in offline_receipt["factors"]
        if f["factor"] == "Computer Vision Analysis"
    )
    assert factor["state"] == "offline"
    assert factor["score"] == 0.0
    assert factor["weighted_points"] == 0.0
    assert factor["evidence"] == "Telemetry factor offline"


def test_fusion_engine_no_longer_offers_placeholder_scores(fusion):
    assert not hasattr(fusion, "generate_heuristic_scores")
