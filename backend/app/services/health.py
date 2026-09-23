"""
INDRA Platform — Dependency health checks for GET /healthz

Each check actually talks to its dependency. They run concurrently, each capped
at CHECK_TIMEOUT_SECONDS, so a hung dependency costs at most that long.

    status      HTTP  when
    healthy     200   every check is up
    degraded    200   a non-critical check is down (Redis, Open-Meteo, outbox backlog)
    unhealthy   503   a critical check is down (Postgres, Kafka/Redpanda)

Postgres and Kafka are critical because without either a submitted report is
not stored or not processed. Redis is not: since Day 6 it holds the weather
cache and the broadcast-dedup set, and both fall back to process memory when it
is gone (`services/cache.py`), so losing it costs cross-restart memory and
nothing else. Open-Meteo being down only marks the weather factor offline in new
receipts. Both therefore degrade rather than fail.

The outbox backlog is the reports stored but not yet published to Kafka. It is
non-critical because nothing is lost while they wait — that is what the outbox
is for — but a report waiting more than a minute is one the pipeline has not
seen, and the operator should know how many and for how long.

A check is "down" if it raises, returns False, or times out. A check may also
return `(ok, details)`; the details are added to its entry in the body.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

import httpx
from sqlalchemy import text

from app.core.config import get_settings

settings = get_settings()

CHECK_TIMEOUT_SECONDS = 2.0

# How long a stored report may wait for Kafka before /healthz says degraded.
# The relay retries every 2 s, so a healthy backlog is seconds old at most.
OUTBOX_MAX_AGE_SECONDS = 60.0

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
    """
    Reachable **and** migrated.

    `SELECT 1` alone was not enough, and the T14 cold-start rehearsal proved it:
    after `docker compose down -v`, with `alembic upgrade head` accidentally
    skipped, Postgres answered `SELECT 1` happily and `/healthz` reported
    **healthy** against a database with no `raw_reports` table at all. The first
    citizen report then failed with a 503 and `UndefinedTableError`. A health check
    that goes green on a schemaless database is telling the operator the one thing
    they must not be told before a demo.

    So this also confirms the table the whole platform writes to actually exists.
    It is a catalogue lookup, not a table scan, so it costs nothing.
    """
    from app.core.database import engine

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        # raw_reports is what every report is written to; outbox is written in
        # the same transaction since Phase 1, so a database without it cannot
        # store a report either.
        for table in ("raw_reports", "outbox"):
            migrated = await conn.execute(text(f"SELECT to_regclass('public.{table}')"))
            if migrated.scalar() is None:
                raise RuntimeError(
                    "database is reachable but not migrated — run `alembic upgrade head`"
                )
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


async def check_outbox_backlog() -> Tuple[bool, Dict[str, Any]]:
    """How many stored reports are waiting for Kafka, and how long the oldest has waited."""
    from app.core.database import engine

    async with engine.connect() as conn:
        count, oldest = (
            await conn.execute(
                text("""
                    SELECT count(*),
                           COALESCE(EXTRACT(EPOCH FROM NOW() - min(created_at)), 0)
                    FROM outbox
                    WHERE published_at IS NULL
                """)
            )
        ).one()
    details: Dict[str, Any] = {"count": int(count), "oldest_s": round(float(oldest), 1)}
    if float(oldest) > OUTBOX_MAX_AGE_SECONDS:
        details["error"] = (
            f"{int(count)} report(s) waiting for Kafka, the oldest for {float(oldest):.0f} s "
            f"(limit {OUTBOX_MAX_AGE_SECONDS:.0f} s)"
        )
        return False, details
    return True, details


async def check_weather_api() -> bool:
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        resp = await client.get(settings.OPEN_METEO_API_URL, params=_WEATHER_PROBE_PARAMS)
    resp.raise_for_status()
    return True


# name → (check, critical)
CHECKS: Dict[str, Tuple[Callable[[], Awaitable[Any]], bool]] = {
    "database": (check_database, True),
    "streaming_bus": (check_streaming_bus, True),
    "redis": (check_redis, False),
    "weather_api": (check_weather_api, False),
    "outbox_backlog": (check_outbox_backlog, False),
}


async def _run(name: str, check: Callable[[], Awaitable[Any]]) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        outcome = await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        ok, details = outcome if isinstance(outcome, tuple) else (outcome, {})
        result: Dict[str, Any] = {"status": "up" if ok else "down", **details}
        if not ok and "error" not in result:
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
