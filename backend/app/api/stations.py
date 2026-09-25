"""
INDRA Platform — Station observations API (layer 8a, Phase 2 T3)

GET /api/stations/latest?feed=metar&max_age_hours=3
    → {feed, generated_at, max_age_hours, count, stations: [...]}

The newest reading from each station of one feed, for the map's station layer.
`feed=metar` is India's aerodromes: real observed temperature, wind,
visibility and present weather. `feed=open_meteo` is the six modelled
rainfall points `GET /api/geo/stations` already serves with their 48 h series.

A station whose newest reading is older than `max_age_hours` is left out
rather than drawn with an old number: a 3 °C reading from last night is not
"the current temperature at Delhi airport". Open, like every read endpoint;
the data is public observations and carries nothing personal.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = logging.getLogger("indra.api.stations")
router = APIRouter(prefix="/api/stations", tags=["Stations"])

FEEDS = ("metar", "open_meteo")

LATEST_SQL = text("""
    SELECT DISTINCT ON (station_code)
           station_code, station_name, CAST(agency AS text) AS agency, feed,
           ST_Y(station_location) AS lat, ST_X(station_location) AS lng,
           recorded_at, temperature_c, dewpoint_c, wind_kmh, gust_kmh,
           visibility_m, weather_codes, convective_cloud, rainfall_mm,
           raw_observation
    FROM station_readings
    WHERE feed = :feed
      AND recorded_at >= now() - make_interval(hours => CAST(:hours AS int))
    ORDER BY station_code, recorded_at DESC
""")


@router.get("/latest")
async def latest_observations(
    feed: str = Query("metar", description="metar (airports) or open_meteo (modelled rainfall)"),
    max_age_hours: int = Query(3, ge=1, le=48, description="Leave out stations silent for longer"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Newest reading per station of one feed. See the module docstring."""
    if feed not in FEEDS:
        raise HTTPException(
            status_code=422, detail=f"feed must be one of {list(FEEDS)}, got {feed!r}"
        )

    now = datetime.now(timezone.utc)
    try:
        rows = (await db.execute(LATEST_SQL, {"feed": feed, "hours": max_age_hours})).mappings().all()
    except Exception as e:
        # No demo payload: an invented observation on a real map is the one
        # thing this layer must never show.
        logger.warning(f"Database query failed in latest_observations: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    stations = []
    for r in rows:
        at = r["recorded_at"]
        stations.append({
            "station_code": r["station_code"],
            "station_name": r["station_name"],
            "agency": r["agency"],
            "feed": r["feed"],
            "lat": r["lat"],
            "lng": r["lng"],
            "recorded_at": at.isoformat() if at else None,
            "age_minutes": round((now - at).total_seconds() / 60) if at else None,
            "temperature_c": r["temperature_c"],
            "dewpoint_c": r["dewpoint_c"],
            "wind_kmh": r["wind_kmh"],
            "gust_kmh": r["gust_kmh"],
            "visibility_m": r["visibility_m"],
            "weather_codes": list(r["weather_codes"] or []),
            "convective_cloud": r["convective_cloud"],
            "rainfall_mm": r["rainfall_mm"],
            "raw_observation": r["raw_observation"],
        })

    return {
        "feed": feed,
        "generated_at": now.isoformat(),
        "max_age_hours": max_age_hours,
        "count": len(stations),
        "stations": stations,
    }
