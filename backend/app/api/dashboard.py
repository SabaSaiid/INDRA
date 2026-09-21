"""
INDRA Platform — Dashboard Summary API
GET /api/dashboard/summary
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.demo import demo_fallback

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# Served only when DEMO_MODE is true, and logged as demo data every time.
DEMO_KPIS = {
    "total_reports": 1248,
    "total_reports_delta_pct": 12.0,
    "verified_events": 37,
    "verified_events_delta_pct": 8.0,
    "critical_events": 5,
    "critical_events_delta_pct": -2.0,
    "citizen_reports": 8421,
    "citizen_reports_delta_pct": 15.0,
    "awaiting_review": 14,
    "active_alerts": 23,
}

# A working stack with nothing in it yet. Zeroes are the truthful answer to "how
# many reports are there" on a freshly started database, and the dashboard renders
# them fine; inventing 1,248 does not become acceptable just because the database
# answered.
EMPTY_KPIS = {key: 0 if isinstance(value, int) else 0.0 for key, value in DEMO_KPIS.items()}


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
        -- QUARANTINED and PENDING_HUMAN_REVIEW as verified: the one event in
        -- the demo database scored 0.4984, was quarantined, was assigned the
        -- quadrant "Noise", and was still advertised as a Verified Event
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

    # Until 20 Sep this returned the DEMO_KPIS below unconditionally — on a
    # database error *and* on an empty result, whatever DEMO_MODE said. It was the
    # one read endpoint that escaped the Day 2 demo gate, and the only place left
    # in the API where a number the database never produced could be served as
    # though it had. These are the headline KPIs on the dashboard, so it was also
    # the worst place for it.
    return demo_fallback(
        "GET /api/dashboard/summary",
        demo=lambda: dict(DEMO_KPIS),
        empty=lambda: dict(EMPTY_KPIS),
        error=db_error,
    )
