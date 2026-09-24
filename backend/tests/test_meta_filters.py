"""
Phase 1 T6 — GET /api/meta/filters: the filter bar's options, from the data.

Uses T5's twelve-event fixture, so every count here can be checked against the
events that produced it.
"""

import httpx
import pytest
import pytest_asyncio

from tests.conftest import wipe_event_tables
from tests.test_event_filters import events  # noqa: F401  (the shared fixture)

from app.api import meta
from app.core.database import async_session, get_db
from app.services import cache

pytestmark = pytest.mark.integration


class CountingSession:
    """The real session, counting the queries the endpoint runs."""

    def __init__(self, session):
        self._session = session
        self.queries = 0

    async def execute(self, *args, **kwargs):
        self.queries += 1
        return await self._session.execute(*args, **kwargs)


@pytest_asyncio.fixture
async def counted():
    from app.main import app

    async with async_session() as session:
        counting = CountingSession(session)

        async def _db():
            yield counting

        app.dependency_overrides[get_db] = _db
        try:
            yield counting
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def options(api):
    r = await api.get("/api/meta/filters")
    assert r.status_code == 200, r.text
    return r.json()


def as_counts(entries):
    return {e["value"]: e["count"] for e in entries}


async def test_an_empty_database_offers_nothing(api):
    async with async_session() as db:
        await wipe_event_tables(db)

    body = await options(api)

    for key in ("event_types", "families", "review_statuses", "severities", "source_types", "states"):
        assert body[key] == [], key
    assert body["date_min"] is None and body["date_max"] is None
    assert body["generated_at"]


async def test_the_counts_are_the_events_counts(api, events):
    body = await options(api)

    assert as_counts(body["event_types"]) == {"URBAN_FLOOD": 4, "HEATWAVE": 3, "THUNDERSTORM": 2, "FOG": 2}
    assert as_counts(body["families"]) == {"water": 4, "convective": 2, "thermal": 3, "visibility": 2}
    assert as_counts(body["severities"]) == {"ADVISORY": 2, "MODERATE": 3, "HIGH": 4, "CRITICAL": 2}
    assert as_counts(body["source_types"]) == {"CITIZEN_APP": 10, "OFFICIAL_DISPATCH": 2}
    assert (body["date_min"], body["date_max"]) == ("2026-09-18", "2026-09-22")


async def test_event_types_carry_their_label_and_family(api, events):
    body = await options(api)
    flood = next(t for t in body["event_types"] if t["value"] == "URBAN_FLOOD")
    assert flood == {"value": "URBAN_FLOOD", "label": "Flood", "family": "water", "count": 4}


async def test_rejected_is_offered_as_a_status_and_counted_nowhere_else(api, events):
    body = await options(api)

    assert as_counts(body["review_statuses"]) == {
        "QUARANTINED": 5, "PENDING_HUMAN_REVIEW": 3, "HUMAN_APPROVED": 3, "REJECTED": 1,
    }
    # E12, the rejected FOG event in Patna, is in no other count.
    assert as_counts(body["event_types"])["FOG"] == 2
    bihar = next(s for s in body["states"] if s["name"] == "Bihar")
    assert bihar["count"] == 4


async def test_a_null_district_counts_for_its_state_and_is_never_a_district(api, events):
    body = await options(api)
    bihar = next(s for s in body["states"] if s["name"] == "Bihar")

    assert bihar["count"] == 4                     # E01, E04, E08 and E10 (no district)
    assert bihar["districts"] == [{"name": "Patna", "count": 2}, {"name": "Gaya", "count": 1}]
    assert all(d["name"] for s in body["states"] for d in s["districts"])


async def test_states_come_biggest_first(api, events):
    body = await options(api)
    assert [(s["name"], s["count"]) for s in body["states"]] == [
        ("Bihar", 4), ("Delhi", 4), ("Maharashtra", 3),
    ]


async def test_a_second_call_within_60_seconds_runs_no_query(api, events, counted):
    await options(api)
    first = counted.queries
    assert first > 0

    await options(api)
    assert counted.queries == first


async def test_after_60_seconds_it_is_computed_again(api, events, counted, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(meta, "_clock", lambda: now[0])

    await options(api)
    first = counted.queries
    now[0] += 61
    await options(api)

    assert counted.queries == 2 * first


async def test_with_redis_down_it_is_served_from_memory(api, events):
    # The suite runs on the in-memory fallback (conftest), which is exactly
    # what the cache uses when Redis is down.
    assert cache.backend() == "memory"
    first = await options(api)
    second = await options(api)
    assert second == first


async def test_a_database_error_is_503_never_invented_options(api):
    from app.main import app

    class Broken:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    async def _db():
        yield Broken()

    app.dependency_overrides[get_db] = _db
    try:
        r = await api.get("/api/meta/filters")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 503
