"""
INDRA Platform — Metadata API
GET /api/meta/filters — every value the event filters can take, with how many events have it
GET /api/meta/sources — whether each feed INDRA reads is alive, and how much it has stored

The filter bar should offer only values that exist in the data: a "Cold wave"
option with nothing behind it is a dead end, and a list hard-coded in the
dashboard goes stale the day a new type is added. So the options come from the
events themselves, each with its count.

Counts are over events that are not REJECTED, as `GET /api/events` lists them
by default — except `review_statuses`, which counts every status including
REJECTED, so the status dropdown can offer what `?review_status=REJECTED`
returns.

Cached for 60 s under `meta:filters`. The expiry travels inside the value
because the cache's in-memory fallback keeps no TTL of its own; this keeps the
behaviour the same with Redis up or down. A new event can therefore take up to
a minute to appear in the dropdowns; it appears in the list at once.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.services import cache
from app.services.feed_status import DEAD_LETTER, FEEDS, feed_state, load_heartbeats, stale_after_s
from app.services.hazards import FAMILIES, family_of, label_of

logger = logging.getLogger("indra.api.meta")
router = APIRouter(prefix="/api/meta", tags=["Meta"])

CACHE_KEY = "meta:filters"
CACHE_TTL_SECONDS = 60
# Wall-clock rather than monotonic: the expiry is stored in Redis, which other
# processes read. Tests replace it.
_clock = time.time

IST = timezone(timedelta(hours=5, minutes=30))
_SEVERITY_ORDER = ["ADVISORY", "MODERATE", "HIGH", "CRITICAL"]


async def _rows(db: AsyncSession, sql: str) -> List[Any]:
    return (await db.execute(text(sql))).fetchall()


def _ist_date(ts) -> Any:
    return ts.astimezone(IST).date().isoformat() if ts else None


async def _compute(db: AsyncSession) -> Dict[str, Any]:
    types = await _rows(db, """
        SELECT CAST(event_type AS text), count(*)
        FROM verified_events WHERE review_status != 'REJECTED'
        GROUP BY 1 ORDER BY 2 DESC, 1
    """)
    statuses = await _rows(db, """
        SELECT CAST(review_status AS text), count(*)
        FROM verified_events
        GROUP BY 1 ORDER BY 2 DESC, 1
    """)
    severities = dict(await _rows(db, """
        SELECT CAST(severity AS text), count(*)
        FROM verified_events WHERE review_status != 'REJECTED'
        GROUP BY 1
    """))
    sources = await _rows(db, """
        SELECT CAST(r.source_type AS text), count(DISTINCT r.event_id)
        FROM raw_reports r JOIN verified_events e ON e.id = r.event_id
        WHERE e.review_status != 'REJECTED'
        GROUP BY 1 ORDER BY 2 DESC, 1
    """)
    places = await _rows(db, """
        SELECT state, district, count(*)
        FROM verified_events
        WHERE review_status != 'REJECTED' AND state IS NOT NULL
        GROUP BY state, district
    """)
    span = await _rows(db, """
        SELECT min(verified_at), max(verified_at)
        FROM verified_events WHERE review_status != 'REJECTED'
    """)

    family_counts: Dict[str, int] = {}
    for event_type, n in types:
        fam = family_of(event_type)
        if fam:
            family_counts[fam] = family_counts.get(fam, 0) + n

    # A NULL district is counted in its state and never listed as a district:
    # "null" is not a place anyone can filter by.
    states: Dict[str, Dict[str, Any]] = {}
    for state, district, n in places:
        entry = states.setdefault(state, {"name": state, "count": 0, "districts": []})
        entry["count"] += n
        if district is not None:
            entry["districts"].append({"name": district, "count": n})
    for entry in states.values():
        entry["districts"].sort(key=lambda d: (-d["count"], d["name"]))

    date_min, date_max = span[0] if span else (None, None)
    return {
        "event_types": [
            {"value": t, "label": label_of(t), "family": family_of(t), "count": n} for t, n in types
        ],
        "families": [{"value": f, "count": family_counts[f]} for f in FAMILIES if f in family_counts],
        "review_statuses": [{"value": s, "count": n} for s, n in statuses],
        "severities": [{"value": s, "count": severities[s]} for s in _SEVERITY_ORDER if s in severities],
        "source_types": [{"value": s, "count": n} for s, n in sources],
        "states": sorted(states.values(), key=lambda s: (-s["count"], s["name"])),
        "date_min": _ist_date(date_min),
        "date_max": _ist_date(date_max),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/filters")
async def filter_options(db: AsyncSession = Depends(get_db)):
    """The values the event filters can take, each with its count. See the module docstring."""
    now = _clock()
    hit = await cache.get_json(CACHE_KEY)
    if isinstance(hit, list) and len(hit) == 2 and hit[0] > now:
        return hit[1]

    try:
        payload = await _compute(db)
    except Exception as e:
        # No demo payload: a dropdown of invented options would send people to
        # filter for events that do not exist.
        logger.warning(f"Database query failed in filter_options: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    await cache.set_json(CACHE_KEY, [now + CACHE_TTL_SECONDS, payload], ttl_seconds=CACHE_TTL_SECONDS)
    return payload


# ─── GET /api/meta/sources ──────────────────────────────────────────────────
#
# Phase 2 T2. Each poller writes a heartbeat to feed_status at the end of every
# tick (services/feed_status.py), so status is the tick's outcome, not a guess
# from the newest row: `failing` after 3 failed ticks in a row, with the error;
# `stale` after 3 poll intervals without a successful tick; `disabled` when the
# setting is off. Push feeds (citizen, official) have no tick and are `ok`.
#
# rows_24h and rows_total are counted from the table each feed writes to, so
# they are what is stored, whatever the poller believes it wrote.
# `newest_row_at` keeps the figure this route served before T2.


def _iso(ts) -> Optional[str]:
    return ts.isoformat() if ts else None


@router.get("/sources")
async def data_sources(db: AsyncSession = Depends(get_db)):
    """Per feed: status from its heartbeat, the last error, rows in the last 24 h and in total."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    feeds: List[Dict[str, Any]] = []
    try:
        heartbeats = await load_heartbeats(db)
        for spec in FEEDS:
            row = (await db.execute(text(f"""
                SELECT max({spec.time_column}),
                       count(*) FILTER (WHERE {spec.time_column} >= now() - INTERVAL '24 hours'),
                       count(*)
                FROM {spec.table}
                WHERE {spec.where}
            """))).fetchone()
            newest, rows_24h, rows_total = row if row else (None, 0, 0)

            beat = heartbeats.get(spec.feed, {})
            enabled = spec.enabled(settings)
            interval = spec.poll_interval_s(settings)
            # A push feed's "last success" is the last thing it received.
            last_success = newest if spec.push else beat.get("last_success_at")

            feeds.append({
                "feed": spec.feed,
                "kind": spec.kind,
                "title": spec.title,
                "enabled": enabled,
                "status": feed_state(
                    enabled=enabled,
                    push=spec.push,
                    last_success_at=last_success,
                    consecutive_failures=int(beat.get("consecutive_failures") or 0),
                    poll_interval_s=interval,
                    now=now,
                ),
                "last_success_at": _iso(last_success),
                "last_attempt_at": _iso(beat.get("last_attempt_at")),
                "last_error": beat.get("last_error"),
                "last_error_at": _iso(beat.get("last_error_at")),
                "consecutive_failures": int(beat.get("consecutive_failures") or 0),
                "items_last_tick": beat.get("items_last_tick"),
                "newest_row_at": _iso(newest),
                "rows_24h": int(rows_24h or 0),
                "rows_total": int(rows_total or 0),
                "poll_interval_s": interval,
                "stale_after_s": stale_after_s(spec, settings),
                "basis": "push" if spec.push else "heartbeat",
            })
    except Exception as e:
        logger.warning(f"Database query failed in data_sources: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Messages the pipeline gave up on after its retries (Phase 2 T8). 0 is
    # the healthy answer; anything else is waiting in the dead-letter topic for
    # scripts/replay_dlq.py.
    dead = heartbeats.get(DEAD_LETTER, {})
    dead_letters = {
        "total": int(dead.get("rows_total") or 0),
        "last_at": _iso(dead.get("last_error_at")),
        "last_error": dead.get("last_error"),
        "topic": settings.KAFKA_DLQ_TOPIC,
    }
    return {"generated_at": now.isoformat(), "feeds": feeds, "dead_letters": dead_letters}
