"""
T8 — Unit tests for DedupService.

Pure logic, no database. All cases use Patna (25.5941, 85.1376) at
t0 = 2026-09-16T10:00:00Z as the base point.

The three gates are AND-ed: text similarity AND ≤ 1.0 km AND ≤ 15 min.
Text similarity has two paths with different thresholds — cosine ≥ 0.88 when
sentence-transformers loaded, Levenshtein ≥ 0.75 on the fallback — so the one
case that straddles them is gated on which path is live rather than hardcoded.
"""

from datetime import timedelta

import pytest

from app.services.dedup import _haversine_km
from tests.conftest import PATNA_LAT, PATNA_LNG, T0, requires_embeddings

BASE_TEXT = "Flood at Kankarbagh, water knee deep"


def existing(text=BASE_TEXT, lat=PATNA_LAT, lng=PATNA_LNG, minutes=0):
    """One entry in the (text, lat, lng, created_at) tuple list is_duplicate takes."""
    return (text, lat, lng, T0 + timedelta(minutes=minutes))


def check(dedup, existing_reports, text=BASE_TEXT):
    """Run is_duplicate for a new report at the base point and time t0."""
    return dedup.is_duplicate(text, PATNA_LAT, PATNA_LNG, T0, existing_reports)


# ── is_duplicate() ─────────────────────────────────────────────────────────────

def test_empty_list_is_never_a_duplicate(dedup):
    assert check(dedup, []) is False


def test_exact_duplicate_within_both_gates(dedup):
    """Same text, ~0.56 km away, 5 minutes later."""
    assert check(dedup, [existing(lat=PATNA_LAT + 0.005, minutes=5)]) is True


def test_gps_gate_rejects_just_over_one_km(dedup):
    """+0.010 deg lat ≈ 1.11 km — outside the 1.0 km gate."""
    assert check(dedup, [existing(lat=PATNA_LAT + 0.010, minutes=1)]) is False


def test_gps_gate_accepts_just_inside_one_km(dedup):
    """+0.008 deg lat ≈ 0.89 km — inside the 1.0 km gate."""
    assert check(dedup, [existing(lat=PATNA_LAT + 0.008, minutes=1)]) is True


def test_time_gate_rejects_just_over_fifteen_minutes(dedup):
    assert check(dedup, [existing(minutes=16)]) is False


def test_time_gate_accepts_just_inside_fifteen_minutes(dedup):
    assert check(dedup, [existing(minutes=14)]) is True


def test_time_gate_is_symmetric_backwards(dedup):
    """The code uses abs() on the delta — an older report 16 min back is also out."""
    assert check(dedup, [existing(minutes=-16)]) is False
    assert check(dedup, [existing(minutes=-14)]) is True


def test_unrelated_text_at_the_same_point_is_not_a_duplicate(dedup):
    """Both spatial gates pass; only the text check should reject this."""
    other = "Traffic signal broken at Danapur crossing"
    assert check(dedup, [existing(text=other, minutes=1)]) is False


@requires_embeddings
def test_paraphrase_is_NOT_caught_at_the_current_088_threshold(dedup):
    """
    Two sentences describing the same flood, 0.1 km and 2 min apart.

    Measured 16 Sep: cosine = 0.8151, which is below COSINE_THRESHOLD = 0.88,
    so this paraphrase is NOT deduplicated. The day plan assumed it would be.

    22 Sep: and it should not be. A duplicate is suppressed and never counts
    as corroboration, so a paraphrase from a second citizen is a second
    witness, not noise. BUG-013 is closed on that basis; the measurement that
    settles it is in test_dedup_corroboration.py.
    """
    result = dedup.is_duplicate(
        "Water rising near Kankarbagh road",
        PATNA_LAT,
        PATNA_LNG,
        T0,
        [existing(text="Kankarbagh road is flooding fast", lat=PATNA_LAT + 0.0009, minutes=2)],
    )
    assert result is False


@requires_embeddings
def test_embeddings_separate_paraphrase_from_unrelated(dedup):
    """
    The evidence for a Day 2 threshold change: the model separates these cases
    cleanly, the threshold just sits in the wrong place.

    Measured 16 Sep:
        identical text           cosine 1.000
        same-event paraphrase    cosine 0.815   ← currently missed at 0.88
        two distinct reports     cosine 0.519
        unrelated civic issue    cosine 0.136

    16 Sep this read as the case for lowering the threshold to ~0.75-0.80.
    22 Sep it is not: catching paraphrases suppresses independent witnesses,
    and at 0.85 two of five measured witness pairs would already have been
    lost. See test_dedup_corroboration.py (BUG-013).
    """
    from app.services.dedup import _cosine_similarity, _get_embedding_model

    model = _get_embedding_model()

    def cos(a, b):
        return _cosine_similarity(
            model.encode(a, convert_to_numpy=True),
            model.encode(b, convert_to_numpy=True),
        )

    paraphrase = cos("Water rising near Kankarbagh road", "Kankarbagh road is flooding fast")
    distinct = cos(
        "Water entering ground floor shops near Kankarbagh main road",
        "Kankarbagh underpass completely submerged, cars stuck",
    )
    unrelated = cos(BASE_TEXT, "Traffic signal broken at Danapur crossing")

    assert paraphrase > distinct > unrelated
    assert paraphrase == pytest.approx(0.82, abs=0.05)
    assert unrelated < 0.30


@requires_embeddings
def test_t12_seed_reports_are_not_falsely_deduplicated(dedup):
    """
    Guards the Day 1 end-to-end scenario: T12 submits six reports within 2 km of
    each other and expects five distinct ones to survive into a single cluster.
    If the text gate were loose enough to collapse them, T12's expected counts
    would be wrong for a reason that has nothing to do with the pipeline.
    """
    seeds = [
        "Water entering ground floor shops near Kankarbagh main road",
        "Kankarbagh underpass completely submerged, cars stuck",
        "Knee deep water outside my house, drain overflowing",
        "Flooding on the road to Patna junction, buses diverted",
        "Sewage water mixed with rain water on the street here",
    ]
    seen = []
    for text in seeds:
        assert dedup.is_duplicate(text, PATNA_LAT, PATNA_LNG, T0, seen) is False
        seen.append((text, PATNA_LAT, PATNA_LNG, T0))

    # ...but the deliberate exact repeat of #1 must still be caught.
    assert dedup.is_duplicate(seeds[0], PATNA_LAT, PATNA_LNG, T0, seen) is True


def test_one_match_among_several_non_matches(dedup):
    """A real candidate list is mostly misses — the single hit must still win."""
    reports = [
        existing(text="Traffic signal broken at Danapur crossing", minutes=1),
        existing(text="Power cut in Rajendra Nagar since morning", minutes=2),
        existing(lat=PATNA_LAT + 0.010, minutes=3),   # right text, too far
        existing(minutes=5),                          # the match
    ]
    assert check(dedup, reports) is True


def test_all_three_gates_must_pass_together(dedup):
    """Each of these fails exactly one gate, so none is a duplicate."""
    assert check(dedup, [existing(minutes=20)]) is False                      # time only
    assert check(dedup, [existing(lat=PATNA_LAT + 0.02, minutes=1)]) is False  # distance only
    assert check(dedup, [existing(text="Completely unrelated civic issue")]) is False


# ── _haversine_km() ────────────────────────────────────────────────────────────

def test_haversine_identical_points_is_zero():
    assert _haversine_km(PATNA_LAT, PATNA_LNG, PATNA_LAT, PATNA_LNG) == pytest.approx(0.0)


def test_haversine_one_hundredth_degree_lat_is_about_1_11_km():
    dist = _haversine_km(PATNA_LAT, PATNA_LNG, PATNA_LAT + 0.01, PATNA_LNG)
    assert dist == pytest.approx(1.11, abs=0.02)


def test_haversine_patna_to_delhi():
    dist = _haversine_km(PATNA_LAT, PATNA_LNG, 28.6139, 77.2090)
    assert dist == pytest.approx(845, abs=10)


def test_haversine_is_symmetric():
    there = _haversine_km(PATNA_LAT, PATNA_LNG, 28.6139, 77.2090)
    back = _haversine_km(28.6139, 77.2090, PATNA_LAT, PATNA_LNG)
    assert there == pytest.approx(back)
