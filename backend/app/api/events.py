"""
INDRA Platform — Events API
GET /api/events — list with filters
GET /api/events/distribution — counts by event_type for donut chart
GET /api/events/{event_id} — full event detail
PATCH /api/events/{event_id}/review — commander/admin approve, reject, re-grade
GET /api/events/{event_id}/provenance — contributing reports + audit chain
"""

import json
import logging
from typing import Literal, Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.demo import demo_fallback
from app.core.security import DEMO_USERS, TokenData, require_roles
from app.models.enums import AuditAction, ReviewStatus, Severity
from app.services import audit
from app.services.fusion_engine import FusionEngine

logger = logging.getLogger("indra.api.events")
router = APIRouter(prefix="/api/events", tags=["Events"])

# Map DB event_type values to display labels matching the frontend
EVENT_TYPE_LABELS = {
    "URBAN_FLOOD": "Flood",
    "CLOUDBURST": "Rainfall",
    "CYCLONE_INUNDATION": "Rainfall",
    "RIVER_BREACH": "Flood",
}

# Map severity for frontend compatibility
SEVERITY_LABELS = {
    "ADVISORY": "low",
    "MODERATE": "moderate",
    "HIGH": "high",
    "CRITICAL": "critical",
}

REVIEW_STATUS_LABELS = {
    "AUTO_PUBLISHED": "verified",
    "PENDING_HUMAN_REVIEW": "under-review",
    "QUARANTINED": "under-review",
    "REJECTED": "rejected",
    "HUMAN_APPROVED": "verified",
}

# Gradient styles per event type for the thumbnail
IMAGE_GRADIENTS = {
    "URBAN_FLOOD": "linear-gradient(135deg, #2563EB, #1E3A8A)",
    "CLOUDBURST": "linear-gradient(135deg, #3B82F6, #6366F1)",
    "CYCLONE_INUNDATION": "linear-gradient(135deg, #EF4444, #C2410C)",
    "RIVER_BREACH": "linear-gradient(135deg, #F59E0B, #92400E)",
}

# Rich fallback verified events when database is offline
DEMO_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "ev-patna-01",
        "event_code": "WX-EV-28231827-A",
        "eventType": "Flood",
        "event_type": "URBAN_FLOOD",
        "severity": "critical",
        "confidence_score": 0.94,
        "verification": "verified",
        "review_status": "AUTO_PUBLISHED",
        "quadrant": "Patna Central Sector",
        "impact_radius_km": 6.8,
        "lat": 25.6093,
        "lng": 85.1376,
        "city": "Patna",
        "state": "Bihar",
        "imageGradient": "linear-gradient(135deg, #2563EB, #1E3A8A)",
        "verified_at": "2026-09-15T11:45:00Z",
        "timestamp": "2026-09-15T11:45:00Z",
    },
    {
        "id": "ev-guwahati-02",
        "event_code": "WX-EV-28231828-B",
        "eventType": "Rainfall",
        "event_type": "CLOUDBURST",
        "severity": "high",
        "confidence_score": 0.88,
        "verification": "under-review",
        "review_status": "PENDING_HUMAN_REVIEW",
        "quadrant": "Brahmaputra Basin",
        "impact_radius_km": 12.0,
        "lat": 26.1445,
        "lng": 91.7362,
        "city": "Guwahati",
        "state": "Assam",
        "imageGradient": "linear-gradient(135deg, #3B82F6, #6366F1)",
        "verified_at": "2026-09-15T11:15:00Z",
        "timestamp": "2026-09-15T11:15:00Z",
    },
    {
        "id": "ev-mumbai-03",
        "event_code": "WX-EV-28231829-C",
        "eventType": "Strong Winds",
        "event_type": "CYCLONE_INUNDATION",
        "severity": "moderate",
        "confidence_score": 0.91,
        "verification": "verified",
        "review_status": "AUTO_PUBLISHED",
        "quadrant": "Konkan Coastal Zone",
        "impact_radius_km": 8.5,
        "lat": 19.0760,
        "lng": 72.8777,
        "city": "Mumbai",
        "state": "Maharashtra",
        "imageGradient": "linear-gradient(135deg, #EF4444, #C2410C)",
        "verified_at": "2026-09-15T10:30:00Z",
        "timestamp": "2026-09-15T10:30:00Z",
    },
    {
        "id": "ev-delhi-04",
        "event_code": "WX-EV-28231830-D",
        "eventType": "Fog",
        "event_type": "CLOUDBURST",
        "severity": "low",
        "confidence_score": 0.82,
        "verification": "verified",
        "review_status": "AUTO_PUBLISHED",
        "quadrant": "NCR Northern Sector",
        "impact_radius_km": 15.0,
        "lat": 28.6139,
        "lng": 77.2090,
        "city": "New Delhi",
        "state": "Delhi",
        "imageGradient": "linear-gradient(135deg, #64748B, #334155)",
        "verified_at": "2026-09-15T09:00:00Z",
        "timestamp": "2026-09-15T09:00:00Z",
    },
    {
        "id": "ev-chennai-05",
        "event_code": "WX-EV-28231831-E",
        "eventType": "Rainfall",
        "event_type": "URBAN_FLOOD",
        "severity": "high",
        "confidence_score": 0.89,
        "verification": "under-review",
        "review_status": "PENDING_HUMAN_REVIEW",
        "quadrant": "Coromandel Coastal Belt",
        "impact_radius_km": 9.2,
        "lat": 13.0827,
        "lng": 80.2707,
        "city": "Chennai",
        "state": "Tamil Nadu",
        "imageGradient": "linear-gradient(135deg, #2563EB, #1E3A8A)",
        "verified_at": "2026-09-15T08:45:00Z",
        "timestamp": "2026-09-15T08:45:00Z",
    },
    {
        "id": "ev-kolkata-06",
        "event_code": "WX-EV-28231832-F",
        "eventType": "Thunderstorm",
        "event_type": "RIVER_BREACH",
        "severity": "moderate",
        "confidence_score": 0.85,
        "verification": "verified",
        "review_status": "AUTO_PUBLISHED",
        "quadrant": "Hooghly Riverfront",
        "impact_radius_km": 7.0,
        "lat": 22.5726,
        "lng": 88.3639,
        "city": "Kolkata",
        "state": "West Bengal",
        "imageGradient": "linear-gradient(135deg, #F59E0B, #92400E)",
        "verified_at": "2026-09-15T07:20:00Z",
        "timestamp": "2026-09-15T07:20:00Z",
    },
    {
        "id": "ev-bengaluru-07",
        "event_code": "WX-EV-28231833-G",
        "eventType": "Flood",
        "event_type": "URBAN_FLOOD",
        "severity": "moderate",
        "confidence_score": 0.87,
        "verification": "under-review",
        "review_status": "PENDING_HUMAN_REVIEW",
        "quadrant": "Bellandur Catchment",
        "impact_radius_km": 5.5,
        "lat": 12.9716,
        "lng": 77.5946,
        "city": "Bengaluru",
        "state": "Karnataka",
        "imageGradient": "linear-gradient(135deg, #2563EB, #1E3A8A)",
        "verified_at": "2026-09-15T06:10:00Z",
        "timestamp": "2026-09-15T06:10:00Z",
    },
]

DEMO_DISTRIBUTION: List[Dict[str, Any]] = [
    {"name": "Rainfall", "count": 142, "value": 142, "color": "#3B82F6"},
    {"name": "Flood", "count": 98, "value": 98, "color": "#F59E0B"},
    {"name": "Thunderstorm", "count": 64, "value": 64, "color": "#8B5CF6"},
    {"name": "Strong Winds", "count": 38, "value": 38, "color": "#2563EB"},
    {"name": "Fog", "count": 19, "value": 19, "color": "#64748B"},
    {"name": "Landslide", "count": 11, "value": 11, "color": "#E11D48"},
]

DEMO_SEVERITY_DISTRIBUTION: List[Dict[str, Any]] = [
    {"name": "Critical", "count": 42, "value": 42, "color": "#EF4444"},
    {"name": "High", "count": 86, "value": 86, "color": "#F59E0B"},
    {"name": "Moderate", "count": 154, "value": 154, "color": "#3B82F6"},
    {"name": "Advisory", "count": 79, "value": 79, "color": "#10B981"},
]



@router.get("")
async def list_events(
    severity: Optional[str] = Query(None, description="Filter by severity: ADVISORY, MODERATE, HIGH, CRITICAL"),
    time_range: Optional[str] = Query(None, description="Time range: 24h, 48h, 7d"),
    bbox: Optional[str] = Query(None, description="Bounding box: min_lng,min_lat,max_lng,max_lat"),
    db: AsyncSession = Depends(get_db),
):
    """List verified events for the map and Recent Weather Events panel."""
    conditions = ["review_status != 'REJECTED'"]
    params = {}

    if severity:
        conditions.append("severity = :severity")
        params["severity"] = severity.upper()

    if time_range:
        interval_map = {"24h": "24 hours", "48h": "48 hours", "7d": "7 days"}
        interval = interval_map.get(time_range, "7 days")
        conditions.append(f"verified_at >= NOW() - INTERVAL '{interval}'")

    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) == 4:
                conditions.append(
                    "ST_Within(center_point, ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))"
                )
                params["min_lng"] = parts[0]
                params["min_lat"] = parts[1]
                params["max_lng"] = parts[2]
                params["max_lat"] = parts[3]
        except (ValueError, IndexError):
            pass

    where_clause = " AND ".join(conditions)

    query = text(f"""
        SELECT
            id, event_code, event_type, severity, confidence_score,
            review_status, quadrant, impact_radius_km,
            ST_Y(center_point) as lat, ST_X(center_point) as lng,
            verification_receipt, verified_at,
            district, state, place_precision
        FROM verified_events
        WHERE {where_clause}
        ORDER BY verified_at DESC
        LIMIT 50
    """)

    db_error = None
    try:
        result = await db.execute(query, params)
        rows = result.fetchall()

        if rows:
            events = []
            for row in rows:
                event_type_raw = row[2]
                severity_raw = row[3]
                review_raw = row[5]

                receipt = row[10] or {}
                # Was receipt.get("city", "Unknown") — read from a receipt key
                # only the synthetic seeder ever wrote, so every real event
                # was served as "Unknown". These are columns now, and a name
                # we do not have is null rather than a word that looks like one.
                city = row[12]
                state = row[13]
                place_precision = row[14]

                events.append({
                    "id": str(row[0]),
                    "event_code": row[1],
                    "eventType": receipt.get("event_type_display", EVENT_TYPE_LABELS.get(event_type_raw, event_type_raw)),
                    "severity": SEVERITY_LABELS.get(severity_raw, "moderate"),
                    "confidence_score": row[4],
                    "verification": REVIEW_STATUS_LABELS.get(review_raw, "under-review"),
                    "review_status": review_raw,
                    "quadrant": row[6],
                    "impact_radius_km": row[7],
                    "lat": row[8],
                    "lng": row[9],
                    "city": city,
                    "state": state,
                    "place_precision": place_precision,
                    "imageGradient": IMAGE_GRADIENTS.get(event_type_raw, "linear-gradient(135deg, #64748B, #334155)"),
                    "verified_at": row[11].isoformat() if row[11] else None,
                    "timestamp": row[11].isoformat() if row[11] else None,
                })
            return events
    except Exception as e:
        logger.warning(f"Database query failed in list_events: {e}")
        db_error = e

    def _demo_events():
        filtered = DEMO_EVENTS
        if severity:
            filtered = [
                e for e in filtered
                if e["severity"].lower() == severity.lower() or e["review_status"].lower() == severity.lower()
            ]
        return filtered

    return demo_fallback("GET /api/events", _demo_events, list, db_error)


@router.get("/distribution")
async def event_distribution(
    by: Optional[str] = Query("hazard", description="Grouping: hazard or severity"),
    time_range: Optional[str] = Query("7d", description="Time range: 24h, 48h, 7d, all"),
    db: AsyncSession = Depends(get_db),
):
    """
    Counts grouped by display event_type or severity for the donut chart.
    Returns both 'count' and 'value' fields for chart compatibility.
    """
    group_by_severity = bool(by and by.lower() == "severity")

    time_clause = ""
    params: Dict[str, Any] = {}
    if time_range and time_range != "all":
        hours = 24 if time_range == "24h" else (48 if time_range == "48h" else 168)
        # verified_events has no created_at; the column recording when the event
        # came into being is verified_at. The old name never raised because
        # DEMO_MODE caught the error and served an invented distribution.
        time_clause = f"AND verified_at >= NOW() - INTERVAL '{hours} hours'"

    if group_by_severity:
        query = text(f"""
            SELECT
                severity,
                COUNT(*) as count
            FROM verified_events
            WHERE review_status != 'REJECTED' {time_clause}
            GROUP BY severity
            ORDER BY count DESC
        """)
        color_map = {
            "CRITICAL": "#EF4444",
            "Critical": "#EF4444",
            "HIGH": "#F59E0B",
            "High": "#F59E0B",
            "MODERATE": "#3B82F6",
            "Moderate": "#3B82F6",
            "ADVISORY": "#10B981",
            "Advisory": "#10B981",
        }
    else:
        query = text(f"""
            SELECT
                COALESCE(verification_receipt->>'event_type_display', CAST(event_type AS text)) as display_type,
                COUNT(*) as count
            FROM verified_events
            WHERE review_status != 'REJECTED' {time_clause}
            GROUP BY COALESCE(verification_receipt->>'event_type_display', CAST(event_type AS text))
            ORDER BY count DESC
        """)
        color_map = {
            "Rainfall": "#3B82F6",
            "Flood": "#F59E0B",
            "Thunderstorm": "#8B5CF6",
            "Strong Winds": "#2563EB",
            "Cyclone": "#2563EB",
            "Fog": "#64748B",
            "Landslide": "#E11D48",
            "Cloudburst": "#0EA5E9",
            "Others": "#94A3B8",
        }

    db_error = None
    try:
        result = await db.execute(query, params)
        rows = result.fetchall()

        if rows:
            distribution = []
            for row in rows:
                raw_name = row[0] or ("Advisory" if group_by_severity else "Others")
                name = raw_name.capitalize() if group_by_severity else raw_name
                cnt = int(row[1])
                distribution.append({
                    "name": name,
                    "count": cnt,
                    "value": cnt,
                    "color": color_map.get(raw_name, color_map.get(name, "#94A3B8")),
                })
            return distribution
    except Exception as e:
        logger.warning(f"Database query failed in event_distribution: {e}")
        db_error = e

    return demo_fallback(
        "GET /api/events/distribution",
        lambda: DEMO_SEVERITY_DISTRIBUTION if group_by_severity else DEMO_DISTRIBUTION,
        list,
        db_error,
    )



@router.get("/{event_id}")
async def get_event_detail(event_id: str, db: AsyncSession = Depends(get_db)):
    """Full event detail including verification_receipt breakdown."""
    # Accepts either a UUID or an event_code. The two comparisons need separate
    # parameters: with one shared parameter Postgres infers its type as uuid
    # from `id = :event_id` and then fails the varchar comparison with
    # "operator does not exist: character varying = uuid", which sent every
    # lookup — valid ones included — down to the demo fallback below.
    query = text("""
        SELECT
            id, event_code, event_type, severity, confidence_score,
            review_status, quadrant, impact_radius_km,
            ST_Y(center_point) as lat, ST_X(center_point) as lng,
            ST_AsGeoJSON(boundary_polygon) as boundary_geojson,
            verification_receipt, verified_at,
            district, state, place_precision
        FROM verified_events
        WHERE event_code = :event_code
           OR id = CAST(:event_uuid AS uuid)
    """)

    # NULL when the path segment isn't a UUID; `id = CAST(NULL AS uuid)` is
    # simply never true, so the event_code branch decides on its own.
    try:
        event_uuid = str(UUID(str(event_id)))
    except (ValueError, AttributeError, TypeError):
        event_uuid = None

    db_error = None
    try:
        result = await db.execute(
            query, {"event_code": str(event_id), "event_uuid": event_uuid}
        )
        row = result.fetchone()

        if row:
            receipt = row[11] or {}
            return {
                "id": str(row[0]),
                "event_code": row[1],
                "event_type": row[2],
                "event_type_display": receipt.get("event_type_display", row[2]),
                "severity": row[3],
                "severity_display": SEVERITY_LABELS.get(row[3], "moderate"),
                "confidence_score": row[4],
                "review_status": row[5],
                "verification": REVIEW_STATUS_LABELS.get(row[5], "under-review"),
                "quadrant": row[6],
                "impact_radius_km": row[7],
                "center": {"lat": row[8], "lng": row[9]},
                "boundary_geojson": row[10],
                "verification_receipt": receipt,
                "verified_at": row[12].isoformat() if row[12] else None,
                # Columns, not a receipt key the pipeline never wrote.
                "city": row[13],
                "state": row[14],
                "place_precision": row[15],
            }
    except Exception as e:
        logger.warning(f"Database query failed in get_event_detail: {e}")
        db_error = e

    def _demo_detail():
        # Fallback to matching demo event
        for ev in DEMO_EVENTS:
            if ev["id"] == str(event_id) or ev["event_code"] == str(event_id):
                return {
                    "id": ev["id"],
                    "event_code": ev["event_code"],
                    "event_type": ev.get("event_type", "URBAN_FLOOD"),
                    "event_type_display": ev["eventType"],
                    "severity": ev["severity"].upper(),
                    "severity_display": ev["severity"],
                    "confidence_score": ev["confidence_score"],
                    "review_status": ev["review_status"],
                    "verification": ev["verification"],
                    "quadrant": ev["quadrant"],
                    "impact_radius_km": ev["impact_radius_km"],
                    "center": {"lat": ev["lat"], "lng": ev["lng"]},
                    "boundary_geojson": None,
                    "verification_receipt": {
                        "city": ev["city"],
                        "state": ev["state"],
                        "confidence_total": int(ev["confidence_score"] * 100),
                        "event_type_display": ev["eventType"],
                    },
                    "verified_at": ev["verified_at"],
                    "city": ev["city"],
                    "state": ev["state"],
                }

        # Default fallback: Patna flood scenario event
        ev = DEMO_EVENTS[0]
        return {
            "id": ev["id"],
            "event_code": ev["event_code"],
            "event_type": "URBAN_FLOOD",
            "event_type_display": ev["eventType"],
            "severity": ev["severity"].upper(),
            "severity_display": ev["severity"],
            "confidence_score": ev["confidence_score"],
            "review_status": ev["review_status"],
            "verification": ev["verification"],
            "quadrant": ev["quadrant"],
            "impact_radius_km": ev["impact_radius_km"],
            "center": {"lat": ev["lat"], "lng": ev["lng"]},
            "boundary_geojson": None,
            "verification_receipt": {
                "city": ev["city"],
                "state": ev["state"],
                "confidence_total": int(ev["confidence_score"] * 100),
                "event_type_display": ev["eventType"],
            },
            "verified_at": ev["verified_at"],
            "city": ev["city"],
            "state": ev["state"],
        }

    def _not_found():
        raise HTTPException(status_code=404, detail="Event not found")

    return demo_fallback(f"GET /api/events/{event_id}", _demo_detail, _not_found, db_error)


# ── Human review ───────────────────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "override_severity"]
    reason: str = Field(min_length=5, max_length=1000)
    new_severity: Optional[Severity] = None

    @model_validator(mode="after")
    def _severity_required_for_override(self):
        if self.action == "override_severity" and self.new_severity is None:
            raise ValueError("new_severity is required for override_severity")
        return self


# action → (statuses it may start from, audit action). None = any except REJECTED.
REVIEW_TRANSITIONS = {
    "approve": (
        {ReviewStatus.QUARANTINED.value, ReviewStatus.PENDING_HUMAN_REVIEW.value},
        AuditAction.HUMAN_APPROVE,
    ),
    "reject": (None, AuditAction.HUMAN_REJECT),
    "override_severity": (None, AuditAction.MANUAL_OVERRIDE),
}


def _event_uuid_or_404(event_id: str) -> str:
    try:
        return str(UUID(str(event_id)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Event not found")


@router.patch("/{event_id}/review")
async def review_event(
    event_id: str,
    body: ReviewRequest,
    operator: TokenData = Depends(require_roles("COMMANDER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """
    A commander's decision on an event.

    | action            | allowed from                      | result                     |
    |-------------------|-----------------------------------|----------------------------|
    | approve           | QUARANTINED, PENDING_HUMAN_REVIEW | HUMAN_APPROVED             |
    | reject            | anything but REJECTED             | REJECTED                   |
    | override_severity | anything but REJECTED             | severity = new_severity    |

    Any other starting status is a 409 and writes nothing.

    * **Quadrant.** assign_quadrant() is score-based, so an approved 0.43 event
      would still read "Noise" — contradicting the approval. An approved event's
      quadrant follows its severity instead: HIGH/CRITICAL → "Critical Verified
      Event", otherwise "Confirmed Minor Event".
    * **confidence_score is never touched.** The machine's number stays the
      machine's number; the human decision is recorded beside it, in
      verification_receipt.human_review and in the audit chain.
    * **Serialised.** The row is locked FOR UPDATE, so two commanders reviewing
      at once get one 200 and one 409. The pipeline's merge takes the same lock
      and preserves HUMAN_APPROVED and severity_override (pipeline.py step 7).
    * The status change and its audit row commit together; EVENT_REVIEWED is
      broadcast only after the commit.
    """
    event_uuid = _event_uuid_or_404(event_id)
    operator_id = DEMO_USERS.get(operator.sub, {}).get("operator_id", operator.sub)

    try:
        row = (
            await db.execute(
                text("""
                    SELECT id, event_code, review_status, severity, quadrant,
                           confidence_score, verification_receipt
                    FROM verified_events
                    WHERE id = CAST(:id AS uuid)
                    FOR UPDATE
                """),
                {"id": event_uuid},
            )
        ).fetchone()
    except Exception as e:
        logger.warning(f"Database query failed in review_event: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    if row is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Event not found")

    _, event_code, status, severity, quadrant, confidence, receipt = row
    receipt = receipt or {}
    allowed_from, audit_action = REVIEW_TRANSITIONS[body.action]
    if status == ReviewStatus.REJECTED.value or (
        allowed_from is not None and status not in allowed_from
    ):
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {body.action} an event that is {status}",
        )

    new_status, new_severity = status, severity
    if body.action == "approve":
        new_status = ReviewStatus.HUMAN_APPROVED.value
    elif body.action == "reject":
        new_status = ReviewStatus.REJECTED.value
    else:
        new_severity = body.new_severity.value

    new_quadrant = quadrant
    if new_status == ReviewStatus.HUMAN_APPROVED.value:
        new_quadrant = FusionEngine.human_approved_quadrant(Severity(new_severity)).value
    elif body.action == "override_severity":
        new_quadrant = FusionEngine().assign_quadrant(Severity(new_severity), confidence).value

    try:
        entry = await audit.record(
            db,
            event_id=event_uuid,
            operator_id=operator_id,
            action=audit_action,
            reason=body.reason,
            details={
                "review_action": body.action,
                "from_status": status,
                "to_status": new_status,
                "from_severity": severity,
                "to_severity": new_severity,
                "confidence_score": confidence,
            },
        )

        human_review = {
            "action": body.action,
            "operator_id": operator_id,
            "reason": body.reason,
            "at": entry["logged_at"].isoformat(),
        }
        severity_override = (
            new_severity if body.action == "override_severity"
            else (receipt.get("human_review") or {}).get("severity_override")
        )
        if severity_override:
            human_review["severity_override"] = severity_override
        receipt["human_review"] = human_review

        await db.execute(
            text("""
                UPDATE verified_events SET
                    review_status = CAST(:status AS review_status_enum),
                    severity = CAST(:sev AS severity_enum),
                    quadrant = CAST(:quad AS quadrant_enum),
                    verification_receipt = CAST(:receipt AS jsonb)
                WHERE id = CAST(:id AS uuid)
            """),
            {
                "id": event_uuid,
                "status": new_status,
                "sev": new_severity,
                "quad": new_quadrant,
                "receipt": json.dumps(receipt),
            },
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"review_event failed for {event_uuid}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Review could not be recorded")

    logger.info(
        f"Review: {operator_id} {body.action} {event_code} "
        f"{status} -> {new_status}, severity {severity} -> {new_severity}"
    )

    try:
        from app.main import ws_manager

        await ws_manager.broadcast({
            "type": "EVENT_REVIEWED",
            "event": {
                "id": event_uuid,
                "event_code": event_code,
                "review_status": new_status,
                "severity": new_severity,
                "quadrant": new_quadrant,
                "confidence_score": confidence,
            },
            "review": {
                "action": body.action,
                "operator_id": operator_id,
                "reason": body.reason,
                "at": human_review["at"],
            },
        })
    except Exception as e:
        # The decision is committed; a failed broadcast must not report it as failed.
        logger.error(f"EVENT_REVIEWED broadcast failed for {event_code}: {e}")

    return await get_event_detail(event_uuid, db)


# ── Provenance ─────────────────────────────────────────────────────────────────

@router.get("/{event_id}/provenance")
async def event_provenance(
    event_id: str,
    operator: TokenData = Depends(require_roles("ANALYST", "COMMANDER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """
    Where an event came from: every contributing report (oldest first), every
    decision taken on it (in chain order), and a check of the audit chain.

    `chain` verifies the **whole ledger** from genesis, not only this event's
    rows — a deleted or rewritten row anywhere would break the links this
    event's rows depend on, so a per-event check alone would prove less.
    `chain.checked` is therefore the ledger's row count.

    Citizens are refused: this exposes other people's raw report text. There is
    no demo fallback — provenance that isn't real is worse than a 503.
    """
    event_uuid = _event_uuid_or_404(event_id)

    try:
        event = (
            await db.execute(
                text("""
                    SELECT id, event_code, review_status, severity,
                           confidence_score, verification_receipt
                    FROM verified_events WHERE id = CAST(:id AS uuid)
                """),
                {"id": event_uuid},
            )
        ).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        reports = (
            await db.execute(
                text("""
                    SELECT id, source_type, raw_text, latitude, longitude,
                           credibility_score, created_at
                    FROM raw_reports
                    WHERE event_id = CAST(:id AS uuid)
                    ORDER BY created_at, id
                """),
                {"id": event_uuid},
            )
        ).fetchall()

        audit_rows = await audit.fetch_rows(db, event_uuid)
        chain = await audit.verify_chain(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database query failed in event_provenance: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {
        "event": {
            "id": str(event[0]),
            "event_code": event[1],
            "review_status": event[2],
            "severity": event[3],
            "confidence_score": event[4],
            "verification_receipt": event[5] or {},
        },
        "reports": [
            {
                "id": str(r[0]),
                "source_type": r[1],
                "raw_text": r[2],
                "latitude": r[3],
                "longitude": r[4],
                "credibility_score": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in reports
        ],
        "audit": [
            {
                "seq": a["seq"],
                "action_taken": a["action_taken"],
                "operator_id": a["operator_id"],
                "reason": a["reason"],
                "details": a["details"],
                "logged_at": a["logged_at"].isoformat(),
                "sha256_hash": a["sha256_hash"],
                "prev_hash": a["prev_hash"],
            }
            for a in audit_rows
        ],
        "chain": chain,
    }
