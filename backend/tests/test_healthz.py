"""
Day 4 T6 — GET /healthz reports real dependency state.

Unit level: each check function is replaced, so no Docker is needed. The live
drills (stop postgres / redis) are run by hand and recorded in the day file.
"""

import asyncio
import time

import pytest

from app.services import health


def _up():
    async def check():
        return True
    return check


def _raises(exc=ConnectionRefusedError("refused")):
    async def check():
        raise exc
    return check


def _false():
    async def check():
        return False
    return check


def _hangs():
    async def check():
        await asyncio.sleep(10)
        return True
    return check


@pytest.fixture
def checks(monkeypatch):
    """All four checks up; tests override one at a time."""
    patched = {name: (_up(), critical) for name, (_, critical) in health.CHECKS.items()}
    monkeypatch.setattr(health, "CHECKS", patched)

    def override(name, fn):
        patched[name] = (fn, patched[name][1])

    return override


async def test_all_up_is_200_healthy(client, checks):
    r = await client.get("/healthz")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert set(body["checks"]) == {"database", "streaming_bus", "redis", "weather_api"}
    assert all(c["status"] == "up" for c in body["checks"].values())
    assert all(c["latency_ms"] >= 0 for c in body["checks"].values())
    assert "database" not in body and "streaming_bus" not in body


async def test_database_error_is_503(client, checks):
    checks("database", _raises())
    r = await client.get("/healthz")

    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy"
    db = r.json()["checks"]["database"]
    assert db["status"] == "down"
    assert "ConnectionRefusedError" in db["error"]


async def test_hung_database_is_503_within_the_timeout(client, checks):
    checks("database", _hangs())
    start = time.perf_counter()
    r = await client.get("/healthz")
    elapsed = time.perf_counter() - start

    assert r.status_code == 503
    assert elapsed < 2.5
    assert "timeout" in r.json()["checks"]["database"]["error"]


async def test_redis_down_is_200_degraded(client, checks):
    checks("redis", _raises())
    r = await client.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


async def test_weather_down_is_200_degraded(client, checks):
    checks("weather_api", _raises())
    r = await client.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


async def test_kafka_false_is_503(client, checks):
    checks("streaming_bus", _false())
    r = await client.get("/healthz")

    assert r.status_code == 503
    assert r.json()["checks"]["streaming_bus"]["status"] == "down"
