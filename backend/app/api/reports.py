"""
INDRA Platform — Reports API
GET  /api/reports/trend?range=7d  — daily total_reports for the trend chart
POST /api/reports/submit          — stores the report, pushes to Redpanda, returns 202
                                    (503 if it could not be stored)
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
from app.core.demo import demo_fallback
from app.services.credibility import compute_credibility
from app.services.geocoding import OutOfIndiaBoundsError, sanitize_coordinates

logger = logging.getLogger("indra.api.reports")
router = APIRouter(prefix="/api/reports", tags=["Reports"])
settings = get_settings()


class ReportSubmission(BaseModel):
    """Pydantic model for incoming citizen report."""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    text: str = Field(..., min_length=5, max_length=2000)
    media_url: Optional[str] = None


DEMO_TREND = [
    {"date": "09 Sep", "reports": 85},
    {"date": "10 Sep", "reports": 112},
    {"date": "11 Sep", "reports": 145},
    {"date": "12 Sep", "reports": 198},
    {"date": "13 Sep", "reports": 264},
    {"date": "14 Sep", "reports": 310},
    {"date": "15 Sep", "reports": 134},
]


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

    db_error = None
    try:
        result = await db.execute(query, {"days": days})
        rows = result.fetchall()

        if rows:
            return [
                {
                    "date": row[0].strftime("%d %b"),
                    "reports": row[1],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning(f"Database query failed in reports_trend: {e}")
        db_error = e

    return demo_fallback("GET /api/reports/trend", lambda: DEMO_TREND, list, db_error)


@router.post("/submit", status_code=202)
async def submit_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a citizen report, persists to DB, pushes to Redpanda topic.

    * Stored and published → 202, `"queued": true`.
    * Stored, publish failed → 202, `"queued": false`. The row exists but the
      pipeline has not been told about it.
    * Not stored → 503 and nothing is published. A 202 here used to tell the
      citizen their report was accepted when it had been dropped.
    """
    # Sanitize & normalize coordinates against Indian bounds. Out-of-bounds
    # reports are refused outright and never stored: two of them would
    # otherwise cluster wherever they were snapped to and become an event.
    try:
        valid_lat, valid_lng, resolved_city, resolved_state = sanitize_coordinates(
            report.latitude,
            report.longitude,
            text_hint=report.text,
            snap_out_of_bounds=settings.SNAP_OUT_OF_BOUNDS_COORDINATES,
        )
    except OutOfIndiaBoundsError as e:
        logger.info(f"Rejected report with out-of-bounds coordinates: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    report_id = uuid.uuid4()
    source_type = "CITIZEN_APP"
    credibility = compute_credibility(source_type, report.text)

    # Compute geom_point and H3 cell
    try:
        import h3
        h3_cell = h3.latlng_to_cell(valid_lat, valid_lng, settings.H3_HEX_RESOLUTION)
    except Exception:
        h3_cell = None

    # Insert into DB
    insert_query = text("""
        INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point, h3_res8, media_url, credibility_score)
        VALUES (
            :id, :source_type, :raw_text, :lat, :lng,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
            :h3_cell, :media_url, :credibility
        )
    """)

    try:
        await db.execute(insert_query, {
            "id": str(report_id),
            "source_type": source_type,
            "raw_text": report.text,
            "lat": valid_lat,
            "lng": valid_lng,
            "h3_cell": h3_cell,
            "media_url": report.media_url,
            "credibility": credibility,
        })
        await db.commit()
    except Exception as e:
        logger.error(f"Report {report_id} could not be stored — returning 503: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="Report could not be stored")

    # Push to Redpanda/Kafka. The report is already stored, so a failure here
    # is reported in the response but is not an error for the citizen.
    queued = False
    try:
        from aiokafka import AIOKafkaProducer
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            # Publish exactly what was stored: the sanitised coordinates and
            # the column names of the raw_reports row. The pipeline still
            # re-reads the row by id, but nothing else consuming this topic
            # should be able to see coordinates the database never held.
            message = json.dumps({
                "id": str(report_id),
                "source_type": source_type,
                "raw_text": report.text,
                "latitude": valid_lat,
                "longitude": valid_lng,
                "h3_res8": h3_cell,
                "credibility_score": credibility,
                "media_url": report.media_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await producer.send_and_wait(
                settings.KAFKA_REPORTS_TOPIC,
                message.encode("utf-8"),
            )
            queued = True
        finally:
            await producer.stop()
    except Exception as e:
        # Non-fatal: report is already in DB
        logger.warning(f"Could not push to Redpanda (non-fatal): {e}")

    return JSONResponse(
        status_code=202,
        content={"id": str(report_id), "status": "accepted", "queued": queued},
    )
