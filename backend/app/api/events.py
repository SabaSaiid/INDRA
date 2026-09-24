"""
INDRA Platform — Events API
GET /api/events — list with the PS's date, event, location and status filters
GET /api/events/distribution — counts by event_type for donut chart
GET /api/events/{event_id} — full event detail
PATCH /api/events/{event_id}/review — commander/admin approve, reject, re-grade
GET /api/events/{event_id}/provenance — contributing reports + audit chain
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Literal, Optional, List, Dict, Any, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.demo import demo_fallback
from app.core.security import DEMO_USERS, TokenData, require_roles
from app.models.enums import AuditAction, EventType, ReviewStatus, Severity, SourceType
from app.services import audit
from app.services.fusion_engine import FusionEngine
# Display label and thumbnail per event type. They live in the hazard taxonomy
# with the rest of each type's description, so a new type is added in one place.
from app.services.hazards import (
    EVENT_TYPE_LABELS,
    FAMILIES,
    IMAGE_GRADIENTS,
    color_of,
    family_of,
    label_of,
    types_in_family,
)

logger = logging.getLogger("indra.api.events")
router = APIRouter(prefix="/api/events", tags=["Events"])

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



# ── GET /api/events: the PS's filters (Phase 1 T5) ─────────────────────────────
#
# "Date-wise filtering • Event-wise filtering • Location-wise filtering •
# Verification status tracking" (PS 26069). Every value is a bound parameter;
# every list and enum value is checked before the query runs, so a typo is a
# 422 naming the parameter rather than a database error reported as an outage
# (BUG-061).

# The shared parameter rules live in api/query_params.py since Phase 2 (T10),
# where report search and the exports use them too. Imported under the names
# this module has always used.
from app.api.query_params import (  # noqa: E402
    IST,
    MAX_RANGE_DAYS,
    csv_values as _csv,
    instant as _instant,
    invalid as _invalid,
    like_pattern as _like,
)
TIME_RANGE_HOURS = {"24h": 24, "48h": 48, "7d": 168}
# Severity sorts by meaning, not by the enum's declaration order.
_SEVERITY_RANK = (
    "CASE severity WHEN 'ADVISORY' THEN 0 WHEN 'MODERATE' THEN 1 "
    "WHEN 'HIGH' THEN 2 WHEN 'CRITICAL' THEN 3 END"
)
SORT_COLUMNS = {
    "verified_at": "verified_at",
    "confidence": "confidence_score",
    "severity": _SEVERITY_RANK,
}
INCLUDES = {"boundary"}


def _event_item(row, include_boundary: bool) -> Dict[str, Any]:
    event_type_raw = row["event_type"]
    receipt = row["verification_receipt"] or {}
    item = {
        "id": str(row["id"]),
        "event_code": row["event_code"],
        "eventType": receipt.get("event_type_display", EVENT_TYPE_LABELS.get(event_type_raw, event_type_raw)),
        # The enum and its family, for a client to key icons and filters on
        # instead of the display label.
        "event_type": event_type_raw,
        "family": family_of(event_type_raw),
        "severity": SEVERITY_LABELS.get(row["severity"], "moderate"),
        "confidence_score": row["confidence_score"],
        "verification": REVIEW_STATUS_LABELS.get(row["review_status"], "under-review"),
        "review_status": row["review_status"],
        "quadrant": row["quadrant"],
        "impact_radius_km": row["impact_radius_km"],
        "lat": row["lat"],
        "lng": row["lng"],
        # Was receipt.get("city", "Unknown") — read from a receipt key only the
        # synthetic seeder ever wrote, so every real event was served as
        # "Unknown". These are columns now, and a name we do not have is null
        # rather than a word that looks like one.
        "city": row["district"],
        "state": row["state"],
        "place_precision": row["place_precision"],
        "imageGradient": IMAGE_GRADIENTS.get(event_type_raw, "linear-gradient(135deg, #64748B, #334155)"),
        "verified_at": row["verified_at"].isoformat() if row["verified_at"] else None,
        "timestamp": row["verified_at"].isoformat() if row["verified_at"] else None,
    }
    if include_boundary:
        # The same GeoJSON string the detail route returns.
        item["boundary_geojson"] = row["boundary_geojson"]
    return item


@router.get("")
async def list_events(
    response: Response,
    date_from: Optional[str] = Query(
        None, alias="from",
        description="From this date (YYYY-MM-DD, an IST day) or ISO 8601 timestamp, inclusive",
    ),
    date_to: Optional[str] = Query(
        None, alias="to",
        description="To this date (YYYY-MM-DD, an IST day, inclusive) or ISO 8601 timestamp",
    ),
    event_type: Optional[str] = Query(None, description="Comma-separated event types, e.g. HEATWAVE,FOG"),
    family: Optional[str] = Query(None, description="Comma-separated: water, convective, thermal, visibility"),
    review_status: Optional[str] = Query(
        None, description="Comma-separated review statuses; REJECTED is shown only when named"
    ),
    severity: Optional[str] = Query(None, description="Comma-separated: ADVISORY, MODERATE, HIGH, CRITICAL"),
    state: Optional[str] = Query(None, max_length=120, description="Exact state name, any case"),
    district: Optional[str] = Query(None, max_length=120, description="Exact district name, any case"),
    source_type: Optional[str] = Query(
        None, description="Comma-separated; events with at least one report from these sources"
    ),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    time_range: Optional[str] = Query(None, description="Time range: 24h, 48h, 7d"),
    bbox: Optional[str] = Query(None, description="Bounding box: min_lng,min_lat,max_lng,max_lat"),
    q: Optional[str] = Query(None, max_length=100, description="Search the event code, district and state"),
    include: Optional[str] = Query(None, description="boundary: add boundary_geojson to each event"),
    sort: str = Query("verified_at:desc", description="verified_at, confidence or severity, then :asc or :desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List verified events for the map, the Recent Weather Events panel and the
    filter bar. The body is a list; the number of matching events is in the
    X-Total-Count header.
    """
    conditions: List[str] = []
    params: Dict[str, Any] = {}

    statuses = _csv("review_status", review_status, [s.value for s in ReviewStatus])
    if statuses:
        conditions.append("CAST(review_status AS text) = ANY(CAST(:statuses AS text[]))")
        params["statuses"] = statuses
    else:
        conditions.append("review_status != 'REJECTED'")

    severities = _csv("severity", severity, [s.value for s in Severity])
    if severities:
        conditions.append("CAST(severity AS text) = ANY(CAST(:severities AS text[]))")
        params["severities"] = severities

    types = _csv("event_type", event_type, [t.value for t in EventType])
    if types:
        conditions.append("CAST(event_type AS text) = ANY(CAST(:types AS text[]))")
        params["types"] = types

    families = _csv("family", family, FAMILIES, normalise=str.lower)
    if families:
        conditions.append("CAST(event_type AS text) = ANY(CAST(:family_types AS text[]))")
        params["family_types"] = [t for f in families for t in types_in_family(f)]

    sources = _csv("source_type", source_type, [s.value for s in SourceType])
    if sources:
        conditions.append("""EXISTS (
            SELECT 1 FROM raw_reports r
            WHERE r.event_id = verified_events.id
              AND CAST(r.source_type AS text) = ANY(CAST(:sources AS text[]))
        )""")
        params["sources"] = sources

    if state is not None:
        conditions.append("lower(state) = lower(:state)")
        params["state"] = state.strip()
    if district is not None:
        conditions.append("lower(district) = lower(:district)")
        params["district"] = district.strip()

    if min_confidence is not None:
        conditions.append("confidence_score >= :min_confidence")
        params["min_confidence"] = min_confidence

    start = _instant("from", date_from, end=False)
    stop = _instant("to", date_to, end=True)
    if start and stop:
        # stop[1]: a date's bound is exclusive, so from may not reach it; a
        # timestamp's is inclusive, so from may equal it.
        if start[0] > stop[0] or (stop[1] and start[0] >= stop[0]):
            raise _invalid("from", "from is later than to", date_from)
        if stop[0] - start[0] > timedelta(days=MAX_RANGE_DAYS):
            raise _invalid("from", f"the range is longer than {MAX_RANGE_DAYS} days", date_from)
    if start:
        conditions.append("verified_at >= :from_ts")
        params["from_ts"] = start[0]
    if stop:
        conditions.append("verified_at < :to_ts" if stop[1] else "verified_at <= :to_ts")
        params["to_ts"] = stop[0]

    if time_range:
        # An unknown value still means 7 days, as it always has; the dashboard
        # sends 7d.
        conditions.append("verified_at >= NOW() - make_interval(hours => CAST(:range_hours AS int))")
        params["range_hours"] = TIME_RANGE_HOURS.get(time_range, 168)

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

    if q and q.strip():
        conditions.append(
            "(event_code ILIKE :q ESCAPE '\\' OR district ILIKE :q ESCAPE '\\' OR state ILIKE :q ESCAPE '\\')"
        )
        params["q"] = _like(q.strip())

    includes = _csv("include", include, INCLUDES, normalise=str.lower) or []
    include_boundary = "boundary" in includes

    field, _, direction = sort.partition(":")
    direction = (direction or "desc").lower()
    if field not in SORT_COLUMNS or direction not in ("asc", "desc"):
        raise _invalid("sort", f"expected one of {sorted(SORT_COLUMNS)}, then :asc or :desc", sort)
    order_by = f"{SORT_COLUMNS[field]} {direction.upper()}, id {direction.upper()}"

    where_clause = " AND ".join(conditions)
    boundary_column = ", ST_AsGeoJSON(boundary_polygon) AS boundary_geojson" if include_boundary else ""
    query = text(f"""
        SELECT
            id, event_code, CAST(event_type AS text) AS event_type,
            CAST(severity AS text) AS severity, confidence_score,
            CAST(review_status AS text) AS review_status, quadrant, impact_radius_km,
            ST_Y(center_point) AS lat, ST_X(center_point) AS lng,
            verification_receipt, verified_at,
            district, state, place_precision{boundary_column}
        FROM verified_events
        WHERE {where_clause}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """)
    params.update(limit=limit, offset=offset)

    # A filter that matches nothing is an answer, never a cue for demo data.
    # Only the unfiltered call — what the dashboard has always made — keeps the
    # demo_fallback behaviour on an empty database.
    filtered = any(
        v is not None
        for v in (date_from, date_to, event_type, family, review_status, state, district,
                  source_type, min_confidence, q)
    ) or offset > 0

    db_error = None
    try:
        rows = (await db.execute(query, params)).mappings().all()
        if rows or filtered:
            if len(rows) < limit and (rows or offset == 0):
                total = offset + len(rows)
            else:
                count = (
                    await db.execute(text(f"SELECT count(*) FROM verified_events WHERE {where_clause}"), params)
                ).fetchone()
                total = int(count[0]) if count else 0
            response.headers["X-Total-Count"] = str(total)
            return [_event_item(row, include_boundary) for row in rows]
    except Exception as e:
        logger.warning(f"Database query failed in list_events: {e}")
        db_error = e

    def _demo_events():
        filtered_demo = DEMO_EVENTS
        if severity:
            filtered_demo = [
                e for e in filtered_demo
                if e["severity"].lower() == severity.lower() or e["review_status"].lower() == severity.lower()
            ]
        return filtered_demo

    events = demo_fallback("GET /api/events", _demo_events, list, db_error)
    response.headers["X-Total-Count"] = str(len(events))
    return events


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
        # Grouped by the stored type as well as the display name, and named in
        # Python. Only scripts/seed_national_data.py writes event_type_display,
        # so every event the pipeline made fell through to its enum value and
        # was drawn as a grey "URBAN_FLOOD" slice (BUG-062); it is now named
        # from the hazard taxonomy, and merged with any seeded slice of the
        # same name.
        query = text(f"""
            SELECT
                verification_receipt->>'event_type_display' as display_type,
                CAST(event_type AS text) as event_type,
                COUNT(*) as count
            FROM verified_events
            WHERE review_status != 'REJECTED' {time_clause}
            GROUP BY 1, 2
        """)
        # The seeder's display names. A taxonomy label not listed here takes
        # its colour from the taxonomy.
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

        if rows and group_by_severity:
            distribution = []
            for row in rows:
                raw_name = row[0] or "Advisory"
                name = raw_name.capitalize()
                cnt = int(row[1])
                distribution.append({
                    "name": name,
                    "count": cnt,
                    "value": cnt,
                    "color": color_map.get(raw_name, color_map.get(name, "#94A3B8")),
                })
            return distribution

        if rows:
            counts: Dict[str, int] = {}
            colors: Dict[str, str] = {}
            for display_type, event_type, cnt in rows:
                name = display_type or label_of(event_type)
                counts[name] = counts.get(name, 0) + int(cnt)
                colors.setdefault(name, color_map.get(name) or color_of(event_type))
            return [
                {"name": name, "count": cnt, "value": cnt, "color": colors[name]}
                for name, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ]
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
                           credibility_score, created_at, submitted_by
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
                # Who vouched for an OFFICIAL_DISPATCH (BUG-025); null for an
                # anonymous citizen report.
                "submitted_by": r[7],
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
