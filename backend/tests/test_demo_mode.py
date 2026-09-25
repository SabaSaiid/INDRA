"""
Day 2 T3 — demo data is served only when DEMO_MODE says so, and always logged.

The database is replaced with a fake session that returns no rows (or raises),
so each endpoint's fallback path is exercised without Docker.
"""

import logging

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.core.database import get_db

LIST_ENDPOINTS = [
    "/api/events",
    "/api/events/distribution",
    "/api/feed/recent",
    "/api/teams",
    "/api/reports/trend",
    # Added 20 Sep. Its absence from this list is why the endpoint kept serving
    # invented KPIs through the Day 2 demo gate and beyond: the hole was never
    # tested, so nothing caught it. It carries the dashboard's headline numbers,
    # which made it the worst place in the API for the gap to be.
    "/api/dashboard/summary",
    "/api/geo/heatmap",
]


class _EmptyResult:
    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def mappings(self):
        return self

    def all(self):
        return []

    def first(self):
        return None


class EmptySession:
    async def execute(self, *args, **kwargs):
        return _EmptyResult()


class BrokenSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("connection refused")


def _api_with(session_cls):
    @pytest_asyncio.fixture
    async def _fixture():
        import httpx

        from app.main import app

        async def _db():
            yield session_cls()

        app.dependency_overrides[get_db] = _db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
        finally:
            app.dependency_overrides.pop(get_db, None)

    return _fixture


empty_api = _api_with(EmptySession)
broken_api = _api_with(BrokenSession)


@pytest.fixture
def demo_mode(monkeypatch):
    def _set(value: bool):
        monkeypatch.setattr(get_settings(), "DEMO_MODE", value)

    return _set


def _is_empty(path, body):
    """
    True when a 200 response carries no data — in whatever shape the endpoint uses.

    Most read endpoints answer with a bare list. Two do not: /api/geo/heatmap
    wraps its cells in an object that also reports the window and resolution it
    was asked for, and /api/dashboard/summary is a fixed set of KPI keys, whose
    empty form is every count at zero. Zero is the truthful answer to "how many
    reports are there" on a fresh database; 1,248 is not.
    """
    if path == "/api/geo/heatmap":
        return body["cells"] == []
    if path == "/api/dashboard/summary":
        return all(value == 0 for value in body.values())
    return body == []


def _warned(caplog, needle):
    return any(r.levelno == logging.WARNING and needle in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_demo_mode_on_empty_db_serves_demo_data_with_warning(empty_api, demo_mode, caplog, path):
    demo_mode(True)
    if path == "/api/reports/trend":
        pytest.skip("trend's generate_series always yields rows; its fallback is DB-error only")

    r = await empty_api.get(path)

    assert r.status_code == 200
    assert len(r.json()) > 0
    assert _warned(caplog, "serving demo data")


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_demo_mode_off_empty_db_returns_nothing_invented(empty_api, demo_mode, caplog, path):
    """
    A working stack with an empty database answers "nothing", never a plausible
    number. What "nothing" looks like depends on the endpoint's shape, so the
    assertion is about emptiness rather than a literal [].
    """
    demo_mode(False)
    if path == "/api/reports/trend":
        pytest.skip("trend's generate_series always yields rows; its fallback is DB-error only")

    r = await empty_api.get(path)

    assert r.status_code == 200
    assert _is_empty(path, r.json()), r.json()
    assert _warned(caplog, "no rows")


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_demo_mode_off_db_error_is_503_not_fake_success(broken_api, demo_mode, caplog, path):
    demo_mode(False)

    r = await broken_api.get(path)

    assert r.status_code == 503
    assert _warned(caplog, "returning 503")


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_demo_mode_on_db_error_serves_demo_data_with_warning(broken_api, demo_mode, caplog, path):
    demo_mode(True)

    r = await broken_api.get(path)

    assert r.status_code == 200
    assert len(r.json()) > 0
    assert _warned(caplog, "serving demo data")


@pytest.mark.parametrize("path", ["/api/events/INDRA-DOES-NOT-EXIST", "/api/teams/NO-SUCH-TEAM"])
async def test_detail_endpoints_404_instead_of_a_demo_record_when_demo_mode_off(empty_api, demo_mode, path):
    demo_mode(False)

    r = await empty_api.get(path)

    assert r.status_code == 404


async def test_event_detail_demo_fallback_still_works_when_demo_mode_on(empty_api, demo_mode):
    demo_mode(True)

    r = await empty_api.get("/api/events/INDRA-DOES-NOT-EXIST")

    assert r.status_code == 200
    assert r.json()["event_code"]


def test_the_demo_kpis_are_at_least_possible():
    """
    BUG-069: citizen_reports was 8,421 against total_reports 1,248. Demo data
    is served only with DEMO_MODE on, but it must never be impossible.
    """
    from app.api.dashboard import DEMO_KPIS

    assert DEMO_KPIS["citizen_reports"] <= DEMO_KPIS["total_reports"]
    assert DEMO_KPIS["critical_events"] <= DEMO_KPIS["verified_events"]
