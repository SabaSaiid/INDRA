"""
INDRA Platform — Agency Alerts API (layer 1 read surface)

`GET /api/alerts/agency` — the official warnings the SACHET poller has stored:
IMD, CWC and state SDMA alerts published on NDMA's national CAP feed.

**This is not the alert engine.** Layer 8b — INDRA issuing, superseding and
retracting its own alerts, with SMS and email dispatch — is out of scope since
20 Sep and is not coming. Nothing here decides anything or notifies anyone. It
reads back warnings other agencies issued, which the poller fetched.

Why the dashboard needs it: every number on the screen up to now was derived
from the citizen reports INDRA itself received, and a pile of reports cannot
corroborate itself. An IMD warning covering the same district in the same hour
is the first genuinely independent evidence the operator can see.

Expired alerts are excluded by default. A warning whose `expires` has passed is
not evidence about now, and showing it beside live events would misrepresent
what is currently in force.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.geocoding import locate_area_description, place_point

logger = logging.getLogger("indra.api.alerts")

router = APIRouter(prefix="/api/alerts", tags=["Agency Alerts"])


LIST_SQL = """
    SELECT
        id, identifier, sender, event, severity, raw_severity, certainty,
        urgency, headline, area_desc, category,
        effective_at, expires_at, sent_at,
        (area_polygon IS NOT NULL) AS has_polygon,
        district_codes
    FROM agency_alerts
    -- CAST(x AS text) is used throughout instead of the postgres shorthand.
    -- SQLAlchemy's text() scans for a colon followed by a word and turns it
    -- into a bind parameter, so the shorthand becomes a phantom bind named
    -- "text" and the statement dies with "A value is required for bind
    -- parameter 'text'". That applies inside SQL comments too, which is how
    -- the first attempt at explaining this broke the query it documented.
    WHERE (CAST(:include_expired AS boolean) OR expires_at IS NULL OR expires_at > now())
      AND (CAST(:severity AS text) IS NULL OR CAST(severity AS text) = CAST(:severity AS text))
    ORDER BY COALESCE(sent_at, fetched_at) DESC
    LIMIT :limit
"""


def _locate(area_desc) -> dict:
    """
    Map coordinates for an alert, from the only location it actually carries.

    None of the stored alerts has a geometry — NDMA answers 403 on the CAP
    polygon endpoint — and their `district_codes` are LGD codes, a vocabulary
    the district gazetteer does not speak. What every alert does carry is an
    `area_desc` in prose, so that is what gets resolved.

    `lat`/`lng` are null when nothing resolves, which is the right answer for
    the mandal-level scopes the state SDMAs issue: a mandal pinned to a
    district centroid is a warning drawn in the wrong place. Across the live
    corpus 98 of 116 descriptions resolve, 35 of them only to a state, and
    `location_precision` says which is which so the map can draw a state-wide
    warning differently from a located one.
    """
    places = locate_area_description(area_desc)
    if not places:
        return {
            "lat": None,
            "lng": None,
            "location_label": None,
            "location_precision": None,
            "districts_matched": 0,
        }

    first = places[0]
    point = place_point(first)
    return {
        "lat": point[0] if point else None,
        "lng": point[1] if point else None,
        "location_label": first.label,
        "location_precision": first.precision,
        # A CAP alert routinely covers several districts. The marker sits on
        # the first; this number stops that being read as the whole scope.
        "districts_matched": len(places),
    }


@router.get("/agency")
async def list_agency_alerts(
    limit: int = Query(20, ge=1, le=200),
    severity: Optional[str] = Query(
        None, description="ADVISORY | MODERATE | HIGH | CRITICAL"
    ),
    include_expired: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Official agency warnings, newest first.

    An empty list means no agency has a live warning in force — a real answer,
    and one that happens. It is never padded.

    `severity` may be NULL on a row: CAP allows the issuing agency to say
    `Unknown`, and `raw_severity` preserves whatever word they used. Filtering by
    severity therefore excludes unrated alerts rather than guessing where they
    belong.
    """
    if severity is not None:
        severity = severity.upper()
        if severity not in {"ADVISORY", "MODERATE", "HIGH", "CRITICAL"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="severity must be ADVISORY, MODERATE, HIGH or CRITICAL",
            )

    try:
        rows = (
            await db.execute(
                text(LIST_SQL),
                {
                    "limit": limit,
                    "severity": severity,
                    "include_expired": include_expired,
                },
            )
        ).mappings().all()
    except Exception as e:
        logger.warning(f"agency alert list failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    return [
        {
            "id": str(r["id"]),
            "identifier": r["identifier"],
            "sender": r["sender"],
            "event": r["event"],
            "category": r["category"],
            "severity": r["severity"].value if hasattr(r["severity"], "value") else r["severity"],
            "raw_severity": r["raw_severity"],
            "certainty": r["certainty"],
            "urgency": r["urgency"],
            "headline": r["headline"],
            "area_desc": r["area_desc"],
            "district_codes": r["district_codes"],
            **_locate(r["area_desc"]),
            "effective_at": r["effective_at"].isoformat() if r["effective_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "has_polygon": bool(r["has_polygon"]),
        }
        for r in rows
    ]


@router.get("/agency/{alert_id}/polygon")
async def get_agency_alert_polygon(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    The warning's footprint as GeoJSON, for drawing on the operator's map.

    Served separately from the list because these rings are large — one live
    Gujarat district alert carried 6332 vertices — and the list is rendered far
    more often than any single footprint is drawn.

    404 when the alert has no polygon. Some CAP alerts carry only LGD district
    codes, and a bounding box derived from those would be a footprint no agency
    drew.
    """
    try:
        row = (
            await db.execute(
                text(
                    "SELECT ST_AsGeoJSON(area_polygon) AS geojson, polygon_thinned, "
                    "polygon_points, identifier, sender "
                    "FROM agency_alerts WHERE CAST(id AS text) = :aid OR identifier = :aid"
                ),
                {"aid": alert_id},
            )
        ).mappings().first()
    except Exception as e:
        logger.warning(f"agency alert polygon failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    if not row or not row["geojson"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No polygon for this alert",
        )

    return {
        "identifier": row["identifier"],
        "sender": row["sender"],
        "geojson": row["geojson"],
        # True means the ring was decimated to bound its size, so this is an
        # approximation of the agency's geometry, not the geometry itself.
        "thinned": bool(row["polygon_thinned"]),
        "source_points": row["polygon_points"],
    }
