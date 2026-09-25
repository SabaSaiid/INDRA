"""
INDRA Platform — Reports API
GET  /api/reports/trend?range=7d  — daily total_reports for the trend chart
POST /api/reports/submit          — stores the report with its outbox message, returns 202
                                    (503 if it could not be stored)
POST /api/reports/official        — the same, for an authenticated COMMANDER/ADMIN,
                                    stored as OFFICIAL_DISPATCH with who filed it
GET  /api/reports/track/{docket}  — where a report is now, for the citizen holding its docket
"""

import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.empty import empty_or_503
from app.core.security import TokenData, require_roles
from app.models.enums import EventType
from app.services.geocoding import (
    LocationUnresolvedError,
    OutOfIndiaBoundsError,
    sanitize_coordinates,
)
from app.services.ingest import (
    StoreError,
    docket_status,
    normalise_docket,
    reporter_hash_for,
    store_report,
)

logger = logging.getLogger("indra.api.reports")
router = APIRouter(prefix="/api/reports", tags=["Reports"])


# How far observed_at may sit from the moment a report arrives. A phone clock a
# few minutes fast is normal; a report "from" tomorrow is not. A week back
# covers a citizen reporting after the fact without letting old events be
# injected as current ones.
OBSERVED_AT_MAX_AHEAD = timedelta(minutes=5)
OBSERVED_AT_MAX_AGE = timedelta(days=7)


class ReportSubmission(BaseModel):
    """Pydantic model for incoming citizen report."""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    text: str = Field(..., min_length=5, max_length=2000)
    media_url: Optional[str] = None
    # When it happened, with a timezone. Omitted means "now": observed_at is
    # stored equal to the time the report was received.
    observed_at: Optional[AwareDatetime] = None
    # The category the citizen picked, if any. Stored as their claim
    # (citizen_hazard); the event's type is still the platform's decision.
    hazard: Optional[EventType] = None

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_plausible(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        now = datetime.now(timezone.utc)
        if v > now + OBSERVED_AT_MAX_AHEAD:
            raise ValueError("observed_at is more than 5 minutes in the future")
        if v < now - OBSERVED_AT_MAX_AGE:
            raise ValueError("observed_at is more than 7 days in the past")
        return v


@router.get("/trend")
async def reports_trend(
    range: str = Query("7d", description="Time range: 7d, 14d, 30d"),
    db: AsyncSession = Depends(get_db),
):
    """
    Reports per IST day for the line chart, oldest first, one row per day.

    Days are Indian days. The series used to be bucketed by the database's UTC
    date, so a report filed between midnight and 05:30 IST was counted on the
    day before; and "7d" returned eight days (BUG-072).
    """
    interval_map = {"7d": 7, "14d": 14, "30d": 30}
    days = interval_map.get(range, 7)

    query = text("""
        WITH today AS (
            SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date AS d
        ),
        date_series AS (
            SELECT generate_series(
                (SELECT d FROM today) - (CAST(:days AS int) - 1),
                (SELECT d FROM today),
                '1 day'::interval
            )::date AS day
        )
        SELECT
            ds.day,
            COUNT(r.id) AS reports
        FROM date_series ds
        LEFT JOIN raw_reports r
               ON (r.created_at AT TIME ZONE 'Asia/Kolkata')::date = ds.day
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
                    "day": row[0].isoformat(),
                    "reports": int(row[1]),
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning(f"Database query failed in reports_trend: {e}")
        db_error = e

    return empty_or_503("GET /api/reports/trend", list, db_error)


async def _ingest(
    report: ReportSubmission,
    db: AsyncSession,
    source_type: str,
    submitted_by: Optional[str],
    reporter_id: Optional[str] = None,
) -> JSONResponse:
    """
    Store one report and queue it for the pipeline. Shared by the citizen and
    official routes, which differ only in the source they are allowed to claim.

    * Stored and published → 202, `"queued": true, "will_retry": false`.
    * Stored, not yet published → 202, `"queued": false, "will_retry": true`.
      The report and its message are both in the database, and the outbox
      relay publishes it as soon as Kafka answers (BUG-060).
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
        )
    except OutOfIndiaBoundsError as e:
        logger.info(f"Rejected report with out-of-bounds coordinates: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except LocationUnresolvedError as e:
        # Unreachable while latitude and longitude are required floats; kept
        # so a location that cannot be placed is a 422, never a 500.
        logger.info(f"Rejected report with no resolvable location: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    try:
        stored = await store_report(
            db,
            source_type=source_type,
            raw_text=report.text,
            latitude=valid_lat,
            longitude=valid_lng,
            district=resolved_city or None,
            state=resolved_state or None,
            media_url=report.media_url,
            submitted_by=submitted_by,
            observed_at=report.observed_at,
            # The pseudonym only: the X-Reporter-Id itself is never stored.
            reporter_hash=reporter_hash_for(reporter_id),
            citizen_hazard=report.hazard.value if report.hazard else None,
        )
    except StoreError:
        raise HTTPException(status_code=503, detail="Report could not be stored")

    return JSONResponse(
        status_code=202,
        content={
            "id": str(stored.id),
            # What the citizen keeps to follow the report: GET /track/{docket}.
            "docket": stored.docket,
            "status": "accepted",
            "queued": stored.queued,
            "will_retry": not stored.queued,
            "source_type": source_type,
        },
    )


@router.post("/submit", status_code=202)
async def submit_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
):
    """
    Accepts a citizen report, persists to DB, pushes to Redpanda topic.

    Anonymous, and always `CITIZEN_APP`. The source is fixed here rather than
    read from the request: if a client could name its own source, anyone could
    claim OFFICIAL_DISPATCH and hand themselves the highest reliability in the
    model (BUG-025). Trusted sources use POST /api/reports/official.

    `X-Reporter-Id` is a random id the client generates once and keeps. Only a
    keyed hash of it is stored, so reports from one device can be linked to
    each other and never to the device.
    """
    return await _ingest(
        report, db, source_type="CITIZEN_APP", submitted_by=None, reporter_id=x_reporter_id
    )


@router.post("/official", status_code=202)
async def submit_official_report(
    report: ReportSubmission,
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(require_roles("COMMANDER", "ADMIN")),
    x_reporter_id: Optional[str] = Header(None, max_length=200),
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
        report, db, source_type="OFFICIAL_DISPATCH", submitted_by=operator.sub,
        reporter_id=x_reporter_id,
    )


@router.get("/recent")
async def list_recent_reports(
    limit: int = Query(100, ge=1, le=500),
    unfused_only: bool = Query(
        True,
        description="Only reports not yet part of an event and not suppressed as duplicates",
    ),
    hours: int = Query(72, ge=1, le=720),
    include_feeds: bool = Query(
        False,
        description="Also list collected posts and headlines, which may be placed only "
                    "at a district or state, or not at all (lat/lng null)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Citizen reports with coordinates, for the field-reports map layer.

    Since Phase 2, `raw_reports` also holds Mastodon posts and news headlines,
    most of them placed only at a district's or state's centroid, or not at
    all. They are left out unless `include_feeds=true`, so the map layer keeps
    drawing exactly what it drew before: reports people filed, at the point
    they filed them. Each item says its `place_precision`.

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
    conditions = ["r.created_at >= NOW() - make_interval(hours => CAST(:hours AS int))"]
    if not include_feeds:
        conditions.append("COALESCE(r.place_precision, 'gps') = 'gps'")
    if unfused_only:
        conditions.append("r.event_id IS NULL")
        conditions.append("r.duplicate_of IS NULL")

    # The event's code comes along so the Field Reports page can say which
    # event a report joined. The docket does not: it is the citizen's
    # credential for GET /track, and this list is open.
    query = text(f"""
        SELECT r.id, r.source_type, r.raw_text, r.latitude, r.longitude,
               r.district, r.state, r.created_at, r.event_id, r.duplicate_of, r.analysis,
               e.event_code, r.observed_at, r.credibility_score,
               COALESCE(r.place_precision, 'gps'), r.platform
        FROM raw_reports r
        LEFT JOIN verified_events e ON e.id = r.event_id
        WHERE {" AND ".join(conditions)}
        ORDER BY r.created_at DESC
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
                "event_id": str(r[8]) if r[8] else None,
                "event_code": r[11],
                "observed_at": r[12].isoformat() if r[12] else None,
                "credibility_score": r[13],
                "place_precision": r[14],
                "platform": r[15],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"Database query failed in list_recent_reports: {e}")
        db_error = e

    # No fallback payload: an empty field-reports layer is an honest map, and a
    # fabricated citizen report is the one thing this console must never draw.
    return empty_or_503("GET /api/reports/recent", list, db_error)


@router.get("/track/{docket}")
async def track_report(docket: str, db: AsyncSession = Depends(get_db)):
    """
    Where a report is now, for the citizen holding its docket.

    Open, like /submit: the docket is the credential, and anyone holding one
    can call this. So it answers only what that person is entitled to know —
    whether the report was received, processed, suppressed as a duplicate, or
    joined an event, and that event's code and decision — and never the text,
    the coordinates or anything about who sent it. The place is the district
    and state, no finer.

    Typing slips are forgiven (case, spaces, hyphens, O/I/L for 0/1/1). A
    docket that cannot exist is the same 404 as one that does not, so the
    answer never helps anyone guess.
    """
    canonical = normalise_docket(docket)
    if canonical is None:
        raise HTTPException(status_code=404, detail="No report with that docket")

    try:
        row = (
            await db.execute(
                text("""
                    SELECT r.docket, r.created_at, r.duplicate_of, r.event_id,
                           r.processed_at, r.district, r.state,
                           e.event_code, CAST(e.review_status AS text)
                    FROM raw_reports r
                    LEFT JOIN verified_events e ON e.id = r.event_id
                    WHERE r.docket = :docket
                """),
                {"docket": canonical},
            )
        ).fetchone()
    except Exception as e:
        # No demo payload: an invented status for a real citizen's report is
        # the one answer this route must never give.
        logger.warning(f"Database query failed in track_report: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    if row is None:
        raise HTTPException(status_code=404, detail="No report with that docket")

    (found, received_at, duplicate_of, event_id, processed_at,
     district, state, event_code, review_status) = row
    return {
        "docket": found,
        "received_at": received_at.isoformat() if received_at else None,
        "status": docket_status(duplicate_of, event_id, review_status, processed_at),
        "event_code": event_code,
        "review_status": review_status,
        "district": district,
        "state": state,
    }
