"""
INDRA Platform — Events API
GET /api/events — list with filters
GET /api/events/distribution — counts by event_type for donut chart
GET /api/events/{event_id} — full event detail
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

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
}

# Gradient styles per event type for the thumbnail
IMAGE_GRADIENTS = {
    "URBAN_FLOOD": "linear-gradient(135deg, #2563EB, #1E3A8A)",
    "CLOUDBURST": "linear-gradient(135deg, #3B82F6, #6366F1)",
    "CYCLONE_INUNDATION": "linear-gradient(135deg, #EF4444, #C2410C)",
    "RIVER_BREACH": "linear-gradient(135deg, #F59E0B, #92400E)",
}


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
            verification_receipt, verified_at
        FROM verified_events
        WHERE {where_clause}
        ORDER BY verified_at DESC
        LIMIT 50
    """)

    result = await db.execute(query, params)
    rows = result.fetchall()

    events = []
    for row in rows:
        event_type_raw = row[2]
        severity_raw = row[3]
        review_raw = row[5]

        # Determine city label from verification_receipt if available
        receipt = row[10] or {}
        city = receipt.get("city", "Unknown")
        state = receipt.get("state", "")

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
            "imageGradient": IMAGE_GRADIENTS.get(event_type_raw, "linear-gradient(135deg, #64748B, #334155)"),
            "verified_at": row[11].isoformat() if row[11] else None,
            "timestamp": row[11].isoformat() if row[11] else None,
        })

    return events


@router.get("/distribution")
async def event_distribution(db: AsyncSession = Depends(get_db)):
    """
    Counts grouped by display event_type for the donut chart.
    Maps DB types to: Rainfall, Flood, Thunderstorm, Strong Winds, Fog, Others
    """
    query = text("""
        SELECT
            verification_receipt->>'event_type_display' as display_type,
            COUNT(*) as count
        FROM verified_events
        WHERE review_status != 'REJECTED'
        GROUP BY verification_receipt->>'event_type_display'
        ORDER BY count DESC
    """)

    result = await db.execute(query)
    rows = result.fetchall()

    # Color mapping for the donut chart
    color_map = {
        "Rainfall": "#3B82F6",
        "Flood": "#F59E0B",
        "Thunderstorm": "#8B5CF6",
        "Strong Winds": "#2563EB",
        "Fog": "#64748B",
        "Others": "#94A3B8",
    }

    distribution = []
    for row in rows:
        name = row[0] or "Others"
        distribution.append({
            "name": name,
            "value": row[1],
            "color": color_map.get(name, "#94A3B8"),
        })

    # If no results, return empty list (frontend will fall back to mock)
    return distribution


@router.get("/{event_id}")
async def get_event_detail(event_id: UUID, db: AsyncSession = Depends(get_db)):
    """Full event detail including verification_receipt breakdown."""
    query = text("""
        SELECT
            id, event_code, event_type, severity, confidence_score,
            review_status, quadrant, impact_radius_km,
            ST_Y(center_point) as lat, ST_X(center_point) as lng,
            ST_AsGeoJSON(boundary_polygon) as boundary_geojson,
            verification_receipt, verified_at
        FROM verified_events
        WHERE id = :event_id
    """)

    result = await db.execute(query, {"event_id": str(event_id)})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

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
        "city": receipt.get("city", "Unknown"),
        "state": receipt.get("state", ""),
    }
