"""
INDRA Platform — Dashboard Summary API
GET /api/dashboard/summary
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.empty import empty_or_503

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# A working stack with nothing in it yet. Zeroes are the truthful answer to "how
# many reports are there" on a freshly started database, and the dashboard renders
# them fine; inventing 1,248 does not become acceptable just because the database
# answered.
EMPTY_KPIS = {
    "total_reports": 0,
    "total_reports_delta_pct": 0.0,
    "verified_events": 0,
    "verified_events_delta_pct": 0.0,
    "critical_events": 0,
    "critical_events_delta_pct": 0.0,
    "citizen_reports": 0,
    "citizen_reports_delta_pct": 0.0,
    "awaiting_review": 0,
    "active_alerts": 0,
}


@router.get("/summary")
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """
    Returns KPI summary with delta percentages vs. the prior 24h window.

    Response: {
      total_reports, total_reports_delta_pct,
      verified_events, verified_events_delta_pct,
      critical_events, critical_events_delta_pct,
      citizen_reports, citizen_reports_delta_pct,
      awaiting_review, active_alerts
    }

    `verified_events` counts only AUTO_PUBLISHED and HUMAN_APPROVED. Events
    the pipeline quarantined or escalated are counted separately as
    `awaiting_review`, so neither number has to stand in for the other.
    `active_alerts` is unexpired CAP warnings from the SACHET feed.
    """
    query = text("""
        WITH
        current_window AS (
            SELECT
                COUNT(*) AS total_reports,
                COUNT(*) FILTER (WHERE source_type = 'CITIZEN_APP') AS citizen_reports
            FROM raw_reports
        ),
        last_24h AS (
            SELECT
                COUNT(*) AS total_reports_24h,
                COUNT(*) FILTER (WHERE source_type = 'CITIZEN_APP') AS citizen_reports_24h
            FROM raw_reports
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        ),
        prev_24h AS (
            SELECT
                COUNT(*) AS total_reports_prev,
                COUNT(*) FILTER (WHERE source_type = 'CITIZEN_APP') AS citizen_reports_prev
            FROM raw_reports
            WHERE created_at >= NOW() - INTERVAL '48 hours'
              AND created_at < NOW() - INTERVAL '24 hours'
        ),
        -- "Verified" means the system or a human actually verified it.
        -- This used to be `review_status != 'REJECTED'`, which counted
        -- QUARANTINED and PENDING_HUMAN_REVIEW as verified: an event that
        -- scored 0.4984, was quarantined, was assigned the quadrant "Noise",
        -- and was still advertised as a Verified Event
        -- (BUG-034). Everything not rejected is still counted, but under a
        -- name that says what it is.
        events_current AS (
            SELECT
                COUNT(*) FILTER (
                    WHERE review_status IN ('AUTO_PUBLISHED', 'HUMAN_APPROVED')
                ) AS verified_events,
                COUNT(*) FILTER (
                    WHERE review_status IN ('PENDING_HUMAN_REVIEW', 'QUARANTINED')
                ) AS awaiting_review,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_events
            FROM verified_events
            WHERE review_status != 'REJECTED'
        ),
        -- Live CAP warnings from SACHET (CWC, IMD, state SDMAs) that have not
        -- expired. 112 of these were being collected and shown on no console
        -- surface an officer looks at (BUG-037).
        alerts_current AS (
            SELECT COUNT(*) AS active_alerts
            FROM agency_alerts
            WHERE expires_at IS NULL OR expires_at > NOW()
        ),
        events_24h AS (
            SELECT
                COUNT(*) FILTER (
                    WHERE review_status IN ('AUTO_PUBLISHED', 'HUMAN_APPROVED')
                ) AS verified_events_24h,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_events_24h
            FROM verified_events
            WHERE verified_at >= NOW() - INTERVAL '24 hours'
              AND review_status != 'REJECTED'
        ),
        events_prev AS (
            SELECT
                COUNT(*) FILTER (
                    WHERE review_status IN ('AUTO_PUBLISHED', 'HUMAN_APPROVED')
                ) AS verified_events_prev,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_events_prev
            FROM verified_events
            WHERE verified_at >= NOW() - INTERVAL '48 hours'
              AND verified_at < NOW() - INTERVAL '24 hours'
              AND review_status != 'REJECTED'
        )
        SELECT
            cw.total_reports,
            l24.total_reports_24h,
            p24.total_reports_prev,
            cw.citizen_reports,
            l24.citizen_reports_24h,
            p24.citizen_reports_prev,
            ec.verified_events,
            e24.verified_events_24h,
            ep.verified_events_prev,
            ec.critical_events,
            e24.critical_events_24h,
            ep.critical_events_prev,
            ec.awaiting_review,
            ac.active_alerts
        FROM current_window cw,
             last_24h l24,
             prev_24h p24,
             events_current ec,
             events_24h e24,
             events_prev ep,
             alerts_current ac
    """)

    db_error = None
    try:
        result = await db.execute(query)
        row = result.fetchone()

        if row is not None:
            def delta_pct(current_24h: int, prev_24h: int) -> float:
                if prev_24h == 0:
                    return 100.0 if current_24h > 0 else 0.0
                return round(((current_24h - prev_24h) / prev_24h) * 100, 1)

            return {
                "total_reports": row[0],
                "total_reports_delta_pct": delta_pct(row[1], row[2]),
                "verified_events": row[6],
                "verified_events_delta_pct": delta_pct(row[7], row[8]),
                "critical_events": row[9],
                "critical_events_delta_pct": delta_pct(row[10], row[11]),
                "citizen_reports": row[3],
                "citizen_reports_delta_pct": delta_pct(row[4], row[5]),
                "awaiting_review": row[12],
                "active_alerts": row[13],
            }
    except Exception as e:
        db_error = e

    # Until 20 Sep this returned invented KPIs unconditionally — on a database
    # error *and* on an empty result (BUG-004). These are the headline numbers on
    # the dashboard, so it was the worst place for it.
    return empty_or_503("GET /api/dashboard/summary", lambda: dict(EMPTY_KPIS), db_error)


# ---------------------------------------------------------------------------
# Analytics sub-endpoints (added 29 Sep)
# ---------------------------------------------------------------------------

@router.get("/inundation-depth")
async def get_inundation_depth(db: AsyncSession = Depends(get_db)):
    """
    Returns the distribution of water inundation depths extracted from
    raw_reports.analysis->>'depth_cm'. Bucketed into 5 ranges for a bar chart.

    Only reports with a non-null depth_cm value and no duplicate_of pointer
    are counted (duplicates would inflate the lower buckets).

    Response: [{ bucket: str, count: int }]
    """
    query = text("""
        SELECT
            CASE
                WHEN (analysis->>'depth_cm')::numeric < 15   THEN '< 15 cm'
                WHEN (analysis->>'depth_cm')::numeric < 30   THEN '15 – 30 cm'
                WHEN (analysis->>'depth_cm')::numeric < 60   THEN '30 – 60 cm'
                WHEN (analysis->>'depth_cm')::numeric < 120  THEN '60 – 120 cm'
                ELSE '> 120 cm'
            END AS bucket,
            CASE
                WHEN (analysis->>'depth_cm')::numeric < 15   THEN 1
                WHEN (analysis->>'depth_cm')::numeric < 30   THEN 2
                WHEN (analysis->>'depth_cm')::numeric < 60   THEN 3
                WHEN (analysis->>'depth_cm')::numeric < 120  THEN 4
                ELSE 5
            END AS sort_order,
            COUNT(*) AS count
        FROM raw_reports
        WHERE
            analysis IS NOT NULL
            AND analysis->>'depth_cm' IS NOT NULL
            AND duplicate_of IS NULL
            AND (analysis->>'depth_cm')::numeric >= 0
        GROUP BY 1, 2
        ORDER BY sort_order
    """)

    db_error = None
    try:
        result = await db.execute(query)
        rows = result.fetchall()
        if rows is not None:
            return [{"bucket": r[0], "count": int(r[2])} for r in rows]
    except Exception as e:
        db_error = e

    return empty_or_503("GET /api/dashboard/inundation-depth", list, db_error)


@router.get("/top-districts")
async def get_top_districts(db: AsyncSession = Depends(get_db)):
    """
    Top 10 districts by number of verified events (AUTO_PUBLISHED or
    HUMAN_APPROVED). Also returns a breakdown of severity so the table
    can show a "critical / high / moderate" split.

    Districts whose name is NULL are excluded — an unknown location is not
    useful in a ranking table.

    Response: [{
        district: str, state: str | null,
        total: int, critical: int, high: int, moderate: int, low: int
    }]
    """
    query = text("""
        SELECT
            district,
            state,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE severity::text = 'CRITICAL')  AS critical,
            COUNT(*) FILTER (WHERE severity::text = 'HIGH')      AS high,
            COUNT(*) FILTER (WHERE severity::text = 'MODERATE')  AS moderate,
            COUNT(*) FILTER (WHERE severity::text NOT IN ('CRITICAL','HIGH','MODERATE')) AS low
        FROM verified_events
        WHERE
            review_status IN ('AUTO_PUBLISHED', 'HUMAN_APPROVED')
            AND district IS NOT NULL
        GROUP BY district, state
        ORDER BY total DESC
        LIMIT 10
    """)

    db_error = None
    try:
        result = await db.execute(query)
        rows = result.fetchall()
        if rows is not None:
            return [
                {
                    "district": r[0],
                    "state": r[1],
                    "total": int(r[2]),
                    "critical": int(r[3]),
                    "high": int(r[4]),
                    "moderate": int(r[5]),
                    "low": int(r[6]),
                }
                for r in rows
            ]
    except Exception as e:
        db_error = e

    return empty_or_503("GET /api/dashboard/top-districts", list, db_error)


@router.get("/verification-breakdown")
async def get_verification_breakdown(db: AsyncSession = Depends(get_db)):
    """
    Confidence score distribution for all non-rejected verified events.
    Bucketed into 5 equal ranges so the frontend can draw a bar chart.
    Also returns per-bucket counts for AUTO_PUBLISHED vs HUMAN_APPROVED
    so the stacked variant can be drawn.

    Response: [{
        bucket: str, count: int, auto_published: int, human_approved: int
    }]
    """
    query = text("""
        SELECT
            CASE
                WHEN confidence_score < 0.2 THEN '0.0 – 0.2'
                WHEN confidence_score < 0.4 THEN '0.2 – 0.4'
                WHEN confidence_score < 0.6 THEN '0.4 – 0.6'
                WHEN confidence_score < 0.8 THEN '0.6 – 0.8'
                ELSE '0.8 – 1.0'
            END AS bucket,
            COUNT(*) AS count,
            COUNT(*) FILTER (WHERE review_status = 'AUTO_PUBLISHED')  AS auto_published,
            COUNT(*) FILTER (WHERE review_status = 'HUMAN_APPROVED')  AS human_approved
        FROM verified_events
        WHERE review_status != 'REJECTED'
        GROUP BY 1
        ORDER BY MIN(confidence_score)
    """)

    db_error = None
    try:
        result = await db.execute(query)
        rows = result.fetchall()
        if rows is not None:
            return [
                {
                    "bucket": r[0],
                    "count": int(r[1]),
                    "auto_published": int(r[2]),
                    "human_approved": int(r[3]),
                }
                for r in rows
            ]
    except Exception as e:
        db_error = e

    return empty_or_503("GET /api/dashboard/verification-breakdown", list, db_error)
