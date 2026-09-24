"""
INDRA Platform — Live Feed API
GET /api/feed/recent?limit=10 — what has just happened, newest first

Three streams, merged on one clock:

- **report** — a citizen report or an official dispatch was stored (`raw_reports`);
- **event** — the pipeline formed an event (`verified_events`, not REJECTED);
- **warning** — an official warning now in force arrived from SACHET (`agency_alerts`).

The feed used to read `raw_reports` alone, and printed each report's UTC clock
time as if it were local: a report filed at 20:27 IST showed as "14:57" (BUG-071).
On a day with no citizen reports it sat on one three-day-old line while the
SACHET poller was storing a hundred official warnings nobody could see scroll
past. Every item now carries `at` (ISO 8601, with its offset) and `time` in IST.

`include` narrows the streams (`reports,events,warnings`), for a caller that
wants reports only.
"""

import logging
from datetime import timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.demo import demo_fallback
from app.services.hazards import label_of

logger = logging.getLogger("indra.api.feed")
router = APIRouter(prefix="/api/feed", tags=["Feed"])

IST = timezone(timedelta(hours=5, minutes=30))
STREAMS = ("reports", "events", "warnings")

# Map source_type to frontend-compatible icon key and label
SOURCE_MAP = {
    "CITIZEN_APP": {"source": "citizen", "sourceLabel": "Citizen report"},
    "TWITTER_IMD": {"source": "social", "sourceLabel": "Social media"},
    "AWS_SENSOR": {"source": "imd", "sourceLabel": "AWS Sensor"},
    "CWC_GAUGE": {"source": "imd", "sourceLabel": "CWC Gauge"},
    # Filed through the authenticated route (BUG-025). It was drawn as "news".
    "OFFICIAL_DISPATCH": {"source": "official", "sourceLabel": "Official dispatch"},
    # Phase 2's feeds. The label is refined per item in _report_item: a post
    # says "Mastodon", a headline its publisher's name.
    "SOCIAL_MEDIA": {"source": "social", "sourceLabel": "Social media"},
    "NEWS_MEDIA": {"source": "news", "sourceLabel": "News"},
}

# What a collected item is labelled with, by platform (Phase 2 T8).
PLATFORM_LABELS = {"mastodon": "Mastodon", "google_news": "Google News"}

DEMO_FEED: List[Dict[str, Any]] = [
    {
        "id": "feed-1",
        "source": "imd",
        "sourceLabel": "IMD Doppler Radar",
        "message": "Doppler radar Patna detects high reflectivity (>52 dBZ) over Kankarbagh & Rajendra Nagar.",
        "time": "12:10",
    },
    {
        "id": "feed-2",
        "source": "imd",
        "sourceLabel": "CWC Gauge",
        "message": "Ganga River water level at Digha Ghat: 50.42m (0.90m above Warning Level). Rising @ 3cm/hr.",
        "time": "11:58",
    },
    {
        "id": "feed-3",
        "source": "citizen",
        "sourceLabel": "Citizen report",
        "message": "Severe waterlogging 3.5ft near Rajendra Nagar Overbridge. Vehicles stranded, power cut.",
        "time": "11:42",
    },
    {
        "id": "feed-4",
        "source": "social",
        "sourceLabel": "Social media",
        "message": "Verified X/Twitter reports of culvert blockage near Boring Road intersection with geotagged media.",
        "time": "11:30",
    },
    {
        "id": "feed-5",
        "source": "news",
        "sourceLabel": "Official Dispatch",
        "message": "NDRF 9th Battalion deployed 4 inflatable rescue boats and dewatering pumps to Patna Central.",
        "time": "11:15",
    },
    {
        "id": "feed-6",
        "source": "imd",
        "sourceLabel": "IMD Weather",
        "message": "Nowcast Warning: Moderate to intense thunderstorm with surface winds up to 45 km/h over Patna, Vaishali.",
        "time": "10:50",
    },
]


def _place(district: Optional[str], state: Optional[str]) -> Optional[str]:
    parts = [p for p in (district, state) if p]
    return ", ".join(parts) or None


def _stamp(ts) -> Dict[str, Optional[str]]:
    if ts is None:
        return {"at": None, "time": ""}
    return {"at": ts.isoformat(), "time": ts.astimezone(IST).strftime("%H:%M")}


REPORTS_SQL = text("""
    SELECT id, source_type, raw_text, created_at, district, state, event_id, duplicate_of,
           platform, source_meta->>'publisher'
    FROM raw_reports
    ORDER BY created_at DESC
    LIMIT :limit
""")

EVENTS_SQL = text("""
    SELECT id, event_code, CAST(event_type AS text), CAST(severity AS text),
           CAST(review_status AS text), verified_at, district, state
    FROM verified_events
    WHERE review_status != 'REJECTED'
    ORDER BY verified_at DESC
    LIMIT :limit
""")

# In force only, as GET /api/alerts/agency lists them by default: an expired
# warning is not news about now.
WARNINGS_SQL = text("""
    SELECT id, sender, event, CAST(severity AS text), headline, area_desc,
           COALESCE(sent_at, fetched_at) AS at
    FROM agency_alerts
    WHERE expires_at IS NULL OR expires_at > now()
    ORDER BY COALESCE(sent_at, fetched_at) DESC
    LIMIT :limit
""")


def _report_item(row) -> Dict[str, Any]:
    info = SOURCE_MAP.get(row[1], {"source": "news", "sourceLabel": "Unknown Source"})
    status = "duplicate" if row[7] else ("in_event" if row[6] else "pending")
    label = info["sourceLabel"]
    if row[1] == "NEWS_MEDIA" and row[9]:
        label = row[9]  # the publisher: "The Hindu", "News On AIR"
    elif row[8] in PLATFORM_LABELS:
        label = PLATFORM_LABELS[row[8]]
    item = {
        "id": str(row[0]),
        "kind": "report",
        "source": info["source"],
        "sourceLabel": label,
        "message": (row[2] or "")[:200],
        "place": _place(row[4], row[5]),
        "status": status,
        **_stamp(row[3]),
    }
    if row[8]:
        item["platform"] = row[8]
    return item


def _event_item(row) -> Dict[str, Any]:
    place = _place(row[6], row[7])
    status = (row[4] or "").replace("_", " ").lower()
    parts = [label_of(row[2]) if row[2] else None, place, status or None]
    return {
        "id": f"event-{row[0]}",
        "kind": "event",
        "event_id": str(row[0]),
        "source": "event",
        "sourceLabel": row[1] or "Event formed",
        "message": " · ".join(p for p in parts if p),
        "place": place,
        "severity": row[3],
        "status": row[4],
        **_stamp(row[5]),
    }


def _warning_item(row) -> Dict[str, Any]:
    return {
        "id": f"warning-{row[0]}",
        "kind": "warning",
        "source": "warning",
        "sourceLabel": row[1] or "Official warning",
        "message": (row[4] or row[2] or "Official warning")[:200],
        "place": (row[5] or None) and row[5][:120],
        "severity": row[3],
        **_stamp(row[6]),
    }


@router.get("/recent")
async def get_recent_feed(
    limit: int = Query(10, ge=1, le=50),
    include: Optional[str] = Query(
        None, description="Comma-separated streams: reports, events, warnings (default: all three)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Reports, events and official warnings, newest first, for the LiveFeed component."""
    wanted = {s.strip().lower() for s in include.split(",")} & set(STREAMS) if include else set(STREAMS)
    if not wanted:
        wanted = set(STREAMS)

    db_error = None
    items: List[Dict[str, Any]] = []
    try:
        if "reports" in wanted:
            rows = (await db.execute(REPORTS_SQL, {"limit": limit})).fetchall()
            items.extend(_report_item(r) for r in rows)
        if "events" in wanted:
            rows = (await db.execute(EVENTS_SQL, {"limit": limit})).fetchall()
            items.extend(_event_item(r) for r in rows)
        if "warnings" in wanted:
            rows = (await db.execute(WARNINGS_SQL, {"limit": limit})).fetchall()
            items.extend(_warning_item(r) for r in rows)

        if items:
            # ISO strings with the same offset sort as the instants they name;
            # asyncpg returns every timestamptz in UTC.
            items.sort(key=lambda it: it["at"] or "", reverse=True)
            return items[:limit]
    except Exception as e:
        logger.warning(f"Database query failed in get_recent_feed: {e}")
        db_error = e

    return demo_fallback("GET /api/feed/recent", lambda: DEMO_FEED[:limit], list, db_error)
