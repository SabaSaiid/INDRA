"""
INDRA Platform — Geo-analytics API (layer 5)

GET /api/geo/heatmap?window=24h|48h|7d&resolution=6|7|8
    → {resolution, window, generated_at, cells: [...]}
GET /api/geo/stations
    → [{station_code, station_name, agency, lat, lng, rainfall_mm, recorded_at, series}]

Aggregates the `h3_res8` cell already stored on every report at ingest. That
column has had two writers since Day 1 and no readers at all; this is the first
thing to read it.

Why H3 rather than a grid of latitude/longitude boxes: H3 cells are
near-equal-area hexagons, so cell counts are comparable across a map of India
instead of shrinking towards the poles, and each cell has exactly one parent at
the next coarser resolution. That parent relationship is what makes zooming a
pure aggregation — a res-7 count is the exact sum of its res-8 children, with no
re-binning and no double counting.

Resolutions offered (average hexagon edge):
    8  ≈ 0.46 km  — street cluster, the resolution reports are stored at
    7  ≈ 1.22 km  — neighbourhood
    6  ≈ 3.23 km  — city district

Open, like every other read endpoint (see tests/test_auth_enforcement.py).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.demo import demo_fallback

logger = logging.getLogger("indra.api.geo")
router = APIRouter(prefix="/api/geo", tags=["Geo"])

# Hours per accepted window. Anything else is a 422 rather than a silent default:
# a dashboard asking for a window this endpoint does not serve should be told so,
# not handed 24 hours of data labelled as something else.
WINDOW_HOURS = {"24h": 24, "48h": 48, "7d": 168}

# Stored resolution. A request finer than this cannot be served by aggregation,
# only invented.
STORED_RESOLUTION = 8


@router.get("/heatmap")
async def geo_heatmap(
    window: str = Query("24h", description="Time window: 24h, 48h or 7d"),
    resolution: int = Query(
        STORED_RESOLUTION, ge=6, le=8, description="H3 resolution: 6, 7 or 8"
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Report density per H3 cell, for the dashboard's heat layer.

    * **Duplicates are excluded.** A suppressed repost is not a second piece of
      evidence, and a heat map that counted it would show a brighter spot for a
      more viral report rather than a wetter street.
    * **Aggregation, never interpolation.** A res-6 or res-7 cell count is the
      exact sum of the stored res-8 counts beneath it. Nothing is smoothed or
      spread, so every number on the map traces to rows in `raw_reports`.
    * `linked_report_count` is how many of a cell's reports the pipeline has
      attached to a verified event — the difference between "people are
      reporting here" and "this has been fused into an incident".
    """
    if window not in WINDOW_HOURS:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=f"window must be one of {sorted(WINDOW_HOURS)}, got {window!r}",
        )

    hours = WINDOW_HOURS[window]
    db_error = None
    cells: List[Dict[str, Any]] = []

    try:
        rows = (
            await db.execute(
                text("""
                    SELECT h3_res8,
                           COUNT(*) AS report_count,
                           COUNT(event_id) AS linked_report_count
                    FROM raw_reports
                    WHERE h3_res8 IS NOT NULL
                      AND duplicate_of IS NULL
                      AND created_at >= NOW() - make_interval(hours => :hours)
                    GROUP BY h3_res8
                """),
                {"hours": hours},
            )
        ).fetchall()

        cells = _roll_up(rows, resolution)

    except Exception as e:
        logger.warning(f"GET /api/geo/heatmap: database query failed: {e}")
        db_error = e

    if db_error is not None or not cells:
        cells = demo_fallback(
            "GET /api/geo/heatmap",
            demo=lambda: [],
            empty=lambda: [],
            error=db_error,
        )

    return {
        "resolution": resolution,
        "window": window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cells": cells,
    }


def _roll_up(rows, resolution: int) -> List[Dict[str, Any]]:
    """
    Fold stored res-8 counts into their res-`resolution` ancestors.

    Kept separate from the endpoint so it can be tested without a database. A
    cell whose id h3 cannot parse is dropped with a warning rather than guessed
    at: a heat map is a claim about where reports are, and an unreadable cell id
    has nothing to say about that.
    """
    import h3

    totals: Dict[str, List[int]] = {}

    for cell, report_count, linked_count in rows:
        try:
            key = (
                cell
                if resolution == STORED_RESOLUTION
                else h3.cell_to_parent(cell, resolution)
            )
        except Exception as e:
            logger.warning(f"GET /api/geo/heatmap: unusable h3 cell {cell!r}: {e}")
            continue

        bucket = totals.setdefault(key, [0, 0])
        bucket[0] += int(report_count)
        bucket[1] += int(linked_count)

    out: List[Dict[str, Any]] = []
    for key, (report_count, linked_count) in totals.items():
        try:
            lat, lng = h3.cell_to_latlng(key)
        except Exception as e:
            logger.warning(f"GET /api/geo/heatmap: cannot place cell {key!r}: {e}")
            continue
        out.append({
            "h3": key,
            "lat": lat,
            "lng": lng,
            "report_count": report_count,
            "linked_report_count": linked_count,
        })

    # Densest first, then by cell id so equal counts come back in a stable order
    # rather than whatever the dict happened to hold.
    out.sort(key=lambda c: (-c["report_count"], c["h3"]))
    return out


# ─── GET /api/geo/stations ──────────────────────────────────────────────────

STATIONS_SQL = text("""
    WITH hourly AS (
        -- The poller writes every 10 min and Open-Meteo reports hourly, so each
        -- observation hour is stored several times; keep one row per hour.
        SELECT DISTINCT ON (station_code, recorded_at)
               station_code, station_name, CAST(agency AS text) AS agency,
               ST_Y(station_location) AS lat, ST_X(station_location) AS lng,
               rainfall_mm, recorded_at
        FROM station_readings
        WHERE recorded_at >= now() - INTERVAL '48 hours'
          -- Rainfall stations only. Since Phase 2 the table also holds airport
          -- observations (feed 'metar'), which carry no rainfall amount and are
          -- served by GET /api/stations/latest instead.
          AND rainfall_mm IS NOT NULL
        ORDER BY station_code, recorded_at
    )
    SELECT station_code, station_name, agency, lat, lng, rainfall_mm, recorded_at
    FROM hourly
    ORDER BY station_code, recorded_at
""")


@router.get("/stations")
async def list_stations(db: AsyncSession = Depends(get_db)):
    """
    Every rainfall station with its newest reading and the last 48 h of hourly
    readings, oldest first.

    `rainfall_mm` is the trailing 24 h accumulation Open-Meteo reports for the
    station's point, the same quantity the weather factor scores; `0.0` is a
    measured dry day. A station with nothing in 48 h is left out rather than
    shown with a stale number. Today these are six city points polled from
    Open-Meteo's model (agency OPEN_METEO), not IMD gauges.
    """
    try:
        rows = (await db.execute(STATIONS_SQL)).fetchall()
    except Exception as e:
        logger.warning(f"Database query failed in list_stations: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    stations: Dict[str, Dict[str, Any]] = {}
    for code, name, agency, lat, lng, mm, at in rows:
        st = stations.setdefault(code, {
            "station_code": code,
            "station_name": name,
            "agency": agency,
            "lat": lat,
            "lng": lng,
            "series": [],
        })
        st["series"].append({"at": at.isoformat(), "rainfall_mm": mm})
        st["rainfall_mm"] = mm
        st["recorded_at"] = at.isoformat()

    return sorted(stations.values(), key=lambda s: -(s.get("rainfall_mm") or 0))
