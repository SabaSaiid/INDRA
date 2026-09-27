"""
INDRA Platform — The official-warning factor (Phase 4 T4)

Since 21 Sep the SACHET poller has stored every IMD, CWC and state SDMA warning
NDMA publishes, with its polygon, and **no scoring code read them** (bug.md).
This module is that reading: does an official warning in force right now cover
this event, and is it a warning about this hazard?

    official_warning_evidence(db, event_type, …) -> (Evidence, cyclone_nearby)

**Which warnings count** — those in force:

* `COALESCE(effective, onset, sent) ≤ now ≤ expires` (a warning with no expiry
  cannot be shown to be in force, so it does not count);
* CAP `status` Actual, `msgType` Alert or Update (a Cancel withdraws, it does
  not warn).

**Where** — the warning's `area_polygon` intersects the event's footprint (its
reports' hull, buffered 250 m as the stored `boundary_polygon` is, or the
stored polygon, or its centre). A warning with no polygon (district codes only)
counts when its area description names the event's district. That second rule
is an addition to the plan: without it a district-only warning is invisible.

**What** — the hazard family matches. The warning's family comes from running
Phase 3's tagger over its `event` and `headline` fields: "Heavy Rainfall" is
water, "Thunderstorm & Lightning" convective, "Heat Wave" thermal. A warning
the tagger cannot read is logged (once) so the lexicon can learn it, and never
matched.

**Score** — the most severe matching warning, on CAP's own severity word:
Extreme 1.0, Severe 0.85, Moderate 0.6, Minor 0.3, Unknown 0.3.

**States:**

* SACHET's last successful poll within 30 minutes and no match → **0.0,
  online**: "no official warning in force covers this event". That is real
  evidence, because the feed is known to be current.
* SACHET stale, disabled or never polled → **offline**: an absent warning from a
  feed that is not being read is not evidence of anything.

"Now" is `services/clock.py`, never the system clock.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import text

from app.core.config import get_settings
from app.services.evidence import IST, Evidence, offline
from app.services.hazards import family_of, label_of

logger = logging.getLogger("indra.services.official_warnings")

SACHET_FEED = "sachet"
SACHET_FRESH_MINUTES = 30
SOURCE = "sachet_cap"

# CAP <severity>, as the agency wrote it.
WARNING_SCORES: Dict[str, float] = {
    "Extreme": 1.0,
    "Severe": 0.85,
    "Moderate": 0.6,
    "Minor": 0.3,
    "Unknown": 0.3,
}
UNKNOWN_SCORE = 0.3

IN_FORCE_MSG_TYPES = ("alert", "update")
CYCLONE_SEARCH_KM = 500

# Warnings the tagger could not read, logged once each.
_unreadable_logged: set = set()


@dataclass(frozen=True)
class Warning:
    identifier: str
    sender: Optional[str]
    event: Optional[str]
    headline: Optional[str]
    raw_severity: Optional[str]
    expires_at: Optional[datetime]
    matched_by: str  # "polygon" | "district"

    @property
    def score(self) -> float:
        return WARNING_SCORES.get((self.raw_severity or "Unknown").strip().title(), UNKNOWN_SCORE)

    @property
    def text(self) -> str:
        return ". ".join(p for p in (self.event, self.headline) if p)


@lru_cache(maxsize=4096)
def _tag(text_: str) -> Tuple[Tuple[str, ...], Optional[str]]:
    """(every hazard type the warning names, its primary) — the Phase 3 tagger."""
    from app.services.hazard_tagger import tag_hazards

    tagged = tag_hazards(text_)
    return tuple(h["type"] for h in tagged["hazards"]), tagged["hazard_primary"]


def warning_hazards(w: Warning) -> Tuple[Tuple[str, ...], Optional[str]]:
    types, primary = _tag(w.text)
    if not types and w.identifier not in _unreadable_logged:
        _unreadable_logged.add(w.identifier)
        logger.info(
            f"SACHET warning {w.identifier} names no hazard the tagger knows "
            f"({w.text[:160]!r}); it is never matched. Worth a lexicon entry."
        )
    return types, primary


def warning_families(w: Warning) -> set:
    types, _ = warning_hazards(w)
    return {f for f in (family_of(t) for t in types) if f}


def _until(at: Optional[datetime]) -> str:
    if at is None:
        return "an unstated time"
    return at.astimezone(IST).strftime("%d %b %H:%M IST")


def warning_line(w: Warning) -> str:
    """'IMD Patna: Severe Heavy Rainfall warning in force until 28 Sep 08:30 IST (SACHET CAP, polygon)'."""
    what = w.event or w.headline or "warning"
    severity = (w.raw_severity or "Unknown").strip().title()
    return (
        f"{w.sender or 'an agency'}: {severity} {what} warning in force until "
        f"{_until(w.expires_at)} (SACHET CAP, matched by {w.matched_by})"
    )


def evidence_from_warnings(
    event_type: Optional[str],
    covering: Sequence[Warning],
    *,
    sachet_fresh: bool,
    sachet_age_minutes: Optional[float] = None,
) -> Evidence:
    """
    The factor from the warnings in force that cover the event. Pure: the
    database work (in force, where) is done by the caller.
    """
    if not sachet_fresh:
        age = (
            f"{sachet_age_minutes:.0f} min ago" if sachet_age_minutes is not None
            else "never, or the poller is off"
        )
        return offline(
            f"SACHET last polled successfully {age} (more than {SACHET_FRESH_MINUTES} min), "
            "so the absence of a warning means nothing: offline"
        )
    etype = event_type or "URBAN_FLOOD"
    family = family_of(etype)
    if family is None:
        return offline("no hazard type to match an official warning against")

    matching = [w for w in covering if family in warning_families(w)]
    others = [w for w in covering if w not in matching]
    detail: Dict[str, Any] = {
        "in_force_covering": [
            {
                "identifier": w.identifier,
                "sender": w.sender,
                "event": w.event,
                "raw_severity": w.raw_severity,
                "score": w.score,
                "expires_at": w.expires_at.isoformat() if w.expires_at else None,
                "families": sorted(warning_families(w)),
                "matched_by": w.matched_by,
                "matches_hazard": w in matching,
            }
            for w in covering
        ],
        "rule": "most severe in-force warning of the event's hazard family covering it",
    }

    if matching:
        best = max(
            matching,
            key=lambda w: (w.score, w.expires_at or datetime.min.replace(tzinfo=timezone.utc), w.identifier),
        )
        detail["chosen"] = best.identifier
        return Evidence(
            best.score, "computed", "official warning", best.score, source=SOURCE,
            reason=warning_line(best), detail=detail,
        )

    if others:
        _, primary = warning_hazards(others[0])
        what = label_of(primary).lower() if primary else "another hazard"
        reason = f"the warning in force here is for {what}, not {label_of(etype).lower()}"
    else:
        reason = "no official warning in force covers this event"
    return Evidence(0.0, "computed", "official warning", 0.0, source=SOURCE, reason=reason, detail=detail)


# ── The database side ──────────────────────────────────────────────────────────

async def sachet_freshness(db, now: datetime) -> Tuple[bool, Optional[float]]:
    """(fresh, minutes since the last successful SACHET poll). Never raises."""
    if not get_settings().SACHET_POLLER_ENABLED:
        return False, None
    try:
        last = (await db.execute(
            text("SELECT last_success_at FROM feed_status WHERE feed = :feed"),
            {"feed": SACHET_FEED},
        )).scalar()
    except Exception as e:
        logger.warning(f"SACHET heartbeat unreadable, treating the feed as stale: {e}")
        return False, None
    if last is None:
        return False, None
    age = (now - last).total_seconds() / 60.0
    return age <= SACHET_FRESH_MINUTES, round(age, 1)


# The event's footprint, three ways. Each is a complete geometry expression.
_FOOTPRINT_FROM_REPORTS = """
    SELECT ST_Buffer(ST_ConvexHull(ST_Collect(geom_point))::geography, 250)::geometry
    FROM raw_reports
    WHERE id = ANY(CAST(:ids AS uuid[])) AND geom_point IS NOT NULL
"""
_FOOTPRINT_FROM_EVENT = """
    SELECT COALESCE(boundary_polygon, center_point)
    FROM verified_events WHERE id = CAST(:event_id AS uuid)
"""
_FOOTPRINT_FROM_POINT = "SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)"

_IN_FORCE = """
    lower(COALESCE(a.status, '')) = 'actual'
    AND lower(COALESCE(a.msg_type, '')) IN ('alert', 'update')
    AND COALESCE(a.effective_at, a.onset_at, a.sent_at) <= CAST(:now AS timestamptz)
    AND a.expires_at >= CAST(:now AS timestamptz)
"""


def _row_to_warning(row) -> Warning:
    return Warning(
        identifier=row[0], sender=row[1], event=row[2], headline=row[3],
        raw_severity=row[4], expires_at=row[5], matched_by=row[6],
    )


async def covering_warnings(
    db,
    *,
    now: datetime,
    report_ids: Optional[Sequence[UUID]] = None,
    event_id: Optional[UUID] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    district: Optional[str] = None,
) -> List[Warning]:
    """Every warning in force now whose area covers the event's footprint."""
    params: Dict[str, Any] = {"now": now, "district": district}
    if report_ids:
        footprint = _FOOTPRINT_FROM_REPORTS
        params["ids"] = [str(i) for i in report_ids]
    elif event_id is not None:
        footprint = _FOOTPRINT_FROM_EVENT
        params["event_id"] = str(event_id)
    else:
        footprint = _FOOTPRINT_FROM_POINT
        params.update(lat=lat, lng=lng)
    rows = (await db.execute(
        text(f"""
            WITH fp(geom) AS ({footprint})
            SELECT a.identifier, a.sender, a.event, a.headline, a.raw_severity, a.expires_at,
                   CASE WHEN a.area_polygon IS NOT NULL THEN 'polygon' ELSE 'district' END
            FROM agency_alerts a CROSS JOIN fp
            WHERE {_IN_FORCE}
              AND (
                    (a.area_polygon IS NOT NULL AND fp.geom IS NOT NULL
                     AND ST_Intersects(a.area_polygon, fp.geom))
                 OR (a.area_polygon IS NULL AND CAST(:district AS text) IS NOT NULL
                     AND position(lower(CAST(:district AS text)) IN lower(COALESCE(a.area_desc, ''))) > 0)
              )
            ORDER BY a.identifier
        """),
        params,
    )).fetchall()
    return [_row_to_warning(r) for r in rows]


async def cyclone_warning_nearby(db, *, now: datetime, lat: float, lng: float) -> bool:
    """True when a cyclone warning is in force within 500 km of the point."""
    rows = (await db.execute(
        text(f"""
            SELECT a.identifier, a.sender, a.event, a.headline, a.raw_severity, a.expires_at,
                   'polygon'
            FROM agency_alerts a
            WHERE {_IN_FORCE}
              AND a.area_polygon IS NOT NULL
              AND ST_DWithin(a.area_polygon::geography,
                             ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                             :metres)
        """),
        {"now": now, "lat": lat, "lng": lng, "metres": CYCLONE_SEARCH_KM * 1000},
    )).fetchall()
    return any("CYCLONE" in warning_hazards(_row_to_warning(r))[0] for r in rows)


async def official_warning_evidence(
    db,
    event_type: Optional[str],
    *,
    now: datetime,
    lat: float,
    lng: float,
    report_ids: Optional[Sequence[UUID]] = None,
    event_id: Optional[UUID] = None,
    district: Optional[str] = None,
) -> Tuple[Evidence, Optional[bool]]:
    """
    (the factor's evidence, whether a cyclone warning is in force within
    500 km). The second is None when SACHET is stale, or the event is not a
    cyclone. Never raises: a failure is the factor offline.
    """
    fresh, age = await sachet_freshness(db, now)
    if not fresh:
        return evidence_from_warnings(event_type, [], sachet_fresh=False, sachet_age_minutes=age), None
    try:
        async with db.begin_nested():
            covering = await covering_warnings(
                db, now=now, report_ids=report_ids, event_id=event_id,
                lat=lat, lng=lng, district=district,
            )
            nearby = None
            if event_type == "CYCLONE":
                nearby = await cyclone_warning_nearby(db, now=now, lat=lat, lng=lng)
    except Exception as e:
        logger.warning(f"Official-warning lookup failed, factor offline: {type(e).__name__}: {e}")
        return offline("the official-warning lookup failed, so this factor is offline"), None
    return evidence_from_warnings(event_type, covering, sachet_fresh=True, sachet_age_minutes=age), nearby
