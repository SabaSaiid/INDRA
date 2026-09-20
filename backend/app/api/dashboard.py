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
      citizen_reports, citizen_reports_delta_pct
    }
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
        events_current AS (
            SELECT
                COUNT(*) AS verified_events,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_events
            FROM verified_events
            WHERE review_status != 'REJECTED'
        ),
        events_24h AS (
            SELECT
                COUNT(*) AS verified_events_24h,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_events_24h
            FROM verified_events
            WHERE verified_at >= NOW() - INTERVAL '24 hours'
              AND review_status != 'REJECTED'
        ),
        events_prev AS (
            SELECT
                COUNT(*) AS verified_events_prev,
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
            ep.critical_events_prev
        FROM current_window cw,
             last_24h l24,
             prev_24h p24,
             events_current ec,
             events_24h e24,
             events_prev ep
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
