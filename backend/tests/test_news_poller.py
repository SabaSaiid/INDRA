"""
Phase 2 T5 — the Google News poller against the test database.

Google News is replaced by httpx's MockTransport serving the two feeds saved
on 24 Sep (100 items each). `now` is passed in, so "stale" is decided against
a fixed clock.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.config import get_settings
from app.core.database import async_session
from app.services.news_rss import parse_feed
from app.workers import news_poller
from app.workers.news_poller import item_to_report, poll_once

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures"
ENGLISH = (FIXTURES / "google_news_imd_heavy_rain.xml").read_bytes()
HINDI = (FIXTURES / "google_news_hi_heavy_rain.xml").read_bytes()
# After the newest item in either file, so nothing is in the future.
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


async def _no_sleep(_seconds):
    return None


def _item(guid, title, publisher="The Hindu", pub="Thu, 24 Sep 2026 06:00:00 GMT"):
    return (
        f"<item><title>{title} - {publisher}</title><link>https://news.google.com/{guid}</link>"
        f"<guid isPermaLink='false'>{guid}</guid><pubDate>{pub}</pubDate>"
        f"<source url='https://www.thehindu.com'>{publisher}</source></item>"
    )


def _feed(*items):
    return ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()


@pytest.fixture
def queries(monkeypatch):
    def set_queries(en="IMD heavy rain", hi=""):
        monkeypatch.setattr(get_settings(), "NEWS_QUERIES_EN", en)
        monkeypatch.setattr(get_settings(), "NEWS_QUERIES_HI", hi)
    set_queries()
    return set_queries


class FakeNews:
    def __init__(self):
        self.by_query = {}
        self.requests = []

    def handler(self, request: httpx.Request):
        q = request.url.params.get("q")
        self.requests.append((q, dict(request.url.params)))
        body = self.by_query.get(q)
        if isinstance(body, httpx.Response):
            return body
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body, headers={"Content-Type": "application/rss+xml"})


@pytest.fixture
def fake():
    return FakeNews()


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


async def _poll(db, fake, now=NOW):
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as client:
        return await poll_once(db, client, sleep=_no_sleep, now=now)


async def _rows(db):
    return (await db.execute(text("""
        SELECT CAST(source_type AS text) AS source_type, platform, raw_text, source_meta,
               observed_at, external_id, docket, place_precision
        FROM raw_reports ORDER BY observed_at
    """))).mappings().all()


# ── T5's table ─────────────────────────────────────────────────────────────────

async def test_the_english_fixture_is_stored(db, fake, queries):
    fake.by_query["IMD heavy rain"] = ENGLISH
    result = await _poll(db, fake)
    rows = await _rows(db)

    distinct = {(i.publisher, i.headline_key) for i in parse_feed(ENGLISH)}
    assert result.seen == 100
    assert result.written == len(rows) == len(distinct)
    assert {(r["source_type"], r["platform"]) for r in rows} == {("NEWS_MEDIA", "google_news")}
    publishers = {r["source_meta"]["publisher"] for r in rows}
    assert {"Telangana Today", "The Hindu"} <= publishers
    assert all(r["observed_at"].utcoffset() == timedelta(0) for r in rows)
    assert all(r["docket"] is None for r in rows)


async def test_only_headline_link_and_publisher_are_kept(db, fake, queries):
    fake.by_query["IMD heavy rain"] = ENGLISH
    await _poll(db, fake)
    for row in await _rows(db):
        assert "\n" not in row["raw_text"]  # the headline alone: no description in this feed
        assert row["source_meta"]["url"].startswith("https://news.google.com/")
        assert row["source_meta"]["publisher_domain"]


async def test_the_same_guid_under_two_queries_is_one_row(db, fake, queries):
    queries(en="IMD warning,IMD heavy rain")
    item = _item("guid-1", "IMD issues red alert for Telangana")
    fake.by_query["IMD warning"] = _feed(item)
    fake.by_query["IMD heavy rain"] = _feed(item)
    result = await _poll(db, fake)
    assert result.seen == 2
    assert result.written == 1
    assert len(await _rows(db)) == 1


async def test_the_same_headline_from_the_same_publisher_under_a_new_guid_is_one_row(db, fake, queries):
    fake.by_query["IMD heavy rain"] = _feed(_item("guid-1", "IMD issues red alert for Telangana"))
    await _poll(db, fake)
    fake.by_query["IMD heavy rain"] = _feed(_item("guid-2", "IMD issues RED alert for Telangana!"))
    result = await _poll(db, fake)
    assert result.written == 0
    assert len(await _rows(db)) == 1


async def test_the_same_headline_from_another_publisher_is_its_own_row(db, fake, queries):
    fake.by_query["IMD heavy rain"] = _feed(
        _item("guid-1", "IMD issues red alert for Telangana", publisher="The Hindu"),
        _item("guid-2", "IMD issues red alert for Telangana", publisher="Telangana Today"),
    )
    assert (await _poll(db, fake)).written == 2


@pytest.mark.parametrize(
    "age_hours, stale",
    [(47, False), (48, False), (49, True)],
)
async def test_an_item_older_than_48_hours_is_stored_stale(db, fake, queries, age_hours, stale):
    pub = (NOW - timedelta(hours=age_hours)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    fake.by_query["IMD heavy rain"] = _feed(_item("guid-old", "Old floods in Assam", pub=pub))
    await _poll(db, fake)
    (row,) = await _rows(db)
    assert row["source_meta"]["stale"] is stale


async def test_the_hindi_fixture_keeps_devanagari_and_says_hi(db, fake, queries):
    queries(en="", hi="भारी बारिश")
    fake.by_query["भारी बारिश"] = HINDI
    result = await _poll(db, fake)

    params = fake.requests[0][1]
    assert (params["hl"], params["gl"], params["ceid"]) == ("hi", "IN", "IN:hi")
    rows = await _rows(db)
    assert result.written == len(rows) > 0
    assert any("भारी बारिश" in r["raw_text"] for r in rows)
    assert {r["source_meta"]["language"] for r in rows} == {"hi"}


async def test_english_queries_use_the_indian_edition(db, fake, queries):
    fake.by_query["IMD heavy rain"] = _feed()
    await _poll(db, fake)
    params = fake.requests[0][1]
    assert (params["hl"], params["gl"], params["ceid"]) == ("en-IN", "IN", "IN:en")


async def test_malformed_xml_is_a_warning_and_a_failed_query(db, fake, queries, caplog):
    queries(en="broken,IMD heavy rain")
    fake.by_query["broken"] = b"<rss><channel><item><title>cut off"
    fake.by_query["IMD heavy rain"] = _feed(_item("guid-1", "IMD alert for Kerala"))
    result = await _poll(db, fake)

    assert result.queries_ok == 1
    assert result.written == 1
    assert any("malformed XML" in e for e in result.errors)
    assert any(r.levelname == "WARNING" and "broken" in r.getMessage() for r in caplog.records)


async def test_http_errors_cost_only_their_query(db, fake, queries):
    queries(en="down,IMD heavy rain")
    fake.by_query["down"] = httpx.Response(503)
    fake.by_query["IMD heavy rain"] = _feed(_item("guid-1", "IMD alert for Kerala"))
    result = await _poll(db, fake)
    assert result.written == 1
    assert any("HTTP 503" in e for e in result.errors)


async def test_a_tick_where_every_query_fails_is_a_failed_heartbeat(db, queries, monkeypatch):
    async with async_session() as s:
        await s.execute(text("DELETE FROM feed_status WHERE feed = 'google_news'"))
        await s.commit()

    async def fetch(client, query, language, since):
        return None, None, f"{query!r}: HTTP 500"

    monkeypatch.setattr(news_poller, "fetch_query", fetch)
    await news_poller.run_tick()

    async with async_session() as s:
        beat = (await s.execute(
            text("SELECT * FROM feed_status WHERE feed = 'google_news'")
        )).mappings().one()
        await s.execute(text("DELETE FROM feed_status WHERE feed = 'google_news'"))
        await s.commit()
    assert beat["consecutive_failures"] == 1
    assert "HTTP 500" in beat["last_error"]


# ── Mapping ────────────────────────────────────────────────────────────────────

def test_a_headline_is_placed_from_its_words():
    (item,) = parse_feed(_feed(_item("g", "Waterlogging in Kochi after heavy rain")))
    mapped = item_to_report(item, "q", "en", NOW)
    assert (mapped["district"], mapped["place_precision"]) == ("Ernakulam", "district")


def test_a_headline_naming_no_place_has_no_coordinates():
    (item,) = parse_feed(_feed(_item("g", "IMD issues monsoon update")))
    mapped = item_to_report(item, "q", "en", NOW)
    assert (mapped["latitude"], mapped["longitude"], mapped["place_precision"]) == (None, None, "none")
