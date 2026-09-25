"""
An empty database answers the empty result, a broken one answers 503, and an
unknown id is a 404. Never a fabricated payload.

The database is replaced with a fake session that returns no rows (or raises),
so each endpoint's empty and error paths are exercised without Docker.

Until 25 Sep this file also proved that a DEMO_MODE flag served hardcoded
events, KPIs, teams and feed items on those same paths. The flag and the data
are gone; the structural guards at the end keep them gone.
"""

import ast
import logging
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.database import get_db

LIST_ENDPOINTS = [
    "/api/events",
    "/api/events/distribution",
    "/api/feed/recent",
    "/api/teams",
    "/api/reports/trend",
    "/api/reports/recent",
    # Added 20 Sep. Its absence from this list is why the endpoint kept serving
    # invented KPIs beyond the Day 2 gate (BUG-004): the hole was never tested,
    # so nothing caught it. It carries the dashboard's headline numbers, which
    # made it the worst place in the API for the gap to be.
    "/api/dashboard/summary",
    "/api/geo/heatmap",
]

# The keys GET /api/dashboard/summary always answers with, data or not.
KPI_KEYS = {
    "total_reports", "total_reports_delta_pct",
    "verified_events", "verified_events_delta_pct",
    "critical_events", "critical_events_delta_pct",
    "citizen_reports", "citizen_reports_delta_pct",
    "awaiting_review", "active_alerts",
}

APP_DIR = Path(__file__).resolve().parents[1] / "app"


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
        return set(body) == KPI_KEYS and all(value == 0 for value in body.values())
    return body == []


def _warned(caplog, needle):
    return any(r.levelno == logging.WARNING and needle in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_empty_db_returns_nothing_invented(empty_api, caplog, path):
    """
    A working stack with an empty database answers "nothing", never a plausible
    number. What "nothing" looks like depends on the endpoint's shape, so the
    assertion is about emptiness rather than a literal [].
    """
    if path == "/api/reports/trend":
        pytest.skip("trend's generate_series always yields rows; its fallback is DB-error only")

    r = await empty_api.get(path)

    assert r.status_code == 200
    assert _is_empty(path, r.json()), r.json()
    # An empty field-reports layer is its normal state, so it is not logged.
    if path != "/api/reports/recent":
        assert _warned(caplog, "no rows")


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_db_error_is_503_not_fake_success(broken_api, caplog, path):
    r = await broken_api.get(path)

    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
    assert _warned(caplog, "returning 503")


@pytest.mark.parametrize("path", ["/api/events/INDRA-DOES-NOT-EXIST", "/api/teams/NO-SUCH-TEAM"])
async def test_detail_endpoints_404_for_unknown_ids(empty_api, path):
    r = await empty_api.get(path)

    assert r.status_code == 404


@pytest.mark.parametrize("path", ["/api/events/INDRA-DOES-NOT-EXIST", "/api/teams/NO-SUCH-TEAM"])
async def test_detail_endpoints_503_on_a_db_error(broken_api, path):
    r = await broken_api.get(path)

    assert r.status_code == 503


# ── The demo gate stays deleted ───────────────────────────────────────────────

def test_the_demo_gate_module_is_deleted():
    assert not (APP_DIR / "core" / "demo.py").exists()


def test_there_is_no_demo_mode_setting():
    from app.core.config import Settings

    assert "DEMO_MODE" not in Settings.model_fields


# Hardcoded accounts and an in-memory preference store that are still being
# moved to the database. Each is removed from this set in the change that
# deletes it; the set is then empty.
_PENDING_REMOVAL = {"DEMO_PREFERENCES"}


def test_no_module_defines_a_demo_dataset():
    """
    Scans the syntax tree, not the text, so a comment recording what was removed
    cannot trip it; a module-level DEMO_ assignment anywhere in app/ does.
    """
    found = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.startswith("DEMO_"):
                    found.add(f"{path.relative_to(APP_DIR)}:{target.id}")

    assert {name.split(":")[1] for name in found} <= _PENDING_REMOVAL, sorted(found)
