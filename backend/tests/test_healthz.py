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
    """All six checks up; tests override one at a time."""
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
    assert set(body["checks"]) == {
        "database", "streaming_bus", "redis", "weather_api", "outbox_backlog", "object_store",
    }
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


async def test_object_store_down_is_200_degraded(client, checks):
    """Phase 2 T1: the platform can lose its object store without breaking."""
    checks("object_store", _raises())
    r = await client.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["object_store"]["status"] == "down"


async def test_kafka_false_is_503(client, checks):
    checks("streaming_bus", _false())
    r = await client.get("/healthz")

    assert r.status_code == 503
    assert r.json()["checks"]["streaming_bus"]["status"] == "down"


# ── Day 5: a reachable but unmigrated database is not healthy ──────────────────

async def test_an_unmigrated_database_is_reported_down(monkeypatch):
    """
    Found by the T14 cold-start rehearsal.

    After `docker compose down -v`, with `alembic upgrade head` skipped, Postgres
    answered SELECT 1 and /healthz reported **healthy** against a database with no
    raw_reports table. The first citizen report then failed with a 503 and
    UndefinedTableError. Going green on a schemaless database tells the operator
    the one thing they must not be told before a demo.

    check_database now also confirms the table exists, so this asserts the failure
    is raised rather than swallowed into a pass.
    """
    from sqlalchemy import text as sa_text

    from app.services import health

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class _Conn:
        async def execute(self, statement, *a, **k):
            # SELECT 1 succeeds; the to_regclass lookup reports "no such table".
            if "to_regclass" in str(statement):
                return _Result(None)
            return _Result(1)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    import app.core.database as database_module

    monkeypatch.setattr(database_module, "engine", _Engine())

    with pytest.raises(RuntimeError, match="not migrated"):
        await health.check_database()


async def test_a_migrated_database_is_healthy(monkeypatch):
    """The same path, with the table present, must pass."""
    from app.services import health

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class _Conn:
        async def execute(self, statement, *a, **k):
            if "to_regclass" in str(statement):
                return _Result("raw_reports")
            return _Result(1)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    import app.core.database as database_module

    monkeypatch.setattr(database_module, "engine", _Engine())

    assert await health.check_database() is True


# ── Phase 1 T3: the outbox backlog ─────────────────────────────────────────────

def _backlog(ok, **details):
    async def check():
        return ok, details
    return check


async def test_a_check_can_report_details_beside_its_status(client, checks):
    checks("outbox_backlog", _backlog(True, count=2, oldest_s=1.5))
    r = await client.get("/healthz")

    assert r.status_code == 200
    backlog = r.json()["checks"]["outbox_backlog"]
    assert (backlog["status"], backlog["count"], backlog["oldest_s"]) == ("up", 2, 1.5)
    assert backlog["critical"] is False


async def test_a_stale_backlog_is_200_degraded_never_503(client, checks):
    """Nothing is lost while reports wait; the operator is told, the platform stays up."""
    checks("outbox_backlog", _backlog(False, count=1, oldest_s=90.0, error="waiting 90 s"))
    r = await client.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    backlog = r.json()["checks"]["outbox_backlog"]
    assert (backlog["status"], backlog["error"]) == ("down", "waiting 90 s")


@pytest.mark.integration
async def test_a_report_waiting_90_seconds_makes_healthz_degraded(client, checks):
    from sqlalchemy import text

    from tests.conftest import wipe_event_tables

    from app.core.database import async_session

    checks("outbox_backlog", health.check_outbox_backlog)
    async with async_session() as db:
        await wipe_event_tables(db)
        await db.execute(text("""
            INSERT INTO outbox (topic, key, payload, created_at)
            VALUES ('indra.raw.reports', 'r1', '{}', NOW() - INTERVAL '90 seconds')
        """))
        await db.commit()
        try:
            r = await client.get("/healthz")
        finally:
            await wipe_event_tables(db)

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    backlog = r.json()["checks"]["outbox_backlog"]
    assert backlog["status"] == "down"
    assert backlog["count"] == 1
    assert backlog["oldest_s"] >= 90


@pytest.mark.integration
async def test_an_empty_backlog_is_up():
    from sqlalchemy import text

    from tests.conftest import wipe_event_tables

    from app.core.database import async_session

    async with async_session() as db:
        await wipe_event_tables(db)
        await db.execute(text("""
            INSERT INTO outbox (topic, key, payload, created_at, published_at)
            VALUES ('indra.raw.reports', 'done', '{}', NOW() - INTERVAL '1 hour', NOW())
        """))
        await db.commit()
        try:
            ok, details = await health.check_outbox_backlog()
        finally:
            await wipe_event_tables(db)

    assert ok is True
    assert details == {"count": 0, "oldest_s": 0.0}
