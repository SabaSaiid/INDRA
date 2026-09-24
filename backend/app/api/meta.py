"""
INDRA Platform — Metadata API
GET /api/meta/filters — every value the event filters can take, with how many events have it

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
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import cache
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
