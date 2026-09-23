"""
Shared pytest fixtures for the INDRA backend suite.

Tests that need Postgres/Redpanda must carry the `@pytest.mark.integration`
marker so `pytest -m "not integration"` stays runnable on a machine with no
Docker.

**The suite never touches the dev database.** Integration fixtures truncate
audit_logs, raw_reports and verified_events, so they run against a separate
`indra_test` database on the same container. `app.core.database` builds its
engine at import time from DATABASE_URL, so the override below has to happen
before *any* `app.` import — including the ones further down this file.
"""

import os

# Must stay above every app import. See the module docstring.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://indra_user:indra_password@localhost:5433/indra_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.dedup import DedupService, _get_embedding_model
from app.services.fusion_engine import FusionEngine


# ── Test database bootstrap ────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _ensure_test_database(url: str) -> None:
    """Create the test database (with PostGIS) if it does not exist yet."""
    import asyncpg
    from sqlalchemy.engine import make_url

    u = make_url(url)
    if not u.database or u.database == "indra_db":
        raise RuntimeError(f"refusing to use {u.database!r} as the test database")

    conn_args = dict(
        user=u.username, password=u.password, host=u.host, port=u.port, timeout=5
    )
    admin = await asyncpg.connect(database="postgres", **conn_args)
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", u.database
        )
        if not exists:
            await admin.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await admin.close()

    db = await asyncpg.connect(database=u.database, **conn_args)
    try:
        await db.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    finally:
        await db.close()


def pytest_collection_modifyitems(config, items):
    """
    Once per session, and only if integration tests were collected: create
    `indra_test` if absent and migrate it to head. If Postgres is unreachable
    the integration tests are left to fail on their own, as before.
    """
    if not any(item.get_closest_marker("integration") for item in items):
        return
    try:
        asyncio.run(_ensure_test_database(TEST_DATABASE_URL))
    except (OSError, asyncio.TimeoutError) as e:
        print(f"\n[conftest] test database unreachable ({e}); integration tests will fail")
        return
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )


# ── Cache isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_cache():
    """
    The whole suite runs on the cache's in-memory fallback, cleared between
    tests.

    Not for want of a Redis — one is usually running on this machine, which is
    exactly the problem. The broadcast-dedup keys live for 24 hours, so a shared
    Redis would carry report ids from one test run into the next and make the
    suite pass or fail depending on what ran yesterday. It would also make
    `pytest -m "not integration"` require a container.

    The Redis path itself is covered by `test_cache.py`, which opts back in
    deliberately and is marked `integration`.
    """
    from app.services import cache

    cache.use_memory_only(True)
    cache.clear()
    yield
    cache.clear()
    cache.use_memory_only(False)


# ── Kafka isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_kafka_publisher():
    """
    Every test starts with no process producer.

    The test client does not run the lifespan, so nothing starts one: a report
    submitted in a test is stored with its outbox row and not published, and
    no test reaches the local broker by accident. A test that wants a publish
    injects a fake with `kafka.set_publisher()`; this forgets it afterwards.
    """
    from app.services import kafka

    kafka.set_publisher(None)
    yield
    kafka.set_publisher(None)


# ── Service fixtures (no DB) ───────────────────────────────────────────────────

@pytest.fixture
def fusion() -> FusionEngine:
    """A bare FusionEngine — it holds no state and needs no database."""
    return FusionEngine()


@pytest.fixture
def dedup() -> DedupService:
    """A bare DedupService — the embedding model is loaded lazily and cached."""
    return DedupService()


# ── Embedding-model availability ───────────────────────────────────────────────

def embeddings_available() -> bool:
    """
    True when sentence-transformers loaded successfully.

    Dedup has two text-similarity paths with different thresholds (cosine 0.88
    vs Levenshtein 0.75), so a handful of tests have to know which one is live
    rather than hardcoding an expectation.
    """
    return _get_embedding_model() is not None


requires_embeddings = pytest.mark.skipif(
    not embeddings_available(),
    reason="sentence-transformers model unavailable — dedup is on the Levenshtein fallback",
)


# ── Shared geo/time constants ──────────────────────────────────────────────────

PATNA_LAT = 25.5941
PATNA_LNG = 85.1376
T0 = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)


# ── HTTP client ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """
    An httpx.AsyncClient bound directly to the ASGI app.

    Note this does NOT run the lifespan, so the Kafka consumer task and the
    PostGIS check in init_db() never fire — which is what makes it usable
    without Docker. Endpoints that hit the DB go through app.core.demo:
    demo data if DEMO_MODE is true, HTTP 503 if it is false.
    """
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Database cleanup ───────────────────────────────────────────────────────────

async def wipe_event_tables(session) -> None:
    """
    Empty audit_logs, the outbox, raw_reports and verified_events, then commit.

    audit_logs has to go first and has to be a TRUNCATE: its rows reference
    verified_events, and trg_audit_immutable is a row-level BEFORE DELETE
    trigger, so `DELETE FROM audit_logs` raises. TRUNCATE fires no row triggers.
    Neither the trigger nor the hash chain can stop or detect a table owner
    emptying the ledger this way — see the "cannot prove" note in
    app/services/audit.py. Fine for a disposable test database.
    """
    from sqlalchemy import text

    await session.execute(text("TRUNCATE audit_logs"))
    # The outbox holds each report's message; a test that counts unpublished
    # rows must not see the last test's.
    await session.execute(text("DELETE FROM outbox"))
    await session.execute(text("DELETE FROM raw_reports"))
    await session.execute(text("DELETE FROM verified_events"))
    await session.commit()
