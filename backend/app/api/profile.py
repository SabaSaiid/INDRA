"""
INDRA Platform — User Profile & Operator Identity API
GET /api/profile/me — operator profile with duty status and active team
PATCH /api/profile/me — update personal info, callsign, bio, duty status
GET /api/profile/operators — personnel roster
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import oauth2_scheme, verify_token

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


# ── Demo Profiles Fallback Store ──────────────────────────────────────────────
DEMO_PROFILES = {
    "commander": {
        "id": "22222222-2222-2222-2222-222222222201",
        "username": "commander",
        "full_name": "Commandant Rajesh K. Verma",
        "email": "rajesh.verma@sih-indra.gov.in",
        "phone": "+91 94311 02847",
        "role": "COMMANDER",
        "agency": "SDMA_BIHAR",
        "operator_id": "OP-CMD-001",
        "badge_number": "NDRF-PAT-091",
        "callsign": "NDRF-CMD-09",
        "team_name": "NDRF 9th Battalion — Flood Rescue Unit",
        "team_code": "TEAM-NDRF-09",
        "team_role": "Incident Commander",
        "duty_status": "ON_DUTY",
        "avatar_initials": "RV",
        "bio": "National Disaster Response Force commander leading urban inundation and river flood operations across Eastern India.",
        "verified_events_triaged": 24,
        "audits_logged": 19,
        "accuracy_rate": 96.8,
        "last_active_at": "2026-09-14T20:45:00Z",
    },
    "admin": {
        "id": "22222222-2222-2222-2222-222222222202",
        "username": "admin",
        "full_name": "Saba Saeed",
        "email": "sabasaid826@gmail.com",
        "phone": "+91 84347 08060",
        "role": "ADMIN",
        "agency": "NDMA",
        "operator_id": "OP-ADMIN-001",
        "badge_number": "NDMA-DIR-001",
        "callsign": "NDMA-DIR-01",
        "team_name": "NDMA National Aerial Reconnaissance Wing",
        "team_code": "TEAM-NDMA-NAT01",
        "team_role": "Platform Administrator & Team Lead",
        "duty_status": "ON_DUTY",
        "avatar_initials": "SS",
        "bio": "Lead System Architect and NDMA Platform Administrator managing the INDRA national big data weather platform.",
        "verified_events_triaged": 37,
        "audits_logged": 42,
        "accuracy_rate": 99.1,
        "last_active_at": "2026-09-15T11:00:00Z",
    },
    "analyst": {
        "id": "22222222-2222-2222-2222-222222222203",
        "username": "analyst",
        "full_name": "Dr. Vikram Sethi",
        "email": "vikram.sethi@imd.gov.in",
        "phone": "+91 98710 44210",
        "role": "ANALYST",
        "agency": "IMD",
        "operator_id": "OP-ANL-001",
        "badge_number": "IMD-MET-552",
        "callsign": "RADAR-HAWK",
        "team_name": "IMD Severe Weather Nowcasting Cell",
        "team_code": "TEAM-IMD-NOW01",
        "team_role": "Lead Meteorological Analyst",
        "duty_status": "ON_DUTY",
        "avatar_initials": "VS",
        "bio": "IMD Nowcasting specialist focusing on Doppler weather radar echoes and cloudburst probability synthesis.",
        "verified_events_triaged": 31,
        "audits_logged": 28,
        "accuracy_rate": 94.5,
        "last_active_at": "2026-09-14T20:30:00Z",
    },
    "citizen": {
        "id": "22222222-2222-2222-2222-222222222204",
        "username": "citizen",
        "full_name": "Meenal Sinha",
        "email": "meenal.sinha09@gmail.com",
        "phone": "+91 93541 18582",
        "role": "CITIZEN",
        "agency": "PUBLIC",
        "operator_id": "OP-CIT-001",
        "badge_number": "CITIZEN-REP-06",
        "callsign": "OBSERVER-MEENAL",
        "team_name": "Community Weather Watch Volunteers",
        "team_code": "TEAM-COMM-VOL",
        "team_role": "Volunteer Reporter",
        "duty_status": "ON_DUTY",
        "avatar_initials": "MS",
        "bio": "Registered citizen weather observer and ground-truth volunteer contributing geotagged ground reports and flooding photos.",
        "verified_events_triaged": 5,
        "audits_logged": 0,
        "accuracy_rate": 92.4,
        "last_active_at": "2026-09-15T10:45:00Z",
    },
}

DEMO_ACTIVITIES = {
    "commander": [
        {"id": "act-c-1", "action": "Dispatched Quick Response Taskforce", "target": "WX-EV-28231827-A (Patna Urban Flood)", "time": "18 mins ago", "status": "DISPATCHED"},
        {"id": "act-c-2", "action": "High-Confidence Triage Signed", "target": "WX-EV-77291044-B (Mumbai Coastal Surge)", "time": "2 hours ago", "status": "VERIFIED"},
        {"id": "act-c-3", "action": "Manual Override Confirmation", "target": "SIG-10928 (River Gauge Anomaly)", "time": "5 hours ago", "status": "LOGGED"},
        {"id": "act-c-4", "action": "Shift Roll-Call & Tactical Inspection", "target": "Patna Regional Command Base", "time": "11 hours ago", "status": "ON DUTY"},
        {"id": "act-c-5", "action": "Evacuation Corridor Authorized", "target": "Sector 4 Embankment Zone", "time": "Yesterday", "status": "COMPLETED"},
    ],
    "analyst": [
        {"id": "act-a-1", "action": "Doppler Radar Echo Cross-Validation", "target": "DWR-PAT-02 (Cloudburst Echo Cluster)", "time": "12 mins ago", "status": "VERIFIED"},
        {"id": "act-a-2", "action": "Bayesian Prior Recalibration", "target": "AWS-BIH-104 (Rainfall Gauge Drift)", "time": "1 hour ago", "status": "COMPLETED"},
        {"id": "act-a-3", "action": "False Alarm Signal Quarantined", "target": "SIG-99120 (Acoustic Glitch Triage)", "time": "4 hours ago", "status": "QUARANTINED"},
        {"id": "act-a-4", "action": "Flash Flood Guidance Synthesis", "target": "South Bihar River Basins", "time": "8 hours ago", "status": "LOGGED"},
        {"id": "act-a-5", "action": "INSAT-3DR Rapid Scan Overlay", "target": "Eastern Himalayan Frontal Cloud", "time": "Yesterday", "status": "COMPLETED"},
    ],
    "admin": [
        {"id": "act-ad-1", "action": "Platform Security Audit & Integrity Check", "target": "Ledger Block #84920 (SHA-256 Validated)", "time": "8 mins ago", "status": "VERIFIED"},
        {"id": "act-ad-2", "action": "Taskforce Deployment Roster Reallocated", "target": "TEAM-NDRF-09 & TEAM-SDRF-02", "time": "45 mins ago", "status": "COMPLETED"},
        {"id": "act-ad-3", "action": "Activated Pan-India Multi-Hazard Gateway", "target": "NDMA Central Node 01", "time": "3 hours ago", "status": "ON DUTY"},
        {"id": "act-ad-4", "action": "RBAC Policy Matrix Synchronized", "target": "Field Responder Clearance Tier 2", "time": "6 hours ago", "status": "LOGGED"},
        {"id": "act-ad-5", "action": "PostgreSQL TimeScale Hypertables Reindexed", "target": "Station Readings Cluster (120M Rows)", "time": "Yesterday", "status": "COMPLETED"},
    ],
    "citizen": [
        {"id": "act-ct-1", "action": "Geotagged Waterlogging Report Submitted", "target": "Kankarbagh Main Road, Patna (0.8m Depth)", "time": "25 mins ago", "status": "SUBMITTED"},
        {"id": "act-ct-2", "action": "Local Drain Overflow Alert Logged", "target": "Ward 12 Municipal Inundation", "time": "3 hours ago", "status": "VERIFIED"},
        {"id": "act-ct-3", "action": "Community Warning Upvoted", "target": "WX-EV-28231827-A Flash Flood Warning", "time": "5 hours ago", "status": "COMPLETED"},
        {"id": "act-ct-4", "action": "Ground-Truth Station Reading Confirmed", "target": "Neighborhood Rain Gauge RG-04", "time": "10 hours ago", "status": "LOGGED"},
        {"id": "act-ct-5", "action": "Evacuation Route Feedback Shared", "target": "Boring Road Relief Shelter Path", "time": "Yesterday", "status": "SUBMITTED"},
    ],
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
            role_defaults = DEMO_PROFILES.get(username, DEMO_PROFILES["commander"])
            data["verified_events_triaged"] = role_defaults.get("verified_events_triaged", 24)
            data["audits_logged"] = role_defaults.get("audits_logged", 19)
            data["accuracy_rate"] = role_defaults.get("accuracy_rate", 96.8)
            data["recent_activities"] = DEMO_ACTIVITIES.get(username, DEMO_ACTIVITIES["commander"])
            return data
    except Exception:
        pass

    # Fallback to demo profile
    profile = DEMO_PROFILES.get(username, DEMO_PROFILES["commander"]).copy()
    profile["recent_activities"] = DEMO_ACTIVITIES.get(username, DEMO_ACTIVITIES["commander"])
    return profile


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

    # Update demo in-memory fallback
    if username in DEMO_PROFILES:
        target = DEMO_PROFILES[username]
        if update_data.full_name is not None:
            target["full_name"] = update_data.full_name
            target["avatar_initials"] = "".join(part[0] for part in update_data.full_name.split()[:2]).upper()
        if update_data.email is not None:
            target["email"] = update_data.email
        if update_data.phone is not None:
            target["phone"] = update_data.phone
        if update_data.callsign is not None:
            target["callsign"] = update_data.callsign
        if update_data.agency is not None:
            target["agency"] = update_data.agency
        if update_data.badge_number is not None:
            target["badge_number"] = update_data.badge_number
        if update_data.bio is not None:
            target["bio"] = update_data.bio
        if update_data.duty_status is not None:
            target["duty_status"] = update_data.duty_status.upper()
        if update_data.team_name is not None:
            target["team_name"] = update_data.team_name
        if update_data.team_code is not None:
            target["team_code"] = update_data.team_code
        if update_data.team_role is not None:
            target["team_role"] = update_data.team_role
        return target

    return {"status": "success", "username": username}


@router.get("/activity")
async def get_operator_activity(
    user: Optional[str] = Query("commander"),
):
    """Return immutable tactical action ledger for specified operator persona."""
    username = user or "commander"
    return DEMO_ACTIVITIES.get(username, DEMO_ACTIVITIES["commander"])


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
        rows = res.mappings().all()
        if rows:
            return [dict(r) for r in rows]
    except Exception:
        pass

    return list(DEMO_PROFILES.values())
