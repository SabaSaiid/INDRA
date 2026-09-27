"""
Phase 2 T7 and T8 — collected posts and headlines through the pipeline.

Posts are built with the pollers' own mapping functions and stored through
`store_report()`, then run through `process_report()`, exactly as the consumer
does. T7: one story shared many times counts once. T8: posts and headlines are
stored, deduplicated and shown, but held out of clustering until Phase 3, so
no headline becomes a fake flood.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.config import get_settings
from app.core.database import async_session
from app.services.ingest import store_report
from app.services.news_rss import parse_feed
from app.services.pipeline import process_report, take_failure
from app.workers.mastodon_poller import status_to_report
from app.workers.news_poller import item_to_report

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    """
    The pipeline asks Open-Meteo when it scores a cluster. Nothing here should
    form one, but if a regression did, the test must fail on the event count,
    not on the network.
    """
    from app.services import pipeline

    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


def _post(text_html, *, observed=NOW, sid=None):
    sid = sid or str(uuid.uuid4().int)[:18]
    status = {
        "id": sid,
        "uri": f"https://mastodon.social/users/someone/statuses/{sid}",
        "content": text_html,
        "account": {"acct": "someone"},
        "created_at": observed.isoformat(),
        "language": "en",
    }
    return status_to_report(status, "mastodon.social", "IMD")


def _headline(title, *, publisher="The Hindu", observed=NOW, guid=None):
    guid = guid or f"guid-{uuid.uuid4()}"
    pub = observed.strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = (
        "<rss><channel><item>"
        f"<title>{title} - {publisher}</title><link>https://news.google.com/{guid}</link>"
        f"<guid>{guid}</guid><pubDate>{pub}</pubDate>"
        f"<source url='https://www.thehindu.com'>{publisher}</source>"
        "</item></channel></rss>"
    ).encode()
    (item,) = parse_feed(xml)
    return item_to_report(item, "IMD heavy rain", "en", datetime.now(timezone.utc))


async def _store_and_process(db, mapped):
    stored = await store_report(db, **mapped)
    assert stored.created
    await process_report(db, {"id": str(stored.id)})
    assert take_failure() is None
    return stored.id


async def _row(db, report_id):
    return (await db.execute(text("""
        SELECT duplicate_of, source_meta, processed_at, event_id
        FROM raw_reports WHERE id = :id
    """), {"id": report_id})).mappings().one()


async def _events(db):
    return (await db.execute(text("SELECT count(*) FROM verified_events"))).scalar()


# ── T7: re-sharing is not witnessing ───────────────────────────────────────────

async def test_two_posts_linking_the_same_article_are_one_story(db):
    first = await _store_and_process(db, _post(
        '<p>Flooding in Patna <a href="https://x.com/a?utm_source=m">link</a></p>'))
    second = await _store_and_process(db, _post(
        '<p>Look at this <a href="https://x.com/a/">link</a></p>'))

    assert (await _row(db, first))["duplicate_of"] is None
    row = await _row(db, second)
    assert row["duplicate_of"] == first
    assert row["source_meta"]["duplicate_basis"] == {"rule": "shared_link"}


async def test_a_post_repeating_an_earlier_headline_is_its_copy(db):
    headline = "IMD issues red alert for heavy rain in Ernakulam"
    rss = await _store_and_process(db, _headline(headline, observed=NOW - timedelta(hours=2)))
    post = await _store_and_process(db, _post(
        f'<p>{headline} <a href="https://example.com/story">example.com/story</a> '
        '<a href="https://mastodon.social/tags/IMD" class="mention hashtag" rel="tag">#IMD</a></p>'
    ))

    row = await _row(db, post)
    assert row["duplicate_of"] == rss
    assert row["source_meta"]["duplicate_basis"]["rule"] == "same_text_same_place"


async def test_the_same_headline_three_days_later_is_not_a_copy(db):
    headline = "IMD issues red alert for heavy rain in Ernakulam"
    await _store_and_process(db, _headline(headline, observed=NOW - timedelta(days=3)))
    later = await _store_and_process(db, _headline(headline, publisher="Mathrubhumi"))
    assert (await _row(db, later))["duplicate_of"] is None


async def test_the_same_headline_from_a_new_guid_is_caught_by_its_key(db):
    headline = "IMD issues red alert for heavy rain in Ernakulam"
    first = await _store_and_process(db, _headline(headline, publisher="The Hindu"))
    second = await _store_and_process(db, _headline(headline, publisher="Mathrubhumi"))
    row = await _row(db, second)
    assert row["duplicate_of"] == first
    assert row["source_meta"]["duplicate_basis"] == {"rule": "same_headline"}


async def test_the_same_words_about_another_district_are_not_a_copy(db):
    await _store_and_process(db, _headline("Heavy rain lashes Ernakulam, schools shut"))
    other = await _store_and_process(db, _headline("Heavy rain lashes Kozhikode, schools shut"))
    assert (await _row(db, other))["duplicate_of"] is None


async def test_a_copy_of_a_copy_points_at_the_original(db):
    first = await _store_and_process(db, _post('<p>A <a href="https://x.com/a">l</a></p>'))
    await _store_and_process(db, _post('<p>B <a href="https://x.com/a">l</a></p>'))
    third = await _store_and_process(db, _post('<p>C <a href="https://www.x.com/a/">l</a></p>'))
    assert (await _row(db, third))["duplicate_of"] == first


# ── T8: the hold, a switch since Phase 3 T9 turned posts' clustering on ────────

def test_posts_join_clustering_by_default():
    # The class default, not get_settings(): the team server's .env sets its own.
    from app.core.config import Settings

    assert Settings.model_fields["SOCIAL_CLUSTERING_ENABLED"].default is True


async def test_with_the_hold_on_five_mastodon_posts_about_patna_make_no_event(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SOCIAL_CLUSTERING_ENABLED", False)
    ids = []
    for words in ("Water rising near Gandhi Maidan", "Roads under water in Kankarbagh",
                  "Knee deep water at Boring Road", "Flooded underpass near the station",
                  "Waterlogging outside PMCH"):
        ids.append(await _store_and_process(db, _post(f"<p>{words}, Patna #PatnaRains</p>")))

    assert await _events(db) == 0
    for rid in ids:
        row = await _row(db, rid)
        assert row["processed_at"] is not None
        assert row["event_id"] is None


async def test_a_stale_headline_is_held_even_with_social_clustering_on(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SOCIAL_CLUSTERING_ENABLED", True)
    mapped = _headline("Floods in Patna", observed=NOW - timedelta(hours=72))
    assert mapped["source_meta"]["stale"] is True
    rid = await _store_and_process(db, mapped)
    row = await _row(db, rid)
    assert row["processed_at"] is not None and row["event_id"] is None


async def test_a_post_with_no_place_is_never_clustered(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SOCIAL_CLUSTERING_ENABLED", True)
    rid = await _store_and_process(db, _post("<p>Rain again today</p>"))
    row = await _row(db, rid)
    assert row["processed_at"] is not None and row["event_id"] is None


# ── T8: how the feed labels them ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_the_live_feed_labels_posts_and_headlines(api, db):
    post = await _store_and_process(db, _post("<p>Heavy rain in Ernakulam</p>"))
    news = await _store_and_process(db, _headline("Red alert in Kozhikode", publisher="Mathrubhumi"))

    rows = (await api.get("/api/feed/recent?include=reports&limit=50")).json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[str(post)]["sourceLabel"] == "Mastodon"
    assert by_id[str(post)]["platform"] == "mastodon"
    assert by_id[str(news)]["sourceLabel"] == "Mathrubhumi"
