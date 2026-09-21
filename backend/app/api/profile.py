"""
INDRA Platform — User Profile & Operator Identity API
GET /api/profile/me — operator profile with duty status and active team
PATCH /api/profile/me — update personal info, callsign, bio, duty status
GET /api/profile/operators — personnel roster
"""

import logging
import uuid
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import oauth2_scheme, verify_token

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
    duty_status: Optional[str] = None  # ON_DUTY, STANDBY, DEPLOYED, OFF_DUTY
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    team_code: Optional[str] = None
    team_role: Optional[str] = None


# ── Operator statistics, computed ────────────────────────────────────────────
#
# DEMO_PROFILES and DEMO_ACTIVITIES used to live here: four invented operators
# with invented statistics. They were returned whenever `user_profiles` had no
# row — which was always, because nothing ever seeded it — and, worse, their
# numbers were pasted over a real row when one did exist:
#
#     data["verified_events_triaged"] = role_defaults.get(..., 24)
#     data["accuracy_rate"] = role_defaults.get(..., 96.8)
#
# So the operator card advertised a 96.8 % accuracy rate that no code computes.
# Migration 0008 seeds the four accounts `core/security.py` genuinely
# authenticates, and the statistics below are counted from the audit ledger.

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


@router.get("/me")
async def get_current_user_profile(
    token: Optional[str] = Depends(oauth2_scheme),
    user: Optional[str] = Query(None, description="Directly query a demo username (e.g. commander, admin, analyst)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get profile of the active operator.
    Resolves identity from Bearer token if provided, otherwise falls back to query param or 'commander'.
    """
    username = user or "commander"
    if token:
        try:
            token_data = verify_token(token)
            if token_data.sub:
                username = token_data.sub
        except Exception:
            pass

    # Try database first
    try:
        res = await db.execute(
            text("""
                SELECT
                    p.id, p.username, p.full_name, p.email, p.phone,
                    p.role, p.agency, p.operator_id, p.badge_number, p.callsign,
                    p.team_id, p.team_role, p.duty_status, p.avatar_url, p.bio,
                    p.last_active_at, p.created_at,
                    t.name AS team_name, t.team_code AS team_code
                FROM user_profiles p
                LEFT JOIN teams t ON p.team_id = t.id
                WHERE p.username = :uname
            """),
            {"uname": username},
        )
        row = res.mappings().first()
        if row:
            data = dict(row)
            data["id"] = str(data["id"])
            if data["team_id"]:
                data["team_id"] = str(data["team_id"])
            data["avatar_initials"] = "".join(part[0] for part in data["full_name"].split()[:2]).upper()
            data.update(await _operator_stats(db, data.get("operator_id")))
            data["recent_activities"] = await _recent_activity(db, data.get("operator_id"))
            return data
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"profile/me lookup failed for {username!r}: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    # No row. There is no invented operator to return: an identity the database
    # does not know about is not an identity.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No operator profile for {username!r}",
    )


@router.patch("/me")
async def update_profile(
    update_data: ProfileUpdate,
    token: Optional[str] = Depends(oauth2_scheme),
    user: Optional[str] = Query("commander"),
    db: AsyncSession = Depends(get_db),
):
    """Update active operator profile."""
    username = user or "commander"
    if token:
        try:
            token_data = verify_token(token)
            if token_data.sub:
                username = token_data.sub
        except Exception:
            pass

    # Update database if available
    try:
        set_clauses = []
        params = {"uname": username}
        if update_data.full_name is not None:
            set_clauses.append("full_name = :full_name")
            params["full_name"] = update_data.full_name
        if update_data.email is not None:
            set_clauses.append("email = :email")
            params["email"] = update_data.email
        if update_data.phone is not None:
            set_clauses.append("phone = :phone")
            params["phone"] = update_data.phone
        if update_data.callsign is not None:
            set_clauses.append("callsign = :callsign")
            params["callsign"] = update_data.callsign
        if update_data.agency is not None:
            set_clauses.append("agency = :agency")
            params["agency"] = update_data.agency
        if update_data.badge_number is not None:
            set_clauses.append("badge_number = :badge_number")
            params["badge_number"] = update_data.badge_number
        if update_data.bio is not None:
            set_clauses.append("bio = :bio")
            params["bio"] = update_data.bio
        if update_data.team_role is not None:
            set_clauses.append("team_role = :team_role")
            params["team_role"] = update_data.team_role
        if update_data.duty_status is not None:
            set_clauses.append("duty_status = :duty_status")
            params["duty_status"] = update_data.duty_status.upper()

        if set_clauses:
            sql = f"UPDATE user_profiles SET {', '.join(set_clauses)}, last_active_at = NOW() WHERE username = :uname"
            await db.execute(text(sql), params)
            await db.commit()
    except Exception:
        pass

    # No in-memory mirror. The previous version updated a DEMO_PROFILES dict and
    # returned it, so a failed UPDATE still answered 200 with the edit applied --
    # the operator saw their change saved when nothing had been written.
    return await get_current_user_profile(token=token, user=username, db=db)


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
    user: Optional[str] = Query("commander"),
    db: AsyncSession = Depends(get_db),
):
    """The operator's audit-ledger actions. Empty until they review something."""
    username = user or "commander"
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


# ── Operator Platform Preferences Store ───────────────────────────────────────
DEMO_PREFERENCES: dict = {}

@router.get("/preferences")
async def get_operator_preferences(
    user: Optional[str] = Query("commander"),
):
    """Retrieve saved mission preferences for operator."""
    username = user or "commander"
    return DEMO_PREFERENCES.get(username, {
        "mapProjection": "globe",
        "defaultBasemap": "satellite",
        "audioAlertsEnabled": True,
        "alertVolume": 0.75,
        "sirenPattern": "warble_fast",
        "tempUnit": "celsius",
        "windUnit": "kmh",
        "rainUnit": "mm",
        "coordFormat": "dd",
        "timezone": "ist",
        "themeMode": "dark",
        "uiDensity": "standard",
        "lowBandwidthDataSaver": False,
    })


@router.patch("/preferences")
async def update_operator_preferences(
    preferences: dict,
    user: Optional[str] = Query("commander"),
):
    """Update mission preferences for operator."""
    username = user or "commander"
    existing = DEMO_PREFERENCES.get(username, {})
    existing.update(preferences)
    DEMO_PREFERENCES[username] = existing
    return {"status": "success", "username": username, "preferences": existing}

