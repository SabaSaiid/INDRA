"""
INDRA Platform — Audit ledger API
GET /api/audit/recent — the newest ledger rows, and whether the whole chain verifies

The ledger was only readable one event at a time (GET /api/events/{id}/provenance)
or one operator at a time (GET /api/profile/activity). The admin console needs
the platform-wide view, and it used to fill that space with an invented audit
trail; this route serves the real ledger.

Gated like provenance (ANALYST, COMMANDER, ADMIN): the rows carry operator ids
and the reasons operators gave.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TokenData, require_roles
from app.services import audit

logger = logging.getLogger("indra.api.audit")
router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/recent")
async def recent_audit_rows(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(require_roles("ANALYST", "COMMANDER", "ADMIN")),
):
    """
    The newest `limit` ledger rows, newest first, and a verification of the
    whole chain from genesis — not just the rows returned, because a break
    anywhere is what the chain exists to reveal.

    `chain` is `{valid, checked, broken_at_seq}` exactly as provenance reports
    it. The known limit applies (BUG-010): deleting the newest rows leaves a
    shorter chain that still verifies.
    """
    try:
        rows = await audit.fetch_rows(db)
    except Exception as e:
        logger.warning(f"audit ledger read failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    chain = audit.verify_rows(rows)
    newest = list(reversed(rows[-limit:]))
    return {
        "chain": chain,
        "total": len(rows),
        "rows": [
            {
                "seq": r["seq"],
                "action_taken": r["action_taken"],
                "operator_id": r["operator_id"],
                "event_id": r["event_id"],
                "reason": r["reason"],
                "logged_at": r["logged_at"].isoformat() if r["logged_at"] else None,
                "sha256_hash": r["sha256_hash"],
            }
            for r in newest
        ],
    }
