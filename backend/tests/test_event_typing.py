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
