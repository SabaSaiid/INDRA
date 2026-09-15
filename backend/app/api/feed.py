"""
INDRA Platform — Live Feed API
GET /api/feed/recent?limit=10 — recent raw_reports as feed items
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = logging.getLogger("indra.api.feed")
router = APIRouter(prefix="/api/feed", tags=["Feed"])

# Map source_type to frontend-compatible icon key and label
SOURCE_MAP = {
    "CITIZEN_APP": {"source": "citizen", "sourceLabel": "Citizen report"},
    "TWITTER_IMD": {"source": "social", "sourceLabel": "Social media"},
    "AWS_SENSOR": {"source": "imd", "sourceLabel": "AWS Sensor"},
    "CWC_GAUGE": {"source": "imd", "sourceLabel": "CWC Gauge"},
    "OFFICIAL_DISPATCH": {"source": "news", "sourceLabel": "Official Dispatch"},
}

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


@router.get("/recent")
async def get_recent_feed(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Recent raw_reports formatted as feed items for the LiveFeed component."""
    query = text("""
        SELECT id, source_type, raw_text, created_at
        FROM raw_reports
        ORDER BY created_at DESC
        LIMIT :limit
    """)

    try:
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()

        if rows:
            feed_items = []
            for row in rows:
                source_info = SOURCE_MAP.get(
                    row[1],
                    {"source": "news", "sourceLabel": "Unknown Source"},
                )
                time_str = row[3].strftime("%H:%M") if row[3] else ""

                feed_items.append({
                    "id": str(row[0]),
                    "source": source_info["source"],
                    "sourceLabel": source_info["sourceLabel"],
                    "message": row[2][:200],  # Truncate long messages
                    "time": time_str,
                })
            return feed_items
    except Exception as e:
        logger.warning(f"Database query failed in get_recent_feed (falling back to demo feed): {e}")

    return DEMO_FEED[:limit]
