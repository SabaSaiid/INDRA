"""
An E2E backend runs only on E2E names, and only it answers /api/e2e/identity.

The Playwright suite signs in, reviews events and files reports. A backend
started with ENVIRONMENT=e2e therefore refuses to start unless its database
ends in _e2e and its Kafka topics and consumer group are the indra.e2e. /
indra-e2e- ones, and GET /api/e2e/identity, which the suite checks before it
runs, exists on that backend alone. The whole file runs without Docker.
"""

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.core.config import Settings
from app.core.database import get_db
from app.core.e2e import assert_e2e_isolated, isolation_problems

BACKEND_DIR = Path(__file__).resolve().parents[1]

# What ./start.sh e2e-backend exports.
E2E = {
    "ENVIRONMENT": "e2e",
    "DATABASE_URL": "postgresql+asyncpg://indra_user:indra_password@localhost:5433/indra_e2e",
    "KAFKA_REPORTS_TOPIC": "indra.e2e.raw.reports",
    "KAFKA_EVENTS_TOPIC": "indra.e2e.verified.events",
    "KAFKA_DLQ_TOPIC": "indra.e2e.raw.reports.dlq",
    "KAFKA_CONSUMER_GROUP": "indra-e2e-report-processor",
    "LAKE_ARCHIVE_ENABLED": "false",
}
DEV_URL = "postgresql+asyncpg://indra_user:indra_password@localhost:5433/indra_db"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**E2E, **overrides})


def _import_app(**env) -> subprocess.CompletedProcess:
    """Import app.main in a fresh interpreter, the way uvicorn would, with these settings."""
    return subprocess.run(
        [
            sys.executable, "-c",
            "from app.main import app; "
            "print('/api/e2e/identity' in app.openapi()['paths'])",
        ],
        cwd=BACKEND_DIR,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── The guard ─────────────────────────────────────────────────────────────────

def test_the_start_script_settings_are_isolated():
    assert isolation_problems(_settings()) == []
    assert_e2e_isolated(_settings())


@pytest.mark.parametrize(
    "override, named",
    [
        pytest.param({"DATABASE_URL": DEV_URL}, "DATABASE_URL", id="dev-database"),
        pytest.param(
            {"DATABASE_URL": DEV_URL.replace("indra_db", "indra_test")}, "DATABASE_URL", id="test-database"
        ),
        pytest.param({"KAFKA_REPORTS_TOPIC": "indra.raw.reports"}, "KAFKA_REPORTS_TOPIC", id="dev-reports-topic"),
        pytest.param({"KAFKA_EVENTS_TOPIC": "indra.verified.events"}, "KAFKA_EVENTS_TOPIC", id="dev-events-topic"),
        pytest.param({"KAFKA_DLQ_TOPIC": "indra.raw.reports.dlq"}, "KAFKA_DLQ_TOPIC", id="dev-dlq-topic"),
        pytest.param(
            {"KAFKA_CONSUMER_GROUP": "indra-report-processor"}, "KAFKA_CONSUMER_GROUP", id="dev-consumer-group"
        ),
        pytest.param({"LAKE_ARCHIVE_ENABLED": "true"}, "LAKE_ARCHIVE_ENABLED", id="lake-archiver-on"),
    ],
)
def test_an_e2e_backend_on_any_dev_name_refuses_to_start(override, named):
    settings = _settings(**override)

    problems = isolation_problems(settings)
    assert len(problems) == 1 and problems[0].startswith(named)
    with pytest.raises(RuntimeError, match="refusing to start an E2E backend"):
        assert_e2e_isolated(settings)


def test_the_guard_does_not_apply_outside_e2e_mode():
    assert_e2e_isolated(Settings(_env_file=None, ENVIRONMENT="development", DATABASE_URL=DEV_URL))


def test_the_app_will_not_import_as_an_e2e_backend_on_the_dev_database():
    r = _import_app(**{**E2E, "DATABASE_URL": DEV_URL})

    assert r.returncode != 0
    assert "refusing to start an E2E backend" in r.stderr
    assert "indra_db" in r.stderr
    assert "indra_password" not in r.stderr


def test_only_an_e2e_backend_mounts_the_identity_route():
    assert _import_app(**E2E).stdout.strip().endswith("True")
    # A production backend needs its own signing key since BUG-120.
    production = dict(ENVIRONMENT="production", DATABASE_URL=DEV_URL, SECRET_KEY="k" * 40)
    assert _import_app(**production).stdout.strip().endswith("False")


# ── The route ─────────────────────────────────────────────────────────────────

async def test_the_identity_route_is_a_404_on_this_backend(client):
    assert (await client.get("/api/e2e/identity")).status_code == 404


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class E2ESession:
    async def execute(self, *args, **kwargs):
        return _Scalar("indra_e2e")


class BrokenSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("connection refused")


def _identity_api(session_cls):
    @pytest_asyncio.fixture
    async def _fixture():
        from fastapi import FastAPI

        from app.api.e2e_identity import router

        app = FastAPI()
        app.include_router(router)

        async def _db():
            yield session_cls()

        app.dependency_overrides[get_db] = _db
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    return _fixture


identity_api = _identity_api(E2ESession)
broken_identity_api = _identity_api(BrokenSession)


async def test_the_identity_names_the_database_postgres_reports(identity_api):
    from app.core.config import get_settings

    settings = get_settings()

    r = await identity_api.get("/api/e2e/identity")

    assert r.status_code == 200
    assert r.json() == {
        "environment": settings.ENVIRONMENT,
        "database": "indra_e2e",
        "reports_topic": settings.KAFKA_REPORTS_TOPIC,
        "consumer_group": settings.KAFKA_CONSUMER_GROUP,
    }


async def test_the_identity_on_a_db_error_is_503(broken_identity_api):
    r = await broken_identity_api.get("/api/e2e/identity")

    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
