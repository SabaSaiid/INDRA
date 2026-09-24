"""
INDRA Platform — An event's type, by a published majority rule (Phase 3 T6)

    decide_event_type(reports) -> {"event_type": "URBAN_FLOOD", "basis": {...}}

**Each report votes once.** Its vote is the hazard its text is about
(`hazard_primary`, from the tagger). When the text names no hazard, the
category the citizen picked (`citizen_hazard`) votes instead: the text is the
evidence, and the citizen's own choice fills in when the text is silent.

**The most votes wins; a tie goes to precedence** (`services/hazards.py`: the
impact outranks its cause, so 2 floods and 2 rain reports make a flood event).
**No votes at all → UNCLASSIFIED**, which the pipeline never auto-publishes.

Not voting:
* a suppressed duplicate — it is already counted through its original;
* a forecast or warning (`not_an_observation`) — context, not a witness.

The basis goes into the receipt verbatim, so the type is a count anyone can
check against the reports in the event's provenance:

    {"rule": "majority of report hazards, ties by precedence",
     "votes": {"URBAN_FLOOD": 4, "RAINFALL": 1},
     "reports_voting": 5, "reports_untagged": 1, "citizen_choice_used": 1}
"""

from collections import Counter
from typing import Any, Dict, Mapping, Optional, Sequence

from app.models.enums import EventType
from app.services.hazards import HAZARDS, precedence_key

RULE = "majority of report hazards, ties by precedence"

# A citizen's pick that is not a real hazard (or is "don't know") is no vote.
_VOTABLE = {t for t in HAZARDS if t != EventType.UNCLASSIFIED.value}


def report_vote(report: Mapping[str, Any]) -> Optional[str]:
    """What one report votes for, or None. See the module docstring."""
    if report.get("duplicate_of") is not None:
        return None
    if "not_an_observation" in (report.get("flags") or []):
        return None
    for field in ("hazard_primary", "citizen_hazard"):
        value = report.get(field)
        if value in _VOTABLE:
            return value
    return None


def decide_event_type(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    votes: Counter = Counter()
    untagged = citizen = voting = 0
    for report in reports:
        if report.get("duplicate_of") is not None:
            continue
        if not report.get("hazard_primary"):
            untagged += 1
        vote = report_vote(report)
        if vote is None:
            continue
        voting += 1
        if report.get("hazard_primary") not in _VOTABLE:
            citizen += 1
        votes[vote] += 1

    if votes:
        top = max(votes.values())
        winner = min((t for t, n in votes.items() if n == top), key=precedence_key)
    else:
        winner = EventType.UNCLASSIFIED.value

    return {
        "event_type": winner,
        "basis": {
            "rule": RULE,
            "votes": dict(sorted(votes.items(), key=lambda kv: (-kv[1], precedence_key(kv[0])))),
            "reports_voting": voting,
            "reports_untagged": untagged,
            "citizen_choice_used": citizen,
        },
    }
