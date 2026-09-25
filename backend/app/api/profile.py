"""
INDRA Platform — User Profile & Operator Identity API
GET /api/profile/me — the signed-in operator's profile, duty status and active team
PATCH /api/profile/me — update personal info, callsign, bio, duty status
GET /api/profile/activity?user= — one operator's audit-ledger actions
GET /api/profile/operators — personnel roster
"""

import logging
import uuid
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TokenData, get_current_operator
from app.models.enums import DutyStatus

logger = logging.getLogger("indra.api.profile")

router = APIRouter(prefix="/api/profile", tags=["User Profile"])


# ── Schemas ───────────────────────────────────────────────────────────────────
class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    callsign: Optional[str] = None
    agency: Optional[str] = None
    badge_number: Optional[str] = None
    bio: Optional[str] = None
    duty_status: Optional[DutyStatus] = None  # ON_DUTY, STANDBY, DEPLOYED, OFF_DUTY
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    team_code: Optional[str] = None
    team_role: Optional[str] = None

    # Accept any case, as the old str field did; an unknown status is a 422
    # instead of an enum error inside the UPDATE.
    @field_validator("duty_status", mode="before")
    @classmethod
    def _upper(cls, value):
        return value.upper() if isinstance(value, str) else value


# ── Operator statistics, computed ────────────────────────────────────────────
#
# Accounts are the rows of user_profiles (migration 0008; they sign in against
# its password_hash since 0019). Statistics are counted from the audit ledger,
# never invented: an operator who has reviewed nothing shows zeros.

STATS_SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE action_taken IN ('HUMAN_APPROVE', 'HUMAN_REJECT'))   AS triaged,
      count(*)                                                                    AS audits
    FROM audit_logs
    WHERE operator_id = :operator_id
    """
)


async def _operator_stats(db: AsyncSession, operator_id: Optional[str]) -> dict:
    """
    Real counts from the audit ledger for one operator.

    `accuracy_rate` is absent on purpose. Nothing in INDRA computes whether a
    reviewer's decision was later found correct, so any number here would be
    invented — the same rule that keeps `station_readings.anomaly_score` NULL.
    """
    if not operator_id:
        return {"verified_events_triaged": 0, "audits_logged": 0, "accuracy_rate": None}
    try:
        row = (await db.execute(STATS_SQL, {"operator_id": operator_id})).mappings().first()
    except Exception:
        return {"verified_events_triaged": 0, "audits_logged": 0, "accuracy_rate": None}
    return {
        "verified_events_triaged": int(row["triaged"] or 0) if row else 0,
        "audits_logged": int(row["audits"] or 0) if row else 0,
        "accuracy_rate": None,
    }


PROFILE_SQL = text(
    """
    SELECT
        p.id, p.username, p.full_name, p.email, p.phone,
        p.role, p.agency, p.operator_id, p.badge_number, p.callsign,
        p.team_id, p.team_role, p.duty_status, p.avatar_url, p.bio,
        p.last_active_at, p.created_at,
        t.name AS team_name, t.team_code AS team_code
    FROM user_profiles p
    LEFT JOIN teams t ON p.team_id = t.id
    WHERE p.username = :uname
    """
)


async def _load_profile(db: AsyncSession, username: str) -> dict:
    """
    One operator's profile, team and ledger statistics.

    404 when user_profiles has no row for them: an identity the database does
    not know about is not an identity. 503 when the database cannot answer.
    """
    try:
        row = (await db.execute(PROFILE_SQL, {"uname": username})).mappings().first()
    except Exception as e:
        logger.warning(f"profile/me lookup failed for {username!r}: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No operator profile for {username!r}",
        )

    data = dict(row)
    data["id"] = str(data["id"])
    if data["team_id"]:
        data["team_id"] = str(data["team_id"])
    data["avatar_initials"] = "".join(part[0] for part in data["full_name"].split()[:2]).upper()
    data.update(await _operator_stats(db, data.get("operator_id")))
    data["recent_activities"] = await _recent_activity(db, data.get("operator_id"))
    return data


@router.get("/me")
async def get_current_user_profile(
    operator: TokenData = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    The signed-in operator's profile. Requires a token.

    The profile is the token subject's and nobody else's: no token, or an
    invalid or expired one, is a 401, never somebody's profile by default.
    """
    return await _load_profile(db, operator.sub)


@router.patch("/me")
async def update_profile(
    update_data: ProfileUpdate,
    operator: TokenData = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the calling operator's own profile. Requires a token.

    The profile edited is the token's subject and nothing else (BUG-009). A
    failed UPDATE is a 503, never a 200 with the edit shown as saved.
    """
    username = operator.sub

    set_clauses = []
    params = {"uname": username}
    for field in ("full_name", "email", "phone", "callsign", "agency", "badge_number", "bio", "team_role"):
        value = getattr(update_data, field)
        if value is not None:
            set_clauses.append(f"{field} = :{field}")
            params[field] = value
    if update_data.duty_status is not None:
        set_clauses.append("duty_status = :duty_status")
        params["duty_status"] = update_data.duty_status.value

    if set_clauses:
        try:
            sql = f"UPDATE user_profiles SET {', '.join(set_clauses)}, last_active_at = NOW() WHERE username = :uname"
            await db.execute(text(sql), params)
            await db.commit()
        except Exception as e:
            logger.error(f"profile update failed for {username!r}: {type(e).__name__}: {e}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )

    # Read back from the database, so the answer is what was written.
    return await _load_profile(db, username)


ACTIVITY_SQL = text(
    """
    SELECT seq, action_taken, reason, details, logged_at, event_id
    FROM audit_logs
    WHERE operator_id = :operator_id
    ORDER BY logged_at DESC
    LIMIT :limit
    """
)


async def _recent_activity(db: AsyncSession, operator_id: Optional[str], limit: int = 20) -> List[dict]:
    """
    The operator's real actions, read from the hash-chained audit ledger.

    This replaces a hardcoded list of invented "tactical actions". The ledger is
    the right source precisely because it is the record the platform already
    treats as authoritative: every HUMAN_APPROVE, HUMAN_REJECT and
    MANUAL_OVERRIDE is written there by the review endpoint, hash-chained to its
    predecessor. An empty list means this operator has reviewed nothing yet,
    which is true of every operator on a fresh stack.
    """
    if not operator_id:
        return []
    try:
        rows = (
            await db.execute(ACTIVITY_SQL, {"operator_id": operator_id, "limit": limit})
        ).mappings().all()
    except Exception as e:
        logger.warning(f"activity lookup failed for {operator_id!r}: {type(e).__name__}: {e}")
        return []

    return [
        {
            "id": str(r["seq"]),
            "action": r["action_taken"],
            "target": str(r["event_id"]) if r["event_id"] else "—",
            "reason": r["reason"],
            "timestamp": r["logged_at"].isoformat() if r["logged_at"] else None,
        }
        for r in rows
    ]


@router.get("/activity")
async def get_operator_activity(
    user: str = Query(..., description="Username whose actions to list"),
    db: AsyncSession = Depends(get_db),
):
    """The operator's audit-ledger actions. Empty until they review something."""
    username = user
    try:
        row = (
            await db.execute(
                text("SELECT operator_id FROM user_profiles WHERE username = :u"),
                {"u": username},
            )
        ).mappings().first()
    except Exception as e:
        logger.warning(f"activity profile lookup failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No operator profile for {username!r}"
        )
    return await _recent_activity(db, row["operator_id"])


@router.get("/operators")
async def list_operators(
    db: AsyncSession = Depends(get_db),
):
    """List operator personnel for duty roster."""
    try:
        res = await db.execute(
            text("""
                SELECT id, username, full_name, email, phone, role, agency, operator_id, badge_number, callsign, duty_status
                FROM user_profiles
                ORDER BY role ASC, full_name ASC
            """)
        )
        # An empty roster is a real answer, not a reason to invent personnel.
        return [dict(r) for r in res.mappings().all()]
    except Exception as e:
        logger.warning(f"operator roster lookup failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
        )
