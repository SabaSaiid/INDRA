"""
INDRA Platform — Dependency health checks for GET /healthz

Each check actually talks to its dependency. They run concurrently, each capped
at CHECK_TIMEOUT_SECONDS, so a hung dependency costs at most that long.

    status      HTTP  when
    healthy     200   every check is up
    degraded    200   a non-critical check is down (Redis, Open-Meteo)
    unhealthy   503   a critical check is down (Postgres, Kafka/Redpanda)

Postgres and Kafka are critical because without either a submitted report is
not stored or not processed. Nothing reads Redis yet, and Open-Meteo being down
only marks the weather factor offline in new receipts, so those degrade.

A check is "down" if it raises, returns False, or times out.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

import httpx
from sqlalchemy import text

from app.core.config import get_settings

settings = get_settings()

CHECK_TIMEOUT_SECONDS = 2.0

# A Patna coordinate, requesting only the current hour: the cheapest real
# forecast call that proves the API answers the request the pipeline makes.
_WEATHER_PROBE_PARAMS = {
    "latitude": 25.59,
    "longitude": 85.14,
    "hourly": "precipitation",
    "past_hours": 1,
    "forecast_hours": 1,
}


async def check_database() -> bool:
    from app.core.database import engine

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def check_streaming_bus() -> bool:
    from app.workers.report_consumer import check_kafka_connection

    return await check_kafka_connection(settings.KAFKA_BOOTSTRAP_SERVERS, timeout=CHECK_TIMEOUT_SECONDS)


async def check_redis() -> bool:
    import redis.asyncio as redis

    client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=CHECK_TIMEOUT_SECONDS)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


async def check_weather_api() -> bool:
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        resp = await client.get(settings.OPEN_METEO_API_URL, params=_WEATHER_PROBE_PARAMS)
    resp.raise_for_status()
    return True


# name → (check, critical)
CHECKS: Dict[str, Tuple[Callable[[], Awaitable[bool]], bool]] = {
    "database": (check_database, True),
    "streaming_bus": (check_streaming_bus, True),
    "redis": (check_redis, False),
    "weather_api": (check_weather_api, False),
}


async def _run(name: str, check: Callable[[], Awaitable[bool]]) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        ok = await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        result: Dict[str, Any] = {"status": "up" if ok else "down"}
        if not ok:
            result["error"] = f"{name} check returned False"
    except asyncio.TimeoutError:
        result = {"status": "down", "error": f"timeout after {CHECK_TIMEOUT_SECONDS:.1f} s"}
    except Exception as e:
        first_line = str(e).split("\n")[0].strip()
        result = {"status": "down", "error": f"{type(e).__name__}: {first_line}"[:200]}
    result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return result


async def run_health_checks() -> Tuple[int, Dict[str, Any]]:
    """Returns (http_status, body)."""
    names = list(CHECKS)
    results = await asyncio.gather(*(_run(n, CHECKS[n][0]) for n in names))
    checks = {n: dict(r, critical=CHECKS[n][1]) for n, r in zip(names, results)}

    critical_down = any(c["critical"] and c["status"] != "up" for c in checks.values())
    any_down = any(c["status"] != "up" for c in checks.values())

    if critical_down:
        return 503, {"status": "unhealthy", "checks": checks}
    if any_down:
        return 200, {"status": "degraded", "checks": checks}
    return 200, {"status": "healthy", "checks": checks}
