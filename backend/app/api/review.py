"""
INDRA Platform — The review queue (Phase 4 T7)

    GET /api/review/queue?tab=pending&limit=50&offset=0
    GET /api/review/queue?counts=true

What a commander should look at first, in tabs. Reading needs ANALYST or
above; claiming and deciding (POST /api/events/{id}/claim, PATCH …/review)
need COMMANDER or ADMIN.

| Tab           | Contents                                                          |
|---------------|-------------------------------------------------------------------|
| `pending`     | PENDING_HUMAN_REVIEW or QUARANTINED, never reviewed               |
| `contradicted`| verdict CONTRADICTED, never reviewed                              |
| `suspicious`  | at least one contributing report flagged as misleading (Phase 3)  |
| `high_impact` | severity HIGH or CRITICAL, never reviewed                         |
| `recent`      | created in the last 2 hours                                       |
| `claimed`     | someone holds an unexpired claim                                  |

"Never reviewed" means no commander has acted on it (no `human_review` in its
receipt). REJECTED events are in no tab: a queue is for work. `suspicious`
does not count `not_an_observation`, which marks a forecast, not a lie; Phase
5 adds the media flags.

**Order, published:** severity (CRITICAL first), then verdict (CORROBORATED,
then UNCONFIRMED, then CONTRADICTED: a corroborated severe event is the most
likely to be real and urgent), then age, oldest first.

`?counts=true` returns `{tab: n}` for every tab in one call.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import CLAIM_MINUTES, claim_view
from app.api.query_params import invalid as _invalid
from app.core.database import get_db
from app.core.security import TokenData, require_roles
from app.services import clock
from app.services.hazards import family_of, label_of

logger = logging.getLogger("indra.api.review")
router = APIRouter(prefix="/api/review", tags=["Review"])

RECENT_HOURS = 2

# Flags that make a report suspicious. `not_an_observation` is a forecast.
SUSPICIOUS_FLAGS = [
    "promotional", "past_event", "implausible_value", "exaggeration",
    "shouting", "forward_marker", "coordinated",
]

_NOT_REVIEWED = "verification_receipt->'human_review' IS NULL"
_NOT_REJECTED = "review_status <> 'REJECTED'"

TABS: Dict[str, str] = {
    "pending": (
        "CAST(review_status AS text) IN ('PENDING_HUMAN_REVIEW', 'QUARANTINED') "
        f"AND {_NOT_REVIEWED}"
    ),
    "contradicted": f"CAST(verdict AS text) = 'CONTRADICTED' AND {_NOT_REJECTED} AND {_NOT_REVIEWED}",
    "suspicious": f"""{_NOT_REJECTED} AND EXISTS (
        SELECT 1 FROM raw_reports r
        WHERE r.event_id = verified_events.id
          AND r.duplicate_of IS NULL
          AND COALESCE(r.flags, '{{}}'::text[]) && CAST(:suspicious_flags AS text[])
    )""",
    "high_impact": (
        f"CAST(severity AS text) IN ('HIGH', 'CRITICAL') AND {_NOT_REJECTED} AND {_NOT_REVIEWED}"
    ),
    "recent": f"{_NOT_REJECTED} AND verified_at >= CAST(:recent_since AS timestamptz)",
    "claimed": (
        f"{_NOT_REJECTED} AND claimed_by IS NOT NULL "
        "AND claimed_at > CAST(:claim_since AS timestamptz)"
    ),
}

ORDER_BY = """
    CASE CAST(severity AS text) WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                                WHEN 'MODERATE' THEN 2 ELSE 3 END,
    CASE CAST(verdict AS text) WHEN 'CORROBORATED' THEN 0 WHEN 'UNCONFIRMED' THEN 1
                               WHEN 'CONTRADICTED' THEN 2 ELSE 3 END,
    verified_at ASC,
    id ASC
"""
ORDER_RULE = "severity (critical first), then verdict (corroborated, unconfirmed, contradicted), then age (oldest first)"


def _params() -> Dict[str, Any]:
    now = clock.now()
    return {
        "suspicious_flags": SUSPICIOUS_FLAGS,
        "recent_since": now - timedelta(hours=RECENT_HOURS),
        "claim_since": now - timedelta(minutes=CLAIM_MINUTES),
    }


def _uses(sql: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Only the parameters this tab's SQL names."""
    return {k: v for k, v in params.items() if f":{k}" in sql}


def _item(row) -> Dict[str, Any]:
    now = clock.now()
    return {
        "id": str(row["id"]),
        "event_code": row["event_code"],
        "event_type": row["event_type"],
        "label": label_of(row["event_type"]),
        "family": family_of(row["event_type"]),
        "severity": row["severity"],
        "confidence_score": row["confidence_score"],
        "factor_coverage": row["factor_coverage"],
        "verdict": row["verdict"],
        "review_status": row["review_status"],
        "district": row["district"],
        "state": row["state"],
        "verified_at": row["verified_at"].isoformat() if row["verified_at"] else None,
        "age_minutes": (
            round((now - row["verified_at"]).total_seconds() / 60.0, 1) if row["verified_at"] else None
        ),
        "report_count": row["report_count"],
        "flagged_reports": row["flagged_reports"],
        "contradictions": row["contradictions"] or [],
        "claim": claim_view(row["claimed_by"], row["claimed_at"]),
    }


@router.get("/queue")
async def review_queue(
    tab: str = Query("pending", description="pending, contradicted, suspicious, high_impact, recent, claimed"),
    counts: bool = Query(False, description="true: {tab: n} for every tab instead of a page"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    operator: TokenData = Depends(require_roles("ANALYST", "COMMANDER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """The review queue. See the module docstring for the tabs and the order."""
    params = _params()
    try:
        if counts:
            out: Dict[str, int] = {}
            for name, where in TABS.items():
                n = (await db.execute(
                    text(f"SELECT count(*) FROM verified_events WHERE {where}"),
                    _uses(where, params),
                )).scalar()
                out[name] = int(n or 0)
            return out

        key = (tab or "").strip().lower()
        if key not in TABS:
            raise _invalid("tab", f"expected one of {list(TABS)}", tab)
        where = TABS[key]
        rows = (await db.execute(
            text(f"""
                SELECT id, event_code, CAST(event_type AS text) AS event_type,
                       CAST(severity AS text) AS severity, confidence_score,
                       CAST(verification_receipt->>'factor_coverage' AS double precision)
                           AS factor_coverage,
                       CAST(verdict AS text) AS verdict,
                       CAST(review_status AS text) AS review_status,
                       district, state, verified_at, claimed_by, claimed_at,
                       verification_receipt->'contradictions' AS contradictions,
                       (SELECT count(*) FROM raw_reports r
                        WHERE r.event_id = verified_events.id) AS report_count,
                       (SELECT count(*) FROM raw_reports r
                        WHERE r.event_id = verified_events.id AND r.duplicate_of IS NULL
                          AND COALESCE(r.flags, '{{}}'::text[])
                              && CAST(:suspicious_flags AS text[])) AS flagged_reports
                FROM verified_events
                WHERE {where}
                ORDER BY {ORDER_BY}
                LIMIT :limit OFFSET :offset
            """),
            {**_uses(where, params), "suspicious_flags": SUSPICIOUS_FLAGS,
             "limit": limit, "offset": offset},
        )).mappings().all()
        total = (await db.execute(
            text(f"SELECT count(*) FROM verified_events WHERE {where}"),
            _uses(where, params),
        )).scalar()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database query failed in review_queue: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {
        "tab": key,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "order": ORDER_RULE,
        "items": [_item(r) for r in rows],
    }
