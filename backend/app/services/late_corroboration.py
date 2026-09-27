"""
INDRA Platform — Late corroboration (Phase 4 T5)

IMD often issues or upgrades a warning **after** the first citizen reports
arrive, and an airport reports fog or a thunderstorm on its own half-hourly
clock. An event scored at 10:00 should rise when the warning lands at 10:20.

    await rescore_open_events([trigger, …])

**Triggers:**

* the SACHET poller stored a new or updated warning (`sachet_trigger`); a
  Cancel is a trigger too, since it withdraws evidence an event was scored on;
* the METAR poller stored an observation with a relevant code (TS, VCTS, FG,
  DS, SS, SQ, GR, GS, RA+) or past a threshold: visibility under 1,000 m, gusts
  of 39 km/h or more, 40 °C or more, 10 °C or less (`metar_triggers`).

**Candidates:** events updated in the last 24 h, not REJECTED, of a family the
trigger speaks to, whose footprint intersects the warning's polygon (or whose
district the district-only warning names), or whose centre lies within 50 km
of the station.

**Bounded:** at most 50 events per trigger per tick; the rest are carried to
the next tick. **Idempotent:** each (trigger, event) pair is processed once,
remembered in the cache for 24 h, and a re-score that changes nothing writes
nothing (pipeline.rescore_event).

Every change is broadcast as `VERIFIED_EVENT` and published to the verified
events topic, exactly as a pipeline write is. Never raises: late corroboration
is an improvement on a stored event, and its failure must not cost a poller its
tick.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import text

from app.services import cache, clock

logger = logging.getLogger("indra.services.late_corroboration")

MAX_EVENTS_PER_TRIGGER = 50
OPEN_EVENT_HOURS = 24
STATION_RADIUS_KM = 50
MARK_TTL_SECONDS = 24 * 60 * 60
MARK_PREFIX = "late:"

# METAR thresholds that make an observation worth re-scoring for.
VISIBILITY_TRIGGER_M = 1000
GUST_TRIGGER_KMH = 39.0
HEAT_TRIGGER_C = 40.0
COLD_TRIGGER_C = 10.0


@dataclass(frozen=True)
class Trigger:
    kind: str                     # "sachet" | "metar"
    key: str                      # "sachet:<identifier>@<sent>" | "metar:<station>@<time>"
    families: Tuple[str, ...]     # hazard families it can speak to
    identifier: Optional[str] = None
    station: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


# Triggers with candidates left over, carried to the next tick. Per process,
# like every poller (BUG-011).
_pending: Dict[str, Trigger] = {}


def pending() -> List[Trigger]:
    return list(_pending.values())


def _reset_for_tests() -> None:
    _pending.clear()


# ── Building triggers ──────────────────────────────────────────────────────────

def sachet_trigger(
    identifier: str,
    *,
    event: Optional[str],
    headline: Optional[str],
    sent_at: Optional[datetime],
    msg_type: Optional[str] = None,
) -> Optional[Trigger]:
    """A stored warning as a trigger; None when its text names no hazard family."""
    from app.services.official_warnings import Warning, warning_families

    families = warning_families(Warning(
        identifier=identifier, sender=None, event=event, headline=headline,
        raw_severity=None, expires_at=None, matched_by="polygon",
    ))
    if not families:
        return None
    stamp = sent_at.isoformat() if sent_at else "unsent"
    return Trigger(
        kind="sachet",
        key=f"sachet:{identifier}@{stamp}",
        families=tuple(sorted(families)),
        identifier=identifier,
        detail={"identifier": identifier, "event": event, "msg_type": msg_type, "sent_at": stamp},
    )


def metar_families(obs: Dict[str, Any]) -> Tuple[str, ...]:
    """Which families an observation speaks to; empty when it is unremarkable."""
    codes = [str(c) for c in (obs.get("weather_codes") or [])]
    bases = {c.rstrip("+-") for c in codes}
    families = set()
    if bases & {"TS", "GR", "GS", "SQ", "DS", "SS"} or any(b.startswith("VCTS") for b in bases):
        families.add("convective")
    if "FG" in bases:
        families.add("visibility")
    if "RA+" in codes or ("TS" in bases and "RA" in bases):
        families.add("water")
    visibility = obs.get("visibility_m")
    if visibility is not None and visibility < VISIBILITY_TRIGGER_M:
        families.add("visibility")
    wind = max([v for v in (obs.get("gust_kmh"), obs.get("wind_kmh")) if v is not None], default=None)
    if wind is not None and wind >= GUST_TRIGGER_KMH:
        families.add("convective")
    temperature = obs.get("temperature_c")
    if temperature is not None and (temperature >= HEAT_TRIGGER_C or temperature <= COLD_TRIGGER_C):
        families.add("thermal")
    return tuple(sorted(families))


def metar_triggers(observations: Iterable[Dict[str, Any]]) -> List[Trigger]:
    """The stored observations that are worth re-scoring for, as triggers."""
    from app.workers.metar_poller import station_table

    table = station_table()
    out: List[Trigger] = []
    for obs in observations:
        families = metar_families(obs)
        if not families:
            continue
        station = str(obs.get("station_code"))
        known = table.get(station) or {}
        lat, lng = known.get("lat"), known.get("lon")
        if lat is None or lng is None:
            continue
        at = obs.get("recorded_at")
        stamp = at.isoformat() if isinstance(at, datetime) else str(at)
        out.append(Trigger(
            kind="metar",
            key=f"metar:{station}@{stamp}",
            families=families,
            station=station,
            lat=float(lat),
            lng=float(lng),
            detail={"station": station, "recorded_at": stamp,
                    "codes": list(obs.get("weather_codes") or [])},
        ))
    return out


# ── Candidates ─────────────────────────────────────────────────────────────────

async def candidates(db, trigger: Trigger, now: datetime) -> List[UUID]:
    """Every open event the trigger may speak to, oldest first."""
    common = {
        "since": now - timedelta(hours=OPEN_EVENT_HOURS),
        "families": list(trigger.families),
    }
    open_events = """
        COALESCE(e.updated_at, e.verified_at) > CAST(:since AS timestamptz)
        AND e.review_status <> 'REJECTED'
        AND e.hazard_family = ANY(CAST(:families AS text[]))
    """
    if trigger.kind == "sachet":
        sql = f"""
            SELECT e.id
            FROM verified_events e
            JOIN agency_alerts a ON a.identifier = :identifier
            WHERE {open_events}
              AND (
                    (a.area_polygon IS NOT NULL
                     AND ST_Intersects(a.area_polygon, COALESCE(e.boundary_polygon, e.center_point)))
                 OR (a.area_polygon IS NULL AND e.district IS NOT NULL
                     AND position(lower(e.district) IN lower(COALESCE(a.area_desc, ''))) > 0)
              )
            ORDER BY e.verified_at, e.id
        """
        params = {**common, "identifier": trigger.identifier}
    else:
        sql = f"""
            SELECT e.id
            FROM verified_events e
            WHERE {open_events}
              AND e.center_point IS NOT NULL
              AND ST_DWithin(
                    e.center_point::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    :metres
                  )
            ORDER BY e.verified_at, e.id
        """
        params = {**common, "lat": trigger.lat, "lng": trigger.lng,
                  "metres": STATION_RADIUS_KM * 1000}
    rows = (await db.execute(text(sql), params)).fetchall()
    return [r[0] for r in rows]


# ── Running ────────────────────────────────────────────────────────────────────

def _mark_key(trigger: Trigger, event_id: Any) -> str:
    return f"{MARK_PREFIX}{trigger.key}:{event_id}"


async def _broadcast(event: Dict[str, Any]) -> None:
    """VERIFIED_EVENT to the dashboard and the verified events topic. Never raises."""
    try:
        from app.main import ws_manager

        await ws_manager.broadcast({"type": "VERIFIED_EVENT", "event": event})
    except Exception as e:
        logger.warning(f"Late corroboration broadcast failed for {event.get('event_code')}: {e}")
    try:
        from app.services.event_publisher import publish_verified_event

        await publish_verified_event(event)
    except Exception as e:
        logger.warning(f"Late corroboration publish failed for {event.get('event_code')}: {e}")


async def _run_one(trigger: Trigger, session_factory) -> Dict[str, int]:
    from app.services import pipeline

    now = clock.now()
    async with session_factory() as db:
        ids = await candidates(db, trigger, now)

    todo = []
    for event_id in ids:
        if await cache.get_json(_mark_key(trigger, event_id)) is None:
            todo.append(event_id)
    batch, rest = todo[:MAX_EVENTS_PER_TRIGGER], todo[MAX_EVENTS_PER_TRIGGER:]

    changed = 0
    for event_id in batch:
        async with session_factory() as db:
            event = await pipeline.rescore_event(
                db, event_id, trigger=trigger.key, trigger_detail=trigger.detail
            )
        await cache.set_json(_mark_key(trigger, event_id), 1, ttl_seconds=MARK_TTL_SECONDS)
        if event is not None:
            changed += 1
            await _broadcast(event)

    if rest:
        _pending[trigger.key] = trigger
    else:
        _pending.pop(trigger.key, None)
    return {"candidates": len(ids), "processed": len(batch), "changed": changed, "deferred": len(rest)}


async def rescore_open_events(
    triggers: Sequence[Trigger], session_factory=None
) -> Dict[str, int]:
    """
    Run the carried-over triggers, then the new ones. Returns the totals.
    Never raises.
    """
    if session_factory is None:
        from app.core.database import async_session as session_factory

    totals = {"triggers": 0, "candidates": 0, "processed": 0, "changed": 0, "deferred": 0}
    queue: Dict[str, Trigger] = dict(_pending)
    for t in triggers:
        queue.setdefault(t.key, t)
    for trigger in queue.values():
        try:
            result = await _run_one(trigger, session_factory)
        except Exception as e:
            logger.warning(f"Late corroboration for {trigger.key} failed (non-fatal): "
                           f"{type(e).__name__}: {e}")
            continue
        totals["triggers"] += 1
        for k, v in result.items():
            totals[k] += v
    if totals["changed"] or totals["deferred"]:
        logger.info(
            f"Late corroboration: {totals['triggers']} trigger(s), {totals['processed']} event(s) "
            f"re-scored, {totals['changed']} changed, {totals['deferred']} carried to the next tick"
        )
    return totals
