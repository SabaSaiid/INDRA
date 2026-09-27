"""
Phase 3 T6 — an event's type is a published count of what its reports say.

`decide_event_type` (`app/services/event_typing.py`): each report votes its
`hazard_primary`, or the citizen's pick when its text names no hazard; the
most votes wins, a tie goes to precedence, no votes → UNCLASSIFIED. T6's table
row for row, then what does not vote. The UNCLASSIFIED cap, the override and
the 403 are pipeline and API behaviour, in `test_hazard_clustering.py`.
"""

import uuid

from app.services.event_typing import RULE, decide_event_type


def _r(hazard=None, citizen=None, flags=(), duplicate_of=None):
    return {
        "id": uuid.uuid4(),
        "hazard_primary": hazard,
        "citizen_hazard": citizen,
        "flags": list(flags),
        "duplicate_of": duplicate_of,
    }


def _type(reports):
    return decide_event_type(reports)["event_type"]


# ── T6's table ─────────────────────────────────────────────────────────────────

def test_four_floods_and_one_rain():
    decided = decide_event_type([_r("URBAN_FLOOD")] * 4 + [_r("RAINFALL")])
    assert decided["event_type"] == "URBAN_FLOOD"
    assert decided["basis"]["votes"] == {"URBAN_FLOOD": 4, "RAINFALL": 1}


def test_a_tie_goes_to_precedence():
    """The impact outranks its cause: 2 floods and 2 rain reports are a flood."""
    assert _type([_r("RAINFALL"), _r("URBAN_FLOOD"), _r("RAINFALL"), _r("URBAN_FLOOD")]) == "URBAN_FLOOD"


def test_three_thunderstorms_and_two_strong_winds():
    assert _type([_r("THUNDERSTORM")] * 3 + [_r("STRONG_WIND")] * 2) == "THUNDERSTORM"


def test_the_citizens_pick_fills_in_when_the_text_is_silent():
    decided = decide_event_type([_r(), _r(), _r(citizen="HEATWAVE")])
    assert decided["event_type"] == "HEATWAVE"
    assert decided["basis"]["citizen_choice_used"] == 1
    assert decided["basis"]["reports_untagged"] == 3


def test_no_votes_is_unclassified():
    decided = decide_event_type([_r()] * 4)
    assert decided["event_type"] == "UNCLASSIFIED"
    assert decided["basis"]["votes"] == {}
    assert decided["basis"]["reports_voting"] == 0


# ── What does not vote ─────────────────────────────────────────────────────────

def test_the_text_outranks_the_citizens_pick():
    assert _type([_r("FOG", citizen="URBAN_FLOOD")]) == "FOG"


def test_a_forecast_does_not_vote():
    reports = [_r("HEATWAVE")] + [_r("RAINFALL", flags=["not_an_observation"])] * 3
    assert _type(reports) == "HEATWAVE"


def test_a_duplicate_does_not_vote():
    reports = [_r("FOG")] + [_r("URBAN_FLOOD", duplicate_of=uuid.uuid4())] * 3
    assert _type(reports) == "FOG"


def test_a_citizens_unclassified_or_unknown_pick_is_no_vote():
    assert _type([_r(citizen="UNCLASSIFIED"), _r(citizen="DONT_KNOW")]) == "UNCLASSIFIED"


def test_the_basis_is_the_published_rule():
    basis = decide_event_type([_r("FOG")])["basis"]
    assert basis["rule"] == RULE == "majority of report hazards, ties by precedence"


def test_the_vote_does_not_depend_on_order():
    reports = [_r("RAINFALL"), _r("URBAN_FLOOD"), _r("THUNDERSTORM"), _r("URBAN_FLOOD"), _r("RAINFALL")]
    assert _type(reports) == _type(list(reversed(reports))) == "URBAN_FLOOD"


# ── The caps: UNCLASSIFIED (T6) and posts only (T9) are never auto-published ───

def _near_perfect(event_type, source_types):
    """
    Every independent signal at its best: 250 mm of rain and, since receipt v2,
    an Extreme IMD warning in force (official_warning 1.0). An UNCLASSIFIED
    event has no hazard to match a warning or the weather against, so both are
    offline for it, as in the pipeline.
    """
    from app.services.corroboration import effective_reporters
    from app.services.evidence import Evidence
    from app.services.pipeline import _legacy_evidence, score_cluster

    stats = {"centroid_lat": 25.59, "centroid_lng": 85.13, "radius_km": 0.3, "max_pairwise_km": 0.2,
             "count": 20}
    witnesses = effective_reporters(
        [{"id": i, "credibility": 0.9, "reporter_hash": f"r{i}", "flags": [], "source_type": "CITIZEN_APP"}
         for i in range(20)]
    )
    rain = event_type != "UNCLASSIFIED"
    evidence = _legacy_evidence(
        event_type, 1.0 if rain else None, 250.0 if rain else None,
        "station_reading" if rain else "not_applicable",
    )
    if rain:
        evidence["official"] = Evidence(
            1.0, "computed", "official warning", 1.0, source="sachet_cap",
            reason="IMD Patna: Extreme Heavy Rainfall warning in force",
        )
    return score_cluster(
        stats, source_types, 1.0 if rain else None, 250.0 if rain else None,
        report_texts=["Water 5 feet deep, people stranded"] * 20, event_type=event_type,
        density=witnesses, eps_km=5.0, weather_source="station_reading" if rain else "not_applicable",
        evidence=evidence,
    )


def test_an_unclassified_event_at_099_waits_for_a_human():
    scored = _near_perfect("UNCLASSIFIED", ["OFFICIAL_DISPATCH"] * 10 + ["CWC_GAUGE"] * 10)
    assert scored["confidence"] >= 0.95
    assert scored["review_status"].value == "PENDING_HUMAN_REVIEW"
    assert scored["caps"] == ["unclassified"]


def test_a_posts_only_event_above_the_gate_waits_for_a_human():
    scored = _near_perfect("URBAN_FLOOD", ["SOCIAL_MEDIA"] * 10 + ["NEWS_MEDIA"] * 10)
    assert scored["confidence"] >= 0.90
    assert scored["review_status"].value == "PENDING_HUMAN_REVIEW"
    assert scored["caps"] == ["posts_only"]


def test_the_same_score_from_official_sources_is_auto_published():
    scored = _near_perfect("URBAN_FLOOD", ["OFFICIAL_DISPATCH"] * 10 + ["CWC_GAUGE"] * 10)
    assert scored["review_status"].value == "AUTO_PUBLISHED"
    assert scored["caps"] == []
