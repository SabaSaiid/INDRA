"""
INDRA Platform — Reports API
GET  /api/reports/trend?range=7d  — daily total_reports for the trend chart
POST /api/reports/submit          — accepts report, pushes to Redpanda, returns 202
"""

import uuid
import json
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings

logger = logging.getLogger("indra.api.reports")
router = APIRouter(prefix="/api/reports", tags=["Reports"])
settings = get_settings()


class ReportSubmission(BaseModel):
    """Pydantic model for incoming citizen report."""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    text: str = Field(..., min_length=5, max_length=2000)
    media_url: Optional[str] = None


@router.get("/trend")
async def reports_trend(
    range: str = Query("7d", description="Time range: 7d, 14d, 30d"),
    db: AsyncSession = Depends(get_db),
):
    """Daily total_reports counts for the line chart."""
    interval_map = {"7d": 7, "14d": 14, "30d": 30}
    days = interval_map.get(range, 7)

    query = text("""
        WITH date_series AS (
            SELECT generate_series(
                (CURRENT_DATE - :days * INTERVAL '1 day')::date,
                CURRENT_DATE::date,
                '1 day'::interval
            )::date AS day
        )
        SELECT
            ds.day,
            COALESCE(COUNT(r.id), 0) AS reports
        FROM date_series ds
        LEFT JOIN raw_reports r ON r.created_at::date = ds.day
        GROUP BY ds.day
        ORDER BY ds.day
    """)

    result = await db.execute(query, {"days": days})
    rows = result.fetchall()

    return [
        {
            "date": row[0].strftime("%d %b"),
            "reports": row[1],
        }
        for row in rows
    ]


@router.post("/submit", status_code=202)
async def submit_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a citizen report, persists to DB, pushes to Redpanda topic.
    Returns 202 Accepted with the report ID.
    """
    report_id = uuid.uuid4()

    # Compute geom_point and H3 cell
    try:
        import h3
        h3_cell = h3.latlng_to_cell(report.latitude, report.longitude, settings.H3_HEX_RESOLUTION)
    except Exception:
        h3_cell = None

    # Insert into DB
    insert_query = text("""
        INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point, h3_res8, media_url, credibility_score)
        VALUES (
            :id, 'CITIZEN_APP', :raw_text, :lat, :lng,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
            :h3_cell, :media_url, 0.5
        )
    """)

    try:
        await db.execute(insert_query, {
            "id": str(report_id),
            "raw_text": report.text,
            "lat": report.latitude,
            "lng": report.longitude,
            "h3_cell": h3_cell,
            "media_url": report.media_url,
        })
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist report: {e}")
        raise HTTPException(status_code=500, detail="Failed to store report")

    # Push to Redpanda/Kafka (non-blocking, fail-safe)
    try:
        from aiokafka import AIOKafkaProducer
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            message = json.dumps({
                "id": str(report_id),
                "source_type": "CITIZEN_APP",
                "text": report.text,
                "latitude": report.latitude,
                "longitude": report.longitude,
                "media_url": report.media_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await producer.send_and_wait(
                settings.KAFKA_REPORTS_TOPIC,
                message.encode("utf-8"),
            )
        finally:
            await producer.stop()
    except Exception as e:
        # Non-fatal: report is already in DB
        logger.warning(f"Could not push to Redpanda (non-fatal): {e}")

    return JSONResponse(
        status_code=202,
        content={"id": str(report_id), "status": "accepted"},
    )
