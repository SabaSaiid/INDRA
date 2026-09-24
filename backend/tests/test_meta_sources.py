"""
GET /api/meta/sources — the Phase 2 T2 contract.

Written before feed_status existed, when status was read from the newest row
each feed wrote. Pollers now report a heartbeat (`basis: heartbeat`, covered in
test_feed_status.py); push feeds still have none and are never stale for being
quiet (`basis: push`).
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.config import get_settings
from app.core.database import async_session

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def clean_db():
    async with async_session() as db:
        await wipe_event_tables(db)
        try:
            yield db
        finally:
            await wipe_event_tables(db)


async def _feeds(api):
    body = (await api.get("/api/meta/sources")).json()
    return {f["feed"]: f for f in body["feeds"]}


async def test_every_feed_is_listed_with_the_contract_fields(api, clean_db):
    feeds = await _feeds(api)
    assert set(feeds) == {
        "citizen", "official", "sachet", "open_meteo", "metar", "mastodon", "google_news",
    }
    for f in feeds.values():
        assert {"feed", "kind", "enabled", "status", "last_success_at", "last_error",
                "rows_24h", "rows_total", "poll_interval_s"} <= set(f)


async def test_citizen_rows_24h_counts_citizen_reports_only(api, clean_db):
    for source, age in (("CITIZEN_APP", "1 hour"), ("CITIZEN_APP", "3 days"), ("OFFICIAL_DISPATCH", "1 hour")):
        await clean_db.execute(
            text(f"""
                INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, created_at)
                VALUES (CAST(:id AS uuid), CAST(:src AS source_type_enum), 'Water on the road',
                        25.59, 85.13, now() - INTERVAL '{age}')
            """),
            {"id": str(uuid.uuid4()), "src": source},
        )
    await clean_db.commit()

    feeds = await _feeds(api)
    assert feeds["citizen"]["rows_24h"] == 1
    assert feeds["citizen"]["rows_total"] == 2
    assert feeds["official"]["rows_24h"] == 1


async def test_a_quiet_push_feed_is_ok_not_stale(api, clean_db):
    feeds = await _feeds(api)
    assert feeds["citizen"]["status"] == "ok"
    assert feeds["citizen"]["basis"] == "push"


async def test_a_disabled_poller_says_disabled(api, clean_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SACHET_POLLER_ENABLED", False)
    feeds = await _feeds(api)
    assert feeds["sachet"]["status"] == "disabled"
    assert feeds["sachet"]["enabled"] is False
