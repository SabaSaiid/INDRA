"""
GET /api/feed/recent — reports, events and official warnings on one clock (BUG-071).

The feed read raw_reports alone and printed each report's UTC clock time as if
it were local, so a report filed at 20:27 IST showed as "14:57". On a day with
no citizen reports it showed one stale line while the SACHET poller stored a
hundred warnings nobody saw arrive.
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

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
        await db.execute(text("DELETE FROM agency_alerts WHERE sender = 'TEST-FEED'"))
        await db.commit()
        try:
            yield db
        finally:
            await wipe_event_tables(db)
            await db.execute(text("DELETE FROM agency_alerts WHERE sender = 'TEST-FEED'"))
            await db.commit()


async def _report(db, created_at: str, body: str = "Water rising near the underpass"):
    rid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO raw_reports
                (id, source_type, raw_text, latitude, longitude, geom_point,
                 district, state, created_at)
            VALUES (CAST(:id AS uuid), 'CITIZEN_APP', :t, 25.5941, 85.1376,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326),
                    'Patna', 'Bihar', CAST(:at AS timestamptz))
        """),
        {"id": str(rid), "t": body, "at": created_at},
    )
    return str(rid)


async def _warning(db, sent_at: str, expires: str, headline: str = "Heavy rain likely"):
    aid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO agency_alerts
                (id, identifier, source_feed, sender, event, severity, headline,
                 area_desc, sent_at, expires_at, fetched_at)
            VALUES (CAST(:id AS uuid), :ident, 'SACHET', 'TEST-FEED', 'Heavy Rain',
                    'HIGH', :h, 'Patna district of Bihar',
                    CAST(:sent AS timestamptz), CAST(:exp AS timestamptz), NOW())
        """),
        {"id": str(aid), "ident": f"test-feed-{aid}", "h": headline, "sent": sent_at, "exp": expires},
    )
    return f"warning-{aid}"


class TestFeedClock:
    async def test_time_is_ist_and_at_keeps_the_instant(self, api, clean_db):
        await _report(clean_db, "2026-09-21T14:57:00+00:00")
        await clean_db.commit()

        item = (await api.get("/api/feed/recent?include=reports")).json()[0]
        assert item["time"] == "20:27"
        assert item["at"].startswith("2026-09-21T14:57:00")
        assert item["place"] == "Patna, Bihar"
        assert item["status"] == "pending"


class TestFeedStreams:
    async def test_a_warning_in_force_is_in_the_feed(self, api, clean_db):
        wid = await _warning(clean_db, "now", "2099-01-01T00:00:00+00:00")
        await clean_db.commit()

        rows = (await api.get("/api/feed/recent?limit=50&include=warnings")).json()
        item = next(r for r in rows if r["id"] == wid)
        assert item["kind"] == "warning"
        assert item["sourceLabel"] == "TEST-FEED"
        assert item["severity"] == "HIGH"

    async def test_an_expired_warning_is_not(self, api, clean_db):
        wid = await _warning(clean_db, "2026-09-01T00:00:00+00:00", "2026-09-01T06:00:00+00:00")
        await clean_db.commit()

        rows = (await api.get("/api/feed/recent?limit=50&include=warnings")).json()
        assert wid not in [r["id"] for r in rows]

    async def test_streams_merge_newest_first(self, api, clean_db):
        older = await _report(clean_db, "2026-09-20T10:00:00+00:00", "Older report")
        newer = await _report(clean_db, "2026-09-22T10:00:00+00:00", "Newer report")
        wid = await _warning(clean_db, "2026-09-21T10:00:00+00:00", "2099-01-01T00:00:00+00:00")
        await clean_db.commit()

        rows = (await api.get("/api/feed/recent?limit=50")).json()
        ours = [r["id"] for r in rows if r["id"] in {older, newer, wid}]
        assert ours == [newer, wid, older]

    async def test_include_reports_leaves_warnings_out(self, api, clean_db):
        await _report(clean_db, "2026-09-22T10:00:00+00:00")
        await _warning(clean_db, "now", "2099-01-01T00:00:00+00:00")
        await clean_db.commit()

        rows = (await api.get("/api/feed/recent?limit=50&include=reports")).json()
        assert {r["kind"] for r in rows} == {"report"}
