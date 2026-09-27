"""
INDRA Platform — Weather Station Corroboration (Open-Meteo)

Two requests to Open-Meteo live here:

* the **24 h rainfall** at an event's location (below, since Day 2): does recent
  rainfall support a flood report? The rain family still reads exactly this;
* since Phase 4, **one hourly request for every hazard's variable**, per H3
  res-7 cell (the section at the end): temperature, visibility, gusts, weather
  code, CAPE, and dust from the air-quality API. `services/evidence.py` turns
  them into each hazard's evidence, beside the airports' own observations.

The rest of this docstring describes the rainfall request.

    weather_score(lat, lng) -> Optional[float]

* **Source.** Open-Meteo's forecast API, `hourly=precipitation` over the past
  24 hours. No API key. Note this is gridded model/reanalysis precipitation,
  not a rain-gauge reading — the receipt's evidence line says so.
* **Curve.** Accumulated 24 h rainfall is scored against IMD's own daily
  rainfall categories, so every breakpoint is a published threshold rather than
  a hand-picked number. See RAINFALL_CURVE.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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


# ── Phase 4 T1: one request per H3 res-7 cell, every variable ─────────────────
#
# Rainfall alone says nothing for or against a heatwave, fog or a gale. Phase 4
# reads each hazard's own variable, and asks Open-Meteo for all of them at once:
#
#     hourly=precipitation,temperature_2m,visibility,wind_gusts_10m,
#            wind_speed_10m,weather_code,cape
#     past_days=1  forecast_days=1  timezone=UTC
#
# All seven answered without a key on 22 Sep. The series runs from 00:00 UTC
# yesterday to 23:00 UTC today; the evidence functions (services/evidence.py)
# only ever read the hours up to now, because an hour after now is a forecast.
#
# **Cached per H3 res-7 cell** (about 5 km², coarser than the res-8 rainfall
# cache above) for 10 minutes, in Redis under `wx:v2:{cell}`: two events in the
# same cell within ten minutes cost one request. A failure is cached for one
# minute, as above, and is None, never a guess.
#
# DUST_STORM also reads the Air Quality API (`hourly=dust,pm10`), cached under
# `wx:v2aq:{cell}`. Its dust figure is CAMS's model estimate, not a measurement.

HOURLY_VARIABLES = (
    "precipitation",
    "temperature_2m",
    "visibility",
    "wind_gusts_10m",
    "wind_speed_10m",
    "weather_code",
    "cape",
)
AIR_QUALITY_VARIABLES = ("dust", "pm10")

V2_H3_RESOLUTION = 7
V2_CACHE_KEY_PREFIX = "wx:v2:"
AIR_QUALITY_CACHE_KEY_PREFIX = "wx:v2aq:"


@dataclass(frozen=True)
class HourlySeries:
    """
    Hourly model values at one point. `times[i]` is the hour the values at
    index i belong to, aware UTC; a missing hour is None in every list.
    `elevation_m` is the model grid's elevation, which decides the hill
    heatwave threshold.
    """

    times: Tuple[datetime, ...]
    values: Dict[str, Tuple[Optional[float], ...]]
    elevation_m: Optional[float]
    provider: str  # "open-meteo forecast" | "open-meteo air-quality"

    def series(self, variable: str) -> Tuple[Optional[float], ...]:
        return self.values.get(variable) or tuple(None for _ in self.times)

    def between(
        self, variable: str, start: datetime, end: datetime
    ) -> List[Tuple[datetime, float]]:
        """(hour, value) for every non-missing value with start ≤ hour ≤ end."""
        out: List[Tuple[datetime, float]] = []
        for t, v in zip(self.times, self.series(variable)):
            if v is not None and start <= t <= end:
                out.append((t, float(v)))
        return out

    def to_json(self) -> Dict[str, Any]:
        return {
            "times": [t.isoformat() for t in self.times],
            "values": {k: list(v) for k, v in self.values.items()},
            "elevation_m": self.elevation_m,
            "provider": self.provider,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "HourlySeries":
        return cls(
            times=tuple(datetime.fromisoformat(t) for t in data["times"]),
            values={k: tuple(v) for k, v in data["values"].items()},
            elevation_m=data.get("elevation_m"),
            provider=data.get("provider", "open-meteo forecast"),
        )


def _cell7_key(lat: float, lng: float) -> str:
    try:
        import h3

        return h3.latlng_to_cell(lat, lng, V2_H3_RESOLUTION)
    except Exception:
        # ~2.5 km rounding if h3 is unavailable — the same order as res 7.
        return f"{round(lat * 40) / 40},{round(lng * 40) / 40}"


def parse_hourly(
    body: Any, variables: Sequence[str], provider: str
) -> Optional[HourlySeries]:
    """
    An Open-Meteo response as an HourlySeries, or None when it is not one.
    A variable the response left out is all None; a series with no time axis
    or no value at all is no measurement.
    """
    try:
        hourly = body["hourly"]
        raw_times = hourly["time"]
        if not isinstance(raw_times, list) or not raw_times:
            return None
        times = []
        for raw in raw_times:
            t = datetime.fromisoformat(str(raw))
            times.append(t if t.tzinfo else t.replace(tzinfo=timezone.utc))
        values: Dict[str, Tuple[Optional[float], ...]] = {}
        for name in variables:
            column = hourly.get(name)
            if not isinstance(column, list) or len(column) != len(times):
                values[name] = tuple(None for _ in times)
                continue
            values[name] = tuple(None if v is None else float(v) for v in column)
        if all(v is None for column in values.values() for v in column):
            return None
        elevation = body.get("elevation")
        return HourlySeries(
            times=tuple(times),
            values=values,
            elevation_m=float(elevation) if elevation is not None else None,
            provider=provider,
        )
    except Exception as e:
        logger.warning(f"Open-Meteo hourly response malformed: {type(e).__name__}: {e}")
        return None


async def _request_json(
    url: str, params: Dict[str, Any], client: Optional[httpx.AsyncClient]
) -> Optional[Any]:
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=settings.WEATHER_TIMEOUT_SECONDS) as own:
                resp = await own.get(url, params=params)
        else:
            resp = await client.get(url, params=params, timeout=settings.WEATHER_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning(f"Open-Meteo request to {url} failed: {type(e).__name__}: {e}")
        return None
    if resp.status_code != 200:
        logger.warning(f"Open-Meteo {url} returned HTTP {resp.status_code}")
        return None
    try:
        return resp.json()
    except Exception as e:
        logger.warning(f"Open-Meteo {url} returned no JSON: {type(e).__name__}: {e}")
        return None


async def _cached_series(
    key: str,
    url: str,
    params: Dict[str, Any],
    variables: Sequence[str],
    provider: str,
    client: Optional[httpx.AsyncClient],
) -> Optional[HourlySeries]:
    now = _clock()
    hit = await cache.get_json(key)
    # [expires_at, series | null]; a cached null is a remembered failure.
    if isinstance(hit, list) and len(hit) == 2 and hit[0] > now:
        return HourlySeries.from_json(hit[1]) if hit[1] is not None else None

    body = await _request_json(url, params, client)
    series = parse_hourly(body, variables, provider) if body is not None else None
    ttl = CACHE_TTL_SECONDS if series is not None else FAILURE_CACHE_TTL_SECONDS
    await cache.set_json(
        key, [now + ttl, series.to_json() if series is not None else None], ttl_seconds=ttl
    )
    return series


async def fetch_hourly(
    lat: float, lng: float, client: Optional[httpx.AsyncClient] = None
) -> Optional[HourlySeries]:
    """Every forecast variable Phase 4 reads, for the res-7 cell around a point. Never raises."""
    try:
        return await _cached_series(
            V2_CACHE_KEY_PREFIX + _cell7_key(lat, lng),
            settings.OPEN_METEO_API_URL,
            {
                "latitude": round(lat, 4),
                "longitude": round(lng, 4),
                "hourly": ",".join(HOURLY_VARIABLES),
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "UTC",
            },
            HOURLY_VARIABLES,
            "open-meteo forecast",
            client,
        )
    except Exception as e:  # the pipeline must never see this
        logger.warning(f"Hourly weather lookup failed unexpectedly: {e}")
        return None


async def fetch_air_quality(
    lat: float, lng: float, client: Optional[httpx.AsyncClient] = None
) -> Optional[HourlySeries]:
    """Dust and PM10 (µg/m³) for the res-7 cell around a point. Never raises."""
    try:
        return await _cached_series(
            AIR_QUALITY_CACHE_KEY_PREFIX + _cell7_key(lat, lng),
            settings.OPEN_METEO_AIR_QUALITY_URL,
            {
                "latitude": round(lat, 4),
                "longitude": round(lng, 4),
                "hourly": ",".join(AIR_QUALITY_VARIABLES),
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "UTC",
            },
            AIR_QUALITY_VARIABLES,
            "open-meteo air-quality",
            client,
        )
    except Exception as e:
        logger.warning(f"Air-quality lookup failed unexpectedly: {e}")
        return None
