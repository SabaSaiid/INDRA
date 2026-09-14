"""
INDRA Platform — Live Feed API
GET /api/feed/recent?limit=10 — recent raw_reports as feed items
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(prefix="/api/feed", tags=["Feed"])

# Map source_type to frontend-compatible icon key and label
SOURCE_MAP = {
    "CITIZEN_APP": {"source": "citizen", "sourceLabel": "Citizen report"},
    "TWITTER_IMD": {"source": "social", "sourceLabel": "Social media"},
    "AWS_SENSOR": {"source": "imd", "sourceLabel": "AWS Sensor"},
    "CWC_GAUGE": {"source": "imd", "sourceLabel": "CWC Gauge"},
    "OFFICIAL_DISPATCH": {"source": "news", "sourceLabel": "Official Dispatch"},
}


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

    result = await db.execute(query, {"limit": limit})
    rows = result.fetchall()

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
