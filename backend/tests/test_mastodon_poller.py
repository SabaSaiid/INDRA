"""
Phase 2 T4 — the Mastodon #IMD poller.

The fixture is a real #IMD timeline page saved on 24 Sep: 40 posts from 3 to
24 Sep (the plan expected 5 from 22 Sep; T4's first row takes its numbers
from the file). Mastodon is replaced by httpx's MockTransport and the 1 s
politeness delay by a no-op, so these run offline and fast.
"""

import copy
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.config import get_settings
from app.core.database import async_session
from app.workers import mastodon_poller
from app.workers.mastodon_poller import cursor_key, poll_once, status_to_report

FIXTURE = Path(__file__).parent / "fixtures" / "mastodon_tag_imd.json"
STATUSES = json.loads(FIXTURE.read_text())
NEWEST_ID = max(STATUSES, key=lambda s: int(s["id"]))["id"]


async def _no_sleep(_seconds):
    return None


@pytest.fixture
def one_tag(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "MASTODON_INSTANCES", "mastodon.social")
    monkeypatch.setattr(settings, "SOCIAL_HASHTAGS", "IMD")
    mastodon_poller._reset_for_tests()
    yield
    mastodon_poller._reset_for_tests()


class FakeMastodon:
    """Answers tag timelines per (host, tag); records every request."""

    def __init__(self):
        self.pages = {}       # (host, tag) → list of statuses
        self.responses = {}   # (host, tag) → httpx.Response to return instead
        self.down = set()     # hosts whose DNS fails
        self.requests = []

    def handler(self, request: httpx.Request):
        host = request.url.host
        tag = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((host, tag, dict(request.url.params)))
        if host in self.down:
            raise httpx.ConnectError(f"[Errno 8] nodename nor servname provided: {host}")
        if (host, tag) in self.responses:
            return self.responses[(host, tag)]
        statuses = self.pages.get((host, tag), [])
        since = request.url.params.get("since_id")
        if since:
            statuses = [s for s in statuses if int(s["id"]) > int(since)]
        return httpx.Response(200, json=statuses, headers={"X-RateLimit-Remaining": "299"})

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake():
    return FakeMastodon()


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


async def _poll(db, fake, cursors=None):
    async with fake.client() as client:
        return await poll_once(db, client, cursors=cursors, sleep=_no_sleep)


async def _rows(db, where="TRUE"):
    return (await db.execute(text(f"""
        SELECT id, CAST(source_type AS text) AS source_type, platform, raw_text, source_meta,
               latitude, longitude, place_precision, geom_point IS NULL AS no_geom,
               h3_res8, docket, reporter_hash, external_id, district, state
        FROM raw_reports WHERE {where}
    """))).mappings().all()


# ── T4's table ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_fixture_page_is_stored_as_social_posts(db, fake, one_tag):
    fake.pages[("mastodon.social", "IMD")] = STATUSES
    result = await _poll(db, fake)

    rows = await _rows(db)
    assert result.seen == 40
    assert result.written == len(rows) == 40
    assert {(r["source_type"], r["platform"]) for r in rows} == {("SOCIAL_MEDIA", "mastodon")}
    assert not [r for r in rows if "<" in r["raw_text"] and ">" in r["raw_text"]]
    assert all(r["source_meta"]["hashtags"] for r in rows)
    assert sum(len(r["source_meta"]["media"]) for r in rows) == 16
    assert all(r["docket"] is None for r in rows)
    assert result.cursors == {cursor_key("mastodon.social", "IMD"): NEWEST_ID}


@pytest.mark.integration
async def test_the_next_poll_with_no_new_posts_writes_nothing(db, fake, one_tag):
    fake.pages[("mastodon.social", "IMD")] = STATUSES
    first = await _poll(db, fake)
    second = await _poll(db, fake, cursors=first.cursors)

    assert fake.requests[-1][2]["since_id"] == NEWEST_ID
    assert (second.seen, second.written) == (0, 0)
    assert second.cursors == first.cursors
    assert len(await _rows(db)) == 40


@pytest.mark.integration
async def test_the_same_page_fetched_again_is_stored_once(db, fake, one_tag):
    fake.pages[("mastodon.social", "IMD")] = STATUSES
    await _poll(db, fake)
    again = await _poll(db, fake)  # no cursor: the whole page again
    assert (again.seen, again.written) == (40, 0)
    assert len(await _rows(db)) == 40


@pytest.mark.integration
async def test_a_boost_of_a_stored_post_adds_no_row(db, fake, one_tag):
    original = STATUSES[0]
    boost = {
        "id": str(int(NEWEST_ID) + 1),
        "uri": "https://mastodon.social/users/someone/statuses/1/activity",
        "content": "",
        "account": {"acct": "someone"},
        "reblog": copy.deepcopy(original),
    }
    fake.pages[("mastodon.social", "IMD")] = [original]
    await _poll(db, fake)
    fake.pages[("mastodon.social", "IMD")] = [boost, original]
    result = await _poll(db, fake)

    assert result.written == 0
    assert len(await _rows(db)) == 1


@pytest.mark.integration
async def test_a_boost_of_an_unseen_post_stores_the_original(db, fake, one_tag):
    original = STATUSES[0]
    boost = {"id": "1", "uri": "https://x/boost", "content": "", "account": {"acct": "b"},
             "reblog": copy.deepcopy(original)}
    fake.pages[("mastodon.social", "IMD")] = [boost]
    await _poll(db, fake)

    (row,) = await _rows(db)
    assert row["external_id"] == mastodon_poller.external_id_for(original)
    assert row["source_meta"]["collected_via_boost"] is True


def test_html_content_becomes_clean_text_with_the_url_once():
    status = {
        "id": "9", "uri": "https://mastodon.social/users/a/statuses/9",
        "content": (
            '<p>Heavy rain in Ernakulam<br>Read: <a href="https://example.com/rain?utm_source=m" '
            'rel="nofollow"><span class="invisible">https://</span><span>example.com/rain</span>'
            '</a></p>'
        ),
        "account": {"acct": "a"}, "tags": [{"name": "imd"}],
    }
    mapped = status_to_report(status, "mastodon.social", "IMD")
    assert mapped["raw_text"] == "Heavy rain in Ernakulam\nRead: https://example.com/rain?utm_source=m"
    assert mapped["source_meta"]["links"] == ["https://example.com/rain"]
    assert (mapped["district"], mapped["place_precision"]) == ("Ernakulam", "district")


def test_a_post_with_no_text_is_skipped():
    status = {"id": "9", "uri": "https://x/9", "content": "", "account": {"acct": "a"},
              "media_attachments": [{"type": "image", "url": "https://x/i.png"}]}
    assert status_to_report(status, "mastodon.social", "IMD") is None


def test_the_spoiler_comes_first():
    status = {"id": "9", "uri": "https://x/9", "spoiler_text": "Weather CW",
              "content": "<p>Rain</p>", "account": {"acct": "a"}}
    assert status_to_report(status, "mastodon.social", "IMD")["raw_text"] == "Weather CW\nRain"


@pytest.mark.integration
async def test_a_429_backs_off_that_instance_and_others_continue(db, fake, one_tag, monkeypatch):
    monkeypatch.setattr(get_settings(), "MASTODON_INSTANCES", "mastodon.social,fosstodon.org")
    fake.responses[("mastodon.social", "IMD")] = httpx.Response(429, headers={"Retry-After": "60"})
    fake.pages[("fosstodon.org", "IMD")] = STATUSES[:3]

    first = await _poll(db, fake)
    assert first.written == 3
    assert any("HTTP 429" in e for e in first.errors)

    # Within the 60 s, mastodon.social is not asked at all; fosstodon still is.
    fake.requests.clear()
    second = await _poll(db, fake)
    assert [h for h, _, _ in fake.requests] == ["fosstodon.org"]
    assert any("waiting out a 429" in e for e in second.errors)


def test_retry_after_as_seconds_or_date():
    assert mastodon_poller._retry_after_seconds("60") == 60.0
    assert mastodon_poller._retry_after_seconds(None) == 60.0
    assert mastodon_poller._retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


@pytest.mark.integration
async def test_an_instance_whose_dns_fails_is_skipped_and_recorded(db, fake, one_tag, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "MASTODON_INSTANCES", "no-such-instance.invalid,mastodon.social")
    monkeypatch.setattr(get_settings(), "SOCIAL_HASHTAGS", "IMD,monsoon")
    fake.down.add("no-such-instance.invalid")
    fake.pages[("mastodon.social", "IMD")] = STATUSES[:2]

    result = await _poll(db, fake)
    assert result.written == 2
    # One failed request, not one per tag: the instance is dropped for the tick.
    assert [t for h, t, _ in fake.requests if h == "no-such-instance.invalid"] == ["IMD"]
    assert any("ConnectError" in e for e in result.errors)
    assert any(r.levelname == "WARNING" and "no-such-instance" in r.getMessage() for r in caplog.records)


@pytest.mark.integration
async def test_run_tick_records_the_dns_error_in_the_heartbeat(db, one_tag, monkeypatch):
    async with async_session() as s:
        await s.execute(text("DELETE FROM feed_status WHERE feed = 'mastodon'"))
        await s.commit()
    monkeypatch.setattr(get_settings(), "MASTODON_INSTANCES", "no-such-instance.invalid")
    monkeypatch.setattr(get_settings(), "MASTODON_TIMEOUT_SECONDS", 2.0)

    await mastodon_poller.run_tick()

    async with async_session() as s:
        beat = (await s.execute(text("SELECT * FROM feed_status WHERE feed = 'mastodon'"))).mappings().one()
        await s.execute(text("DELETE FROM feed_status WHERE feed = 'mastodon'"))
        await s.commit()
    assert beat["consecutive_failures"] == 1
    assert "no-such-instance.invalid" in beat["last_error"]


@pytest.mark.integration
async def test_low_rate_limit_skips_the_rest_of_the_instances_tags(db, fake, one_tag, monkeypatch):
    monkeypatch.setattr(get_settings(), "SOCIAL_HASHTAGS", "IMD,monsoon,fog")
    fake.responses[("mastodon.social", "IMD")] = httpx.Response(
        200, json=STATUSES[:1], headers={"X-RateLimit-Remaining": "19"}
    )
    result = await _poll(db, fake)
    assert [t for _, t, _ in fake.requests] == ["IMD"]
    assert result.written == 1
    assert any("19 requests left" in e for e in result.errors)


@pytest.mark.integration
async def test_the_same_post_under_two_tags_is_one_row(db, fake, one_tag, monkeypatch):
    monkeypatch.setattr(get_settings(), "SOCIAL_HASHTAGS", "IMD,monsoon")
    fake.pages[("mastodon.social", "IMD")] = STATUSES[:5]
    fake.pages[("mastodon.social", "monsoon")] = STATUSES[:5]
    result = await _poll(db, fake)
    assert result.seen == 10
    assert result.written == 5


# ── Privacy ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_no_author_handle_appears_anywhere_in_the_database(db, fake, one_tag):
    fake.pages[("mastodon.social", "IMD")] = STATUSES
    await _poll(db, fake)

    handles = set()
    for s in STATUSES:
        acct = s["account"]["acct"]
        handles |= {acct.lower(), acct.split("@")[0].lower()}

    dump = (await db.execute(text("""
        SELECT lower(coalesce(string_agg(CAST(r AS text), ' '), '')) FROM raw_reports r
    """))).scalar()
    outbox = (await db.execute(text("""
        SELECT lower(coalesce(string_agg(CAST(payload AS text), ' '), '')) FROM outbox
    """))).scalar()

    # A handle the author wrote into their own post text would be theirs to
    # publish; the check is on everything *around* the text.
    texts = " ".join(r["raw_text"].lower() for r in await _rows(db))
    leaked = {h for h in handles if (h in dump or h in outbox) and h not in texts}
    assert not leaked


@pytest.mark.integration
async def test_urls_open_the_post_without_naming_the_author(db, fake, one_tag):
    fake.pages[("mastodon.social", "IMD")] = STATUSES[:3]
    await _poll(db, fake)
    for row in await _rows(db):
        assert row["external_id"].startswith("sha256:")
        assert row["source_meta"]["url"].startswith("https://mastodon.social/web/statuses/")
        assert "/@" not in row["source_meta"]["url"] and "/users/" not in row["source_meta"]["url"]
        assert row["reporter_hash"] == row["source_meta"]["author_hash"]


# ── Places ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_post_naming_no_place_is_stored_with_no_coordinates(db, fake, one_tag):
    status = {"id": "5", "uri": "https://mastodon.social/users/a/statuses/5",
              "content": "<p>Rain again today #weather</p>", "account": {"acct": "a"},
              "tags": [{"name": "weather"}], "created_at": "2026-09-24T05:00:00.000Z"}
    fake.pages[("mastodon.social", "IMD")] = [status]
    await _poll(db, fake)

    (row,) = await _rows(db)
    assert (row["latitude"], row["longitude"], row["place_precision"]) == (None, None, "none")
    assert row["no_geom"] and row["h3_res8"] is None


@pytest.mark.integration
async def test_a_district_post_has_a_point_but_no_h3_cell(db, fake, one_tag):
    status = {"id": "6", "uri": "https://mastodon.social/users/a/statuses/6",
              "content": "<p>Heavy rain in Ernakulam</p>", "account": {"acct": "a"},
              "created_at": "2026-09-24T05:00:00.000Z"}
    fake.pages[("mastodon.social", "IMD")] = [status]
    await _poll(db, fake)

    (row,) = await _rows(db)
    assert row["place_precision"] == "district"
    assert not row["no_geom"]
    assert row["h3_res8"] is None


@pytest.mark.integration
async def test_a_state_post_keeps_coordinates_but_no_geometry(db, fake, one_tag):
    status = {"id": "7", "uri": "https://mastodon.social/users/a/statuses/7",
              "content": "<p>Heavy rain in Kerala today</p>", "account": {"acct": "a"},
              "created_at": "2026-09-24T05:00:00.000Z"}
    fake.pages[("mastodon.social", "IMD")] = [status]
    await _poll(db, fake)

    (row,) = await _rows(db)
    assert row["place_precision"] == "state"
    assert row["latitude"] is not None
    assert row["no_geom"]
