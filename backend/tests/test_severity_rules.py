"""
T3 (Day 5) — severity from what the reports say, not from how many there are.

Pure, no database. This is the file to open if a nodal officer asks "how did you
decide this was CRITICAL?", because the answer must be a rule they can argue
with rather than a model they have to trust.

The rule is the higher of two axes over the cluster's non-duplicate reports:

    depth   max depth_cm    >=120 CRITICAL · >=60 HIGH · >=20 MODERATE · else ADVISORY
    count   report count                     >=10 HIGH · >=5  MODERATE · else ADVISORY

Depth cuts are operational: 20 cm stops a two-wheeler, 60 cm floats a small car,
120 cm is above an adult's waist. The count axis deliberately cannot reach
CRITICAL — a count says something is happening, not how bad it is.

What this replaces: `_derive_severity(cluster_size)`, under which one report
saying "water two metres deep" was MODERATE and twelve saying "small puddle"
was HIGH.
"""

import pytest

from app.models.enums import Severity
from app.services.pipeline import (
    SEVERITY_ORDER,
    _count_severity,
    _depth_severity,
    _derive_severity,
    score_cluster,
)

NO_DEPTH = "Road flooded outside the community hall"


def _texts(body, n=1):
    """One text carrying the phrase under test, padded with depth-free filler."""
    return [body] + [NO_DEPTH] * (n - 1)


# ── The depth axis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "depth_cm,expected",
    [
        (300, Severity.CRITICAL),
        (121, Severity.CRITICAL),
        (120, Severity.CRITICAL),    # boundary, inclusive
        (119, Severity.HIGH),        # just below
        (60, Severity.HIGH),         # boundary, inclusive
        (59, Severity.MODERATE),     # just below
        (20, Severity.MODERATE),     # boundary, inclusive
        (19, Severity.ADVISORY),     # just below
        (0, Severity.ADVISORY),
        (None, Severity.ADVISORY),   # no report quoted a depth
    ],
)
def test_depth_axis_boundaries(depth_cm, expected):
    assert _depth_severity(depth_cm) is expected


# ── The count axis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "count,expected",
    [
        (100, Severity.HIGH),
        (10, Severity.HIGH),         # boundary, inclusive
        (9, Severity.MODERATE),      # just below
        (5, Severity.MODERATE),      # boundary, inclusive
        (4, Severity.ADVISORY),      # just below
        (1, Severity.ADVISORY),
        (0, Severity.ADVISORY),
    ],
)
def test_count_axis_boundaries(count, expected):
    assert _count_severity(count) is expected


def test_the_count_axis_can_never_reach_critical():
    """
    Popularity is not severity.

    A thousand people saying "wet road" is a thousand people saying "wet road".
    CRITICAL has to come from what the water is doing, which is the depth axis.
    """
    for count in (10, 25, 100, 10_000):
        assert _count_severity(count) is not Severity.CRITICAL


# ── Real phrases, end to end through extract_metadata ──────────────────────────

@pytest.mark.parametrize(
    "body,count,expected,why",
    [
        ("Chest deep water in the gali", 2, Severity.CRITICAL, "130 cm, depth axis alone"),
        ("Water up to the first floor ceiling", 2, Severity.CRITICAL, "reach rule, 250 cm"),
        ("2-3 ft paani bhara hai", 2, Severity.HIGH, "91 cm from the upper bound"),
        ("Waist deep water in the lane", 2, Severity.HIGH, "100 cm"),
        ("Knee deep water outside my house", 2, Severity.MODERATE, "50 cm"),
        ("घुटनों तक पानी", 2, Severity.MODERATE, "50 cm, Hindi"),
        ("Ankle deep water near the shop", 2, Severity.ADVISORY, "15 cm, below 20"),
        (NO_DEPTH, 2, Severity.ADVISORY, "no depth, 2 reports"),
    ],
)
def test_severity_from_real_phrases(body, count, expected, why):
    decided = _derive_severity(_texts(body, count), count)
    assert decided["severity"] is expected, why


# ── The two axes interacting — this is the whole point of max() ────────────────

def test_a_single_deep_report_outranks_a_crowd_of_shallow_ones():
    """
    One person in chest-deep water beats two people on a wet road.

    This is the case the old cluster-size rule got exactly backwards, and it is
    the dam-break / flash-flood shape: the first report of a serious incident
    arrives alone.
    """
    deep = _derive_severity(["Chest deep water in the gali"], 1)
    assert deep["severity"] is Severity.CRITICAL
    assert deep["basis"]["depth_axis"] == "CRITICAL"
    assert deep["basis"]["count_axis"] == "ADVISORY"


def test_a_crowd_outranks_a_single_shallow_report():
    """The count axis still carries an event nobody measured."""
    crowd = _derive_severity([NO_DEPTH] * 12, 12)
    assert crowd["severity"] is Severity.HIGH
    assert crowd["basis"]["depth_axis"] == "ADVISORY"
    assert crowd["basis"]["count_axis"] == "HIGH"
    assert crowd["provenance"] == "rule_based_count_only"


def test_count_axis_wins_when_it_is_the_higher_of_the_two():
    """12 reports of ankle-deep water: shallow, but plainly happening."""
    decided = _derive_severity(_texts("Ankle deep water near the shop", 12), 12)
    assert decided["severity"] is Severity.HIGH
    assert decided["basis"]["depth_axis"] == "ADVISORY"
    assert decided["basis"]["count_axis"] == "HIGH"


def test_max_is_not_alphabetical():
    """
    Severity is a str enum, so a naive max() returns HIGH over CRITICAL.

    SEVERITY_ORDER exists solely to stop that, and it fails silently in exactly
    the worst case — the most serious events — so it gets its own test.
    """
    assert max(Severity.CRITICAL, Severity.HIGH) is Severity.HIGH  # the trap
    assert max(Severity.CRITICAL, Severity.HIGH, key=SEVERITY_ORDER.index) is Severity.CRITICAL

    # And through the real rule: CRITICAL depth with a HIGH count must stay CRITICAL.
    decided = _derive_severity(_texts("Chest deep water in the gali", 12), 12)
    assert decided["severity"] is Severity.CRITICAL


# ── Provenance and basis: the receipt has to say which evidence was used ───────

def test_provenance_distinguishes_measured_depth_from_count_only():
    with_depth = _derive_severity(_texts("Knee deep water outside my house", 3), 3)
    without = _derive_severity([NO_DEPTH] * 3, 3)

    assert with_depth["provenance"] == "rule_based_depth_and_count"
    assert without["provenance"] == "rule_based_count_only"


def test_basis_names_the_phrase_that_decided_it():
    """
    A commander overriding this severity must be able to see what they override.
    """
    decided = _derive_severity(_texts("Knee deep water outside my house", 5), 5)
    basis = decided["basis"]

    assert basis["rule"] == "max(depth_axis, count_axis)"
    assert basis["max_depth_cm"] == 50
    assert basis["depth_basis"] == "body:knee"
    assert basis["reports_with_depth"] == 1
    assert basis["report_count"] == 5
    assert basis["depth_axis"] == "MODERATE"
    assert basis["count_axis"] == "MODERATE"


def test_the_deepest_report_decides_not_the_first():
    """max over the cluster, so ordering cannot change the answer."""
    bodies = [
        "Ankle deep water near the shop",
        "Chest deep water in the gali",
        "Knee deep water outside my house",
    ]
    decided = _derive_severity(bodies, 3)
    assert decided["severity"] is Severity.CRITICAL
    assert decided["basis"]["max_depth_cm"] == 130

    # Reversed input, identical verdict — Postgres does not promise row order.
    assert _derive_severity(list(reversed(bodies)), 3)["basis"] == decided["basis"]


# ── Determinism ────────────────────────────────────────────────────────────────

def test_severity_is_deterministic_over_fifty_runs():
    bodies = _texts("Waist deep water in the lane", 5)
    verdicts = {_derive_severity(bodies, 5)["severity"] for _ in range(50)}
    assert len(verdicts) == 1


def test_empty_and_malformed_texts_do_not_raise():
    """Ingestion accepts odd text; severity must survive all of it."""
    for bodies in ([], [""], [None], ["  "], ["🌊" * 100], ["x" * 4000]):
        decided = _derive_severity(bodies, len(bodies))
        assert decided["severity"] in SEVERITY_ORDER
        assert decided["provenance"] == "rule_based_count_only"


# ── Through score_cluster, where the receipt is assembled ──────────────────────

STATS = {
    "count": 5,
    "centroid_lat": 25.5943,
    "centroid_lng": 85.1375,
    "max_pairwise_km": 1.9,
    "radius_km": 0.95,
}


def _score(texts):
    return score_cluster(
        dict(STATS), ["CITIZEN_APP"] * 5, 0.35, 15.6, report_texts=list(texts)
    )


def test_score_cluster_publishes_severity_basis_in_the_receipt():
    scored = _score(_texts("Waist deep water in the lane", 5))

    assert scored["severity"] is Severity.HIGH
    assert scored["receipt"]["provenance"]["severity"] == "rule_based_depth_and_count"
    assert scored["receipt"]["severity_basis"]["max_depth_cm"] == 100


def test_content_changes_severity_while_confidence_is_untouched():
    """
    Severity and confidence are independent readings of the same cluster.

    Same geometry, same sources, same weather — only the words differ. The
    confidence score must not move, because none of its six factors reads text;
    the severity must, because that is the entire change.
    """
    shallow = _score([NO_DEPTH] * 5)
    deep = _score(_texts("Chest deep water in the gali", 5))

    assert shallow["confidence"] == deep["confidence"]
    assert shallow["severity"] is Severity.MODERATE
    assert deep["severity"] is Severity.CRITICAL


def test_report_texts_is_required():
    """
    Forgetting it must be a TypeError, never a silent downgrade to count-only.

    A default would reintroduce the popularity-grading bug invisibly, with every
    existing test still passing.
    """
    with pytest.raises(TypeError):
        score_cluster(dict(STATS), ["CITIZEN_APP"], 0.35, 15.6)
