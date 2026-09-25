"""
INDRA Platform — Teams API
Operational Disaster Response Units (NDRF, SDRF, IMD, CWC) and Team Sixth Sense Showcase
"""

import logging
import uuid
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.empty import empty_or_503
from app.core.security import TokenData, require_roles
from app.models.enums import TeamAgency, TeamStatus

logger = logging.getLogger("indra.api.teams")

# Creating and dispatching a unit are operational decisions, so they carry the
# same gate as reviewing an event (BUG-009). An analyst reads; a commander acts.
_can_dispatch = require_roles("COMMANDER", "ADMIN")

router = APIRouter(prefix="/api/teams", tags=["Teams"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────
class TeamCreate(BaseModel):
    team_code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    agency: TeamAgency  # NDRF, SDRF, IMD, CWC, NDMA, MUNICIPAL
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=80)
    lead_name: str = Field(min_length=1, max_length=100)
    lead_phone: Optional[str] = Field(None, max_length=30)
    radio_callsign: Optional[str] = Field(None, max_length=40)
    specialization: Optional[str] = Field(None, max_length=200)
    status: TeamStatus = TeamStatus.AVAILABLE
    members_count: int = Field(12, ge=1, le=1000)

    # The enums are upper case; the old str fields upper-cased whatever came
    # in, so "ndrf" keeps working. An unknown agency is now a 422 rather than
    # a database error surfacing as a 500.
    @field_validator("agency", "status", mode="before")
    @classmethod
    def _upper(cls, value):
        return value.upper() if isinstance(value, str) else value


class TeamAssignRequest(BaseModel):
    event_id: Optional[str] = None  # None unassigns


# ── Hackathon Team Showcase Data ──────────────────────────────────────────────
SIXTH_SENSE_TEAM = {
    "team_name": "Sixth Sense",
    "problem_statement": "SIH26069 — National Weather Big Data Analytics Platform",
    "theme": "Disaster Management",
    "tagline": "From fragmented weather reports to verified, actionable weather events.",
    "institution": "Smart India Hackathon 2026",
    "members": [
        {
            "id": "ss-1",
            "name": "Saba Saeed",
            "role": "Team Lead & Full-Stack Architect",
            "specialty": "Next.js Command Center, Real-Time WebSockets & System Design",
            "bio": "Directs architecture and cross-service orchestration for the INDRA intelligence platform.",
            "avatar_initials": "SS",
            "github": "https://github.com/SabaSaiid",
            "badge": "LEAD ARCHITECT",
        },
        {
            "id": "ss-2",
            "name": "Pritam Singh",
            "role": "AI & Bayesian Engine Lead",
            "specialty": "Bayesian Probability Fusion, Anomaly Detection & Cross-Source Weighting",
            "bio": "Formulated the 3-phase evidence synthesis engine condensing 127 raw signals into verified confidence receipts.",
            "avatar_initials": "PS",
            "github": "https://github.com/SabaSaiid/INDRA",
            "badge": "FUSION SCIENTIST",
        },
        {
            "id": "ss-3",
            "name": "Aditya",
            "role": "Geospatial Systems Engineer",
            "specialty": "Uber H3 Spatial Hexagons, DBSCAN Spatio-Temporal Clustering & PostGIS",
            "bio": "Implemented dynamic ε-neighborhood spatial clustering and convex hull boundary polygon calculation.",
            "avatar_initials": "AD",
            "github": "https://github.com/SabaSaiid/INDRA",
            "badge": "SPATIAL ENGINEER",
        },
        {
            "id": "ss-4",
            "name": "Salman Khurshid",
            "role": "Data Pipeline Architect",
            "specialty": "Redpanda / Kafka Streaming, Async Workers & Sensor Ingestion",
            "bio": "Engineered high-throughput consumer pipelines processing citizen reports, AWS gauges, and social signals.",
            "avatar_initials": "SK",
            "github": "https://github.com/SabaSaiid/INDRA",
            "badge": "PIPELINE LEAD",
        },
        {
            "id": "ss-5",
            "name": "Pragati Sahu",
            "role": "NLP & Semantic Deduplication Lead",
            "specialty": "TF-IDF + Cosine Similarity, Multilingual Signal Deduplication & Spam Filtering",
            "bio": "Created the semantic similarity layer that clusters repetitive emergency reports within spatial windows.",
            "avatar_initials": "PS",
            "github": "https://github.com/SabaSaiid/INDRA",
            "badge": "NLP SPECIALIST",
        },
        {
            "id": "ss-6",
            "name": "Meenal Sinha",
            "role": "Citizen Intelligence & Cloud Security",
            "specialty": "Crowdsourced Ground Verification, OAuth2 RBAC & Immutable SHA-256 Audit Logs",
            "bio": "Leads citizen ground-truth verification workflows and tamper-proof cryptographic audit tracking.",
            "avatar_initials": "MS",
            "github": "https://github.com/SabaSaiid/INDRA",
            "badge": "INTELLIGENCE LEAD",
        },
    ],
}


@router.get("")
async def list_teams(
    agency: Optional[str] = Query(None, description="Filter by agency (NDRF, SDRF, IMD, CWC, NDMA, MUNICIPAL)"),
    status: Optional[str] = Query(None, description="Filter by status (AVAILABLE, DEPLOYED, STANDBY, OFF_DUTY)"),
    city: Optional[str] = Query(None, description="Filter by city name"),
    db: AsyncSession = Depends(get_db),
):
    """List all operational disaster response teams with assigned event details."""
    db_error = None
    try:
        query_sql = """
            SELECT
                t.id,
                t.team_code,
                t.name,
                t.agency,
                t.city,
                t.state,
                t.lead_name,
                t.lead_phone,
                t.radio_callsign,
                t.specialization,
                t.status,
                t.members_count,
                t.created_at,
                t.assigned_event_id,
                e.event_code AS assigned_event_code,
                e.event_type AS assigned_event_type,
                ST_Y(e.center_point) AS event_lat,
                ST_X(e.center_point) AS event_lng
            FROM teams t
            LEFT JOIN verified_events e ON t.assigned_event_id = e.id
            WHERE 1=1
        """
        params = {}
        if agency:
            query_sql += " AND t.agency = :agency"
            params["agency"] = agency.upper()
        if status:
            query_sql += " AND t.status = :status"
            params["status"] = status.upper()
        if city:
            query_sql += " AND LOWER(t.city) LIKE LOWER(:city)"
            params["city"] = f"%{city}%"

        query_sql += " ORDER BY t.status = 'DEPLOYED' DESC, t.name ASC"

        res = await db.execute(text(query_sql), params)
        rows = res.mappings().all()

        if rows:
            results = []
            for r in rows:
                results.append({
                    "id": str(r["id"]),
                    "team_code": r["team_code"],
                    "name": r["name"],
                    "agency": r["agency"],
                    "city": r["city"],
                    "state": r["state"],
                    "lead_name": r["lead_name"],
                    "lead_phone": r["lead_phone"],
                    "radio_callsign": r["radio_callsign"],
                    "specialization": r["specialization"],
                    "status": r["status"],
                    "members_count": r["members_count"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "assigned_event_id": str(r["assigned_event_id"]) if r["assigned_event_id"] else None,
                    "assigned_event_code": r["assigned_event_code"],
                    "assigned_event_type": r["assigned_event_type"],
                    "event_lat": r["event_lat"],
                    "event_lng": r["event_lng"],
                })
            return results
    except Exception as e:
        db_error = e

    return empty_or_503("GET /api/teams", list, db_error)


@router.get("/hackathon/sixth-sense")
async def get_hackathon_team():
    """Returns Team Sixth Sense SIH 2026 Developer Roster and Architecture Showcase."""
    return SIXTH_SENSE_TEAM


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full detail and member roster for a specific team."""
    db_error = None
    try:
        try:
            tid_uuid = uuid.UUID(team_id)
        except (ValueError, AttributeError):
            tid_uuid = None

        if tid_uuid:
            where_sql = "t.id = :tid"
            params = {"tid": tid_uuid}
        else:
            where_sql = "t.team_code = :tid"
            params = {"tid": team_id}

        team_res = await db.execute(
            text(f"""
                SELECT
                    t.id, t.team_code, t.name, t.agency, t.city, t.state,
                    t.lead_name, t.lead_phone, t.radio_callsign, t.specialization,
                    t.status, t.members_count, t.created_at, t.assigned_event_id,
                    e.event_code AS assigned_event_code,
                    e.event_type AS assigned_event_type,
                    e.severity AS assigned_event_severity,
                    e.confidence_score AS assigned_event_confidence
                FROM teams t
                LEFT JOIN verified_events e ON t.assigned_event_id = e.id
                WHERE {where_sql}
            """),
            params,
        )
        row = team_res.mappings().first()
        if row:
            # Query members
            members_res = await db.execute(
                text("""
                    SELECT id, username, full_name, email, phone, role, operator_id, badge_number, callsign, team_role, duty_status
                    FROM user_profiles
                    WHERE team_id = :tid
                    ORDER BY team_role = 'Commander' DESC, full_name ASC
                """),
                {"tid": row["id"]},
            )
            members = []
            for m in members_res.mappings().all():
                m_dict = dict(m)
                m_dict["id"] = str(m_dict["id"])
                members.append(m_dict)

            data = dict(row)
            data["id"] = str(data["id"])
            if data["assigned_event_id"]:
                data["assigned_event_id"] = str(data["assigned_event_id"])
            data["created_at"] = data["created_at"].isoformat() if data["created_at"] else None
            data["members"] = members
            return data
    except Exception as e:
        db_error = e

    def _not_found():
        raise HTTPException(status_code=404, detail="Team not found")

    return empty_or_503(f"GET /api/teams/{team_id}", _not_found, db_error)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    team_in: TeamCreate,
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(_can_dispatch),
):
    """Create a new emergency response unit. COMMANDER or ADMIN."""
    new_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO teams (
                    id, team_code, name, agency, city, state, lead_name, lead_phone,
                    radio_callsign, specialization, status, members_count, created_at
                ) VALUES (
                    :id, :team_code, :name, CAST(:agency AS team_agency_enum), :city, :state, :lead_name, :lead_phone,
                    :radio_callsign, :specialization, CAST(:status AS team_status_enum), :members_count, NOW()
                )
            """),
            {
                "id": new_id,
                "team_code": team_in.team_code.upper(),
                "name": team_in.name,
                "agency": team_in.agency.value,
                "city": team_in.city,
                "state": team_in.state,
                "lead_name": team_in.lead_name,
                "lead_phone": team_in.lead_phone,
                "radio_callsign": team_in.radio_callsign,
                "specialization": team_in.specialization,
                "status": team_in.status.value,
                "members_count": team_in.members_count,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Team code {team_in.team_code.upper()!r} already exists",
        )
    except Exception as e:
        # The exception text used to be returned to the client verbatim.
        logger.error(f"create_team failed: {type(e).__name__}: {e}")
        await db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info(f"Team {team_in.team_code.upper()} created by {operator.sub}")
    return {"id": str(new_id), "team_code": team_in.team_code.upper(), "status": "created"}


@router.patch("/{team_id}/assign")
async def assign_team(
    team_id: str,
    payload: TeamAssignRequest,
    db: AsyncSession = Depends(get_db),
    operator: TokenData = Depends(_can_dispatch),
):
    """
    Assign a team to a verified event, or unassign it with event_id null.
    COMMANDER or ADMIN.

    A dispatch that did not happen must not answer as if it had. This used to
    return 200 for a team that does not exist, and on any database error it
    edited an in-memory DEMO_TEAMS list instead and answered "Updated in demo
    store" — whatever DEMO_MODE said. The operator saw a unit dispatched when
    nothing had been written.
    """
    event_uuid = None
    if payload.event_id:
        try:
            event_uuid = uuid.UUID(payload.event_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="event_id is not a valid UUID")

    try:
        tid_uuid = uuid.UUID(team_id)
    except (ValueError, AttributeError):
        tid_uuid = None
    where_sql = "id = :tid" if tid_uuid else "team_code = :tid"
    new_status = "DEPLOYED" if event_uuid else "AVAILABLE"

    try:
        if event_uuid:
            exists = (
                await db.execute(
                    text("SELECT 1 FROM verified_events WHERE id = :eid"),
                    {"eid": event_uuid},
                )
            ).first()
            if not exists:
                raise HTTPException(status_code=404, detail="Event not found")

        updated = (
            await db.execute(
                text(f"""
                    UPDATE teams
                    SET assigned_event_id = :event_id,
                        status = CAST(:status AS team_status_enum)
                    WHERE {where_sql}
                    RETURNING id
                """),
                {"tid": tid_uuid or team_id, "event_id": event_uuid, "status": new_status},
            )
        ).first()
        if not updated:
            await db.rollback()
            raise HTTPException(status_code=404, detail="Team not found")
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"assign_team failed: {type(e).__name__}: {e}")
        await db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info(
        f"Team {team_id} {'dispatched to ' + str(event_uuid) if event_uuid else 'returned to base'}"
        f" by {operator.sub}"
    )
    return {
        "team_id": team_id,
        "assigned_event_id": payload.event_id,
        "status": new_status,
        "assigned_by": operator.sub,
        "message": f"Team {team_id} successfully {'dispatched' if event_uuid else 'returned to base'}",
    }
