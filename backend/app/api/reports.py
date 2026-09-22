"""
INDRA Platform — Reports API
GET  /api/reports/trend?range=7d  — daily total_reports for the trend chart
POST /api/reports/submit          — stores the report, pushes to Redpanda, returns 202
                                    (503 if it could not be stored)
POST /api/reports/official        — the same, for an authenticated COMMANDER/ADMIN,
                                    stored as OFFICIAL_DISPATCH with who filed it
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
from app.core.security import TokenData, require_roles
from app.services.credibility import compute_credibility
from app.services.geocoding import OutOfIndiaBoundsError, sanitize_coordinates
from app.services.text_processing import clean_text, detect_language, extract_metadata

logger = logging.getLogger("indra.api.reports")
router = APIRouter(prefix="/api/reports", tags=["Reports"])
settings = get_settings()


def _analyse(raw_text: str, report_id) -> Optional[dict]:
    """
    Layer-3 extraction for one report: cleaned text, language, depth, keywords.

    Rules and dictionaries only — no model. `raw_text` is never modified; this is
    stored alongside it in raw_reports.analysis.

    **Best-effort by design.** Any failure returns None so the caller stores the
    report with analysis NULL and still answers 202. Losing a disaster report
    because a regex raised would be a far worse bug than not knowing how deep the
    water was, so the whole thing is wrapped. Content severity re-extracts from
    raw_text at scoring time and therefore does not depend on this succeeding.
    """
    try:
        meta = extract_metadata(raw_text)
        return {
            "cleaned_text": clean_text(raw_text),
            "language": detect_language(raw_text),
            "depth_cm": meta["depth_cm"],
            "depth_basis": meta["depth_basis"],
            "keywords": meta["keywords"],
            "places": meta["places"],
            "url_count": meta["url_count"],
            "phone_count": meta["phone_count"],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(
            f"Analysis failed for report {report_id}, storing it without one: {e}"
        )
        return None


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


async def _ingest(
    report: ReportSubmission,
    db: AsyncSession,
    source_type: str,
    submitted_by: Optional[str],
) -> JSONResponse:
    """
    Store one report and publish it. Shared by the citizen and official routes,
    which differ only in the source they are allowed to claim.

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
    credibility = compute_credibility(source_type, report.text)

    # Compute geom_point and H3 cell
    try:
        import h3
        h3_cell = h3.latlng_to_cell(valid_lat, valid_lng, settings.H3_HEX_RESOLUTION)
    except Exception:
        h3_cell = None

    analysis = _analyse(report.text, report_id)

    # Insert into DB
    insert_query = text("""
        INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point, h3_res8, district, state, media_url, credibility_score, analysis, submitted_by)
        VALUES (
            :id, :source_type, :raw_text, :lat, :lng,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
            :h3_cell, :district, :state, :media_url, :credibility, CAST(:analysis AS jsonb), :submitted_by
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
            # Resolved above and, until now, thrown away on the next line: the
            # table had no column to put it in, so the ingest path computed a
            # location it could not keep.
            "district": resolved_city or None,
            "state": resolved_state or None,
            "media_url": report.media_url,
            "credibility": credibility,
            "analysis": json.dumps(analysis) if analysis is not None else None,
            "submitted_by": submitted_by,
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
        content={
            "id": str(report_id),
            "status": "accepted",
            "queued": queued,
            "source_type": source_type,
        },
    )


@router.post("/submit", status_code=202)
async def submit_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a citizen report, persists to DB, pushes to Redpanda topic.

    Anonymous, and always `CITIZEN_APP`. The source is fixed here rather than
    read from the request: if a client could name its own source, anyone could
    claim OFFICIAL_DISPATCH and hand themselves the highest reliability in the
    model (BUG-025). Trusted sources use POST /api/reports/official.
    """
    return await _ingest(report, db, source_type="CITIZEN_APP", submitted_by=None)


@router.post("/official", status_code=202)
async def submit_official_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(require_roles("COMMANDER", "ADMIN")),
):
    """
    A report from a trusted field source — a district control room, an SDRF
    team — filed by an authenticated COMMANDER or ADMIN (BUG-025).

    Stored as `OFFICIAL_DISPATCH`, source reliability 1.00, with the operator's
    token subject in `submitted_by`. Everything after storage is the citizen
    path: the same coordinate checks, the same dedup, clustering and scoring.
    One official report in a cluster lifts the Source Reliability factor to
    1.00, because that factor is the maximum over the cluster's sources; it
    does not bypass corroboration, weather or human review.

    The route is exactly as trusted as the account behind it. The demo accounts
    are published in the dashboard for its persona switcher, so in this build
    it shows the mechanism — role-gated and attributed — not a secret.
    """
    return await _ingest(
        report, db, source_type="OFFICIAL_DISPATCH", submitted_by=operator.sub
    )


@router.get("/recent")
async def list_recent_reports(
    limit: int = Query(100, ge=1, le=500),
    unfused_only: bool = Query(
        True,
        description="Only reports not yet part of an event and not suppressed as duplicates",
    ),
    hours: int = Query(72, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """
    Citizen reports with coordinates, for the field-reports map layer.

    These are **raw reports, not events**. Nothing here has been clustered,
    corroborated or scored, and a caller drawing them must draw them
    differently from a verified event — the whole point of the layer is to
    show what has come in that the pipeline has not yet turned into anything.

    `unfused_only` is the default because the fused ones are already on the
    map as their event. It also excludes reports suppressed as duplicates:
    counting a duplicate as a separate sighting is the double-count the dedup
    step exists to prevent, and drawing it would undo that on the screen.

    The layer exists because 4 of the 9 reports in the demo database belong to
    no event — one that could not reach DBSCAN_MIN_SAMPLES alone, and three
    suppressed against it — and were therefore invisible everywhere except a
    total in the KPI strip (BUG-035, BUG-037).
    """
    conditions = ["created_at >= NOW() - make_interval(hours => CAST(:hours AS int))"]
    if unfused_only:
        conditions.append("event_id IS NULL")
        conditions.append("duplicate_of IS NULL")

    query = text(f"""
        SELECT id, source_type, raw_text, latitude, longitude,
               district, state, created_at, event_id, duplicate_of, analysis
        FROM raw_reports
        WHERE {" AND ".join(conditions)}
        ORDER BY created_at DESC
        LIMIT :limit
    """)

    db_error = None
    try:
        rows = (await db.execute(query, {"limit": limit, "hours": hours})).fetchall()
        return [
            {
                "id": str(r[0]),
                "source_type": r[1],
                "text": r[2][:300],
                "lat": r[3],
                "lng": r[4],
                "district": r[5],
                "state": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
                "fused": r[8] is not None,
                "duplicate": r[9] is not None,
                "depth_cm": (r[10] or {}).get("depth_cm"),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"Database query failed in list_recent_reports: {e}")
        db_error = e

    # No demo payload: an empty field-reports layer is an honest map, and a
    # fabricated citizen report is the one thing this console must never draw.
    return demo_fallback("GET /api/reports/recent", list, list, db_error)
