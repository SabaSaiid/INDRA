"""
INDRA Platform — Station Poller (layer 1: the one scheduled external feed)

`station_readings` was created on Day 1 and never held a row (BUG-008). Every
weather number in the platform was fetched per event, at scoring time, from
Open-Meteo — which meant layer 1 had no feed on a schedule and layer 7 had no
historical table with anything in it.

This task closes both. Every STATION_POLL_INTERVAL_SECONDS it reads Open-Meteo's
current precipitation for the demo cities and writes one row each:

    station_code    OM-PATNA, OM-DELHI, …
    agency          OPEN_METEO          — never IMD or CWC; there is no feed for
                                          either, and a row claiming one would be
                                          a fabricated source
    rainfall_mm     the reported value  — 0.0 is a real measurement, not a miss
    river_level_m   NULL                — no gauge feed exists
    anomaly_score   NULL                — anomaly detection is out of scope since
                                          20 Sep. 0.0 would read as "computed and
                                          normal", which is a lie about a model
                                          that does not run
    recorded_at     the observation time Open-Meteo reports, not now()

The task never takes the app down. Every tick is wrapped; a failure logs one
WARNING and the next tick retries. With STATION_POLLER_ENABLED=false nothing is
started and nothing else changes.

Single process only, like the rest of the demo stack: two backends polling would
write each reading twice. That is the same rule already recorded for the Kafka
consumer (BUG-011).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint

from app.core.config import get_settings
from app.models.enums import Agency
from app.models.station_readings import StationReading

logger = logging.getLogger("indra.workers.station_poller")
settings = get_settings()

# The same six cities scripts/burst_reports.py uses, so a demo and a poll talk
# about the same places. (lat, lng).
STATIONS: Dict[str, Tuple[float, float]] = {
    "Patna": (25.5941, 85.1376),
    "Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777),
    "Chennai": (13.0827, 80.2707),
    "Kolkata": (22.5726, 88.3639),
    "Guwahati": (26.1445, 91.7362),
}


def station_code(city: str) -> str:
    return f"OM-{city.upper()}"


async def fetch_current_precipitation(
    lat: float, lng: float, client: httpx.AsyncClient
) -> Optional[Tuple[float, datetime]]:
    """
    (precipitation_mm, observed_at) at a point, or None on any failure.

    Never raises. A malformed or partial body is a failure, not a zero — the
    whole point of this table is that every row came from a real response.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
        "current": "precipitation",
        "timezone": "UTC",
    }
    try:
        resp = await client.get(
            settings.OPEN_METEO_API_URL,
            params=params,
            timeout=settings.WEATHER_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning(f"Open-Meteo current failed for ({lat}, {lng}): {type(e).__name__}: {e}")
        return None

    if resp.status_code != 200:
        logger.warning(f"Open-Meteo current returned HTTP {resp.status_code} for ({lat}, {lng})")
        return None

    try:
        current = resp.json()["current"]
        mm = current["precipitation"]
        if mm is None:
            raise ValueError("precipitation is null")
        observed_at = datetime.fromisoformat(current["time"]).replace(tzinfo=timezone.utc)
        return float(mm), observed_at
    except Exception as e:
        logger.warning(
            f"Open-Meteo current response malformed for ({lat}, {lng}): {type(e).__name__}: {e}"
        )
        return None


async def poll_once(db, client: Optional[httpx.AsyncClient] = None) -> int:
    """
    One tick: read every station and write what came back. Returns the number of
    rows written — 0 is a legitimate outcome when Open-Meteo is unreachable.

    Rows are only written for stations that actually answered. A station that
    failed simply has no row for this tick, which is visible in the data rather
    than papered over with a zero.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.WEATHER_TIMEOUT_SECONDS)

    written = 0
    try:
        for city, (lat, lng) in STATIONS.items():
            reading = await fetch_current_precipitation(lat, lng, client)
            if reading is None:
                continue
            mm, observed_at = reading
            db.add(
                StationReading(
                    station_code=station_code(city),
                    station_name=city,
                    agency=Agency.OPEN_METEO,
                    station_location=ST_SetSRID(ST_MakePoint(lng, lat), 4326),
                    rainfall_mm=mm,
                    river_level_m=None,
                    anomaly_score=None,
                    recorded_at=observed_at,
                )
            )
            written += 1

        if written:
            await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Station poll tick failed: {type(e).__name__}: {e}")
        return 0
    finally:
        if own_client:
            await client.aclose()

    return written


async def start_station_poller() -> None:
    """
    The lifespan task. Polls immediately on startup so a fresh stack has rows
    within seconds rather than ten minutes, then every interval.
    """
    if not settings.STATION_POLLER_ENABLED:
        logger.info("Station poller disabled (STATION_POLLER_ENABLED=false)")
        return

    from app.core.database import async_session

    logger.info(
        f"✓ Station poller started — {len(STATIONS)} stations "
        f"every {settings.STATION_POLL_INTERVAL_SECONDS}s"
    )

    while True:
        try:
            async with async_session() as db:
                written = await poll_once(db)
            if written:
                logger.info(f"Station poll wrote {written}/{len(STATIONS)} readings")
            else:
                logger.warning("Station poll wrote no readings — Open-Meteo unreachable?")
        except asyncio.CancelledError:
            logger.info("Station poller shutting down...")
            raise
        except Exception as e:
            # The task must outlive any single failure, including a database
            # that is not up yet on a cold start.
            logger.warning(f"Station poll failed (non-fatal): {type(e).__name__}: {e}")

        try:
            await asyncio.sleep(settings.STATION_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Station poller shutting down...")
            raise


async def latest_reading_near(
    db, lat: float, lng: float
) -> Optional[Tuple[float, datetime, str]]:
    """
    (rainfall_mm, recorded_at, station_code) for the freshest station reading
    within STATION_READING_MAX_DISTANCE_KM and STATION_READING_MAX_AGE_MINUTES
    of a point, or None if there is no such row.

    A row whose rainfall_mm is NULL is not a reading and is skipped; a row
    whose rainfall_mm is 0.0 is a real measurement and is used.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT rainfall_mm, recorded_at, station_code
        FROM station_readings
        WHERE rainfall_mm IS NOT NULL
          AND recorded_at >= now() - make_interval(mins => :max_age_min)
          AND ST_DWithin(
                station_location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :max_dist_m
              )
        ORDER BY recorded_at DESC
        LIMIT 1
        """
    )
    try:
        row = (
            await db.execute(
                sql,
                {
                    "lat": lat,
                    "lng": lng,
                    "max_age_min": settings.STATION_READING_MAX_AGE_MINUTES,
                    "max_dist_m": settings.STATION_READING_MAX_DISTANCE_KM * 1000.0,
                },
            )
        ).first()
    except Exception as e:
        logger.warning(f"Station reading lookup failed: {type(e).__name__}: {e}")
        return None

    if row is None:
        return None
    return float(row[0]), row[1], row[2]
