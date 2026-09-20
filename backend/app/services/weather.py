"""
INDRA Platform — Weather Station Corroboration (Open-Meteo)

The one external signal in the fusion receipt: does recent rainfall at the
event's location support a flood report?

    weather_score(lat, lng) -> Optional[float]

* **Source.** Open-Meteo's forecast API, `hourly=precipitation` over the past
  24 hours. No API key. Note this is gridded model/reanalysis precipitation,
  not a rain-gauge reading — the receipt's evidence line says so.
* **Curve.** Accumulated 24 h rainfall is scored against IMD's own daily
  rainfall categories, so every breakpoint is a published threshold rather than
  a number picked for the demo. See RAINFALL_CURVE.
* **Cache.** One entry per H3 res-8 cell for 10 minutes, in Redis under
  `wx:{cell}` and in process memory when Redis is down (`services/cache.py`). A
  flood cluster sends many reports from the same few cells in quick succession;
  they must not each make an HTTP request. The expiry is written *inside* the
  cached value as well as given to Redis as a TTL, so both backends expire on the
  same injected clock and the cache behaves identically either way.
* **Failure is `None`, never a guess.** Timeout, connection error, non-200,
  malformed JSON, missing field — all return None, which compute_receipt()
  excludes from the weighted mean, lowering the receipt's `factor_coverage` by
  this factor's 0.25 rather than scoring it a misleading 0.0. This function
  never raises. Zero rainfall is *not* a failure: it is a real measurement, and
  it scores 0.0 with the factor **online**, costing the full 0.25 — which is the
  whole reason None and 0.0 have to stay distinguishable here.
"""

import logging
import time
from typing import Callable, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.services import cache

logger = logging.getLogger("indra.services.weather")
settings = get_settings()

LOOKBACK_HOURS = 24

CACHE_TTL_SECONDS = 600
# Failures are cached too, but briefly: with the network down, every report in
# a burst would otherwise wait out the full timeout, yet a transient blip
# should not blank the factor for ten minutes.
FAILURE_CACHE_TTL_SECONDS = 60

# (24 h rainfall mm, score) breakpoints, linearly interpolated between them.
# The mm values are IMD's daily rainfall category boundaries:
#   0.0           no rain              → 0.00
#   2.5           light rain begins    → 0.10
#   15.6          moderate begins      → 0.35
#   64.5          heavy begins         → 0.70
#   115.6         very heavy begins    → 0.90
#   204.5+        extremely heavy      → 1.00
# Scores rise fastest through moderate→heavy, the band in which urban drainage
# typically fails, and flatten above very heavy where the question "was there
# enough rain to flood?" is already settled.
RAINFALL_CURVE: List[Tuple[float, float]] = [
    (0.0, 0.00),
    (2.5, 0.10),
    (15.6, 0.35),
    (64.5, 0.70),
    (115.6, 0.90),
    (204.5, 1.00),
]

# Redis key namespace for the per-cell reading.
CACHE_KEY_PREFIX = "wx:"

# Injectable for tests; production uses time.monotonic.
_clock: Callable[[], float] = time.monotonic


def rainfall_to_score(rainfall_mm: float) -> float:
    """Map 24 h accumulated rainfall (mm) to a 0–1 score on RAINFALL_CURVE."""
    mm = max(0.0, float(rainfall_mm))
    for (x0, y0), (x1, y1) in zip(RAINFALL_CURVE, RAINFALL_CURVE[1:]):
        if mm <= x1:
            return round(y0 + (y1 - y0) * (mm - x0) / (x1 - x0), 4)
    return RAINFALL_CURVE[-1][1]


def _cell_key(lat: float, lng: float) -> str:
    try:
        import h3

        return h3.latlng_to_cell(lat, lng, settings.H3_HEX_RESOLUTION)
    except Exception:
        # ~1 km rounding if h3 is unavailable — same order of size as res 8.
        return f"{round(lat, 2)},{round(lng, 2)}"


def clear_cache() -> None:
    """Drop the cached readings. Clears the memory fallback only."""
    cache.clear()


async def fetch_rainfall(
    lat: float,
    lng: float,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[float]:
    """
    Accumulated precipitation (mm) over the last LOOKBACK_HOURS at (lat, lng),
    or None on any failure. Cached per H3 cell. Never raises.
    """
    key = CACHE_KEY_PREFIX + _cell_key(lat, lng)
    now = _clock()

    hit = await cache.get_json(key)
    # [expires_at, rainfall_mm | null]. A cached null is a remembered failure,
    # which is not the same as a cache miss and must not trigger a request.
    if isinstance(hit, list) and len(hit) == 2 and hit[0] > now:
        return hit[1]

    rainfall = await _request_rainfall(lat, lng, client)
    ttl = CACHE_TTL_SECONDS if rainfall is not None else FAILURE_CACHE_TTL_SECONDS
    await cache.set_json(key, [now + ttl, rainfall], ttl_seconds=ttl)
    return rainfall


async def _request_rainfall(
    lat: float, lng: float, client: Optional[httpx.AsyncClient]
) -> Optional[float]:
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
        "hourly": "precipitation",
        "past_hours": LOOKBACK_HOURS,
        "forecast_hours": 0,
        "timezone": "UTC",
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=settings.WEATHER_TIMEOUT_SECONDS) as own:
                resp = await own.get(settings.OPEN_METEO_API_URL, params=params)
        else:
            resp = await client.get(
                settings.OPEN_METEO_API_URL,
                params=params,
                timeout=settings.WEATHER_TIMEOUT_SECONDS,
            )
    except Exception as e:
        logger.warning(f"Open-Meteo request failed for ({lat}, {lng}): {type(e).__name__}: {e}")
        return None

    if resp.status_code != 200:
        logger.warning(f"Open-Meteo returned HTTP {resp.status_code} for ({lat}, {lng})")
        return None

    try:
        values = resp.json()["hourly"]["precipitation"]
        if not isinstance(values, list) or not values:
            raise ValueError("empty precipitation series")
        # Open-Meteo reports missing hours as null; they contribute nothing,
        # but a series that is entirely null is no measurement at all.
        present = [float(v) for v in values if v is not None]
        if not present:
            raise ValueError("precipitation series is all null")
        return round(sum(present), 2)
    except Exception as e:
        logger.warning(f"Open-Meteo response malformed for ({lat}, {lng}): {type(e).__name__}: {e}")
        return None


async def weather_score(
    lat: float,
    lng: float,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    (score, rainfall_mm) for the Weather Station Corroboration factor.
    Both are None when the signal is unavailable. Never raises.
    """
    try:
        rainfall = await fetch_rainfall(lat, lng, client)
    except Exception as e:  # belt and braces — the pipeline must not see this
        logger.warning(f"Weather lookup failed unexpectedly: {e}")
        return None, None
    if rainfall is None:
        return None, None
    return rainfall_to_score(rainfall), rainfall
