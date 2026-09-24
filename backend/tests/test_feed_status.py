"""
Phase 2 T2 — feed heartbeats and GET /api/meta/sources.

The pure block pins `feed_state()`'s rules at their boundaries. The
integration block writes real heartbeats through `record_tick()` and reads
them back through the endpoint: T2's test table, row for row, plus the cursor
and the dead-letter count the endpoint grew on the way (T8).
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session
from app.services import feed_status
from app.services.feed_status import (
    DEAD_LETTER,
    FAILING_AFTER_FAILURES,
    MAX_ERROR_LENGTH,
    feed_state,
    get_cursor,
    record_tick,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _state(**overrides):
    args = dict(
        enabled=True, push=False, last_success_at=NOW, consecutive_failures=0,
        poll_interval_s=600, now=NOW,
    )
    args.update(overrides)
    return feed_state(**args)


# ── feed_state(): the rules ────────────────────────────────────────────────────

def test_a_fresh_success_is_ok():
    assert _state() == "ok"


def test_never_polled_is_stale_not_ok():
    assert _state(last_success_at=None) == "stale"


def test_stale_boundary_is_three_intervals():
    assert _state(last_success_at=NOW - timedelta(seconds=1800)) == "ok"
    assert _state(last_success_at=NOW - timedelta(seconds=1801)) == "stale"


def test_failing_after_three_failures_not_two():
    assert FAILING_AFTER_FAILURES == 3
    assert _state(consecutive_failures=2) == "ok"
    assert _state(consecutive_failures=3) == "failing"


def test_failing_outranks_stale():
    assert _state(consecutive_failures=3, last_success_at=None) == "failing"


def test_disabled_outranks_everything():
    assert _state(enabled=False, consecutive_failures=5) == "disabled"


def test_a_push_feed_is_ok_however_quiet():
    assert _state(push=True, last_success_at=None, poll_interval_s=None) == "ok"


def test_every_feed_has_a_distinct_name_and_known_kind():
    names = [f.feed for f in feed_status.FEEDS]
    assert len(names) == len(set(names))
    assert {f.kind for f in feed_status.FEEDS} <= {
        "citizen", "official", "social", "news", "station", "warnings",
    }


# ── Heartbeats through the endpoint ────────────────────────────────────────────


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def clean_status():
    async with async_session() as db:
        await db.execute(text("DELETE FROM feed_status"))
        await db.commit()
    yield
    async with async_session() as db:
        await db.execute(text("DELETE FROM feed_status"))
        await db.commit()


@pytest.fixture
def all_pollers_on(monkeypatch):
    settings = get_settings()
    for name in ("SACHET_POLLER_ENABLED", "STATION_POLLER_ENABLED", "METAR_POLLER_ENABLED",
                 "MASTODON_POLLER_ENABLED", "NEWS_POLLER_ENABLED"):
        monkeypatch.setattr(settings, name, True)


async def _feeds(api):
    r = await api.get("/api/meta/sources")
    assert r.status_code == 200
    return r.json()


async def _row(feed):
    async with async_session() as db:
        return (await db.execute(
            text("SELECT * FROM feed_status WHERE feed = :f"), {"f": feed}
        )).mappings().first()


@pytest.mark.integration
async def test_fresh_start_every_poller_is_stale_and_push_feeds_ok(api, clean_status, all_pollers_on):
    body = await _feeds(api)
    status = {f["feed"]: f["status"] for f in body["feeds"]}
    assert status == {
        "citizen": "ok", "official": "ok",
        "sachet": "stale", "open_meteo": "stale", "metar": "stale",
        "mastodon": "stale", "google_news": "stale",
    }


@pytest.mark.integration
async def test_the_new_pollers_are_off_by_default(api, clean_status):
    status = {f["feed"]: f["status"] for f in (await _feeds(api))["feeds"]}
    assert {status["metar"], status["mastodon"], status["google_news"]} == {"disabled"}


@pytest.mark.integration
async def test_one_successful_tick_is_ok_with_its_item_count(api, clean_status, all_pollers_on):
    await record_tick("metar", ok=True, items=104)
    feed = next(f for f in (await _feeds(api))["feeds"] if f["feed"] == "metar")
    assert feed["status"] == "ok"
    assert feed["items_last_tick"] == 104
    assert feed["basis"] == "heartbeat"
    assert feed["last_success_at"] is not None


@pytest.mark.integration
async def test_three_failed_ticks_are_failing_with_the_last_error(api, clean_status, all_pollers_on):
    for n in (1, 2, 3):
        await record_tick("mastodon", ok=False, error=f"HTTP 500 on try {n}")
    feed = next(f for f in (await _feeds(api))["feeds"] if f["feed"] == "mastodon")
    assert feed["status"] == "failing"
    assert feed["last_error"] == "HTTP 500 on try 3"
    assert feed["consecutive_failures"] == 3


@pytest.mark.integration
async def test_two_failed_ticks_are_not_yet_failing(api, clean_status, all_pollers_on):
    await record_tick("mastodon", ok=True, items=1)
    await record_tick("mastodon", ok=False, error="timeout")
    await record_tick("mastodon", ok=False, error="timeout")
    feed = next(f for f in (await _feeds(api))["feeds"] if f["feed"] == "mastodon")
    assert feed["status"] == "ok"
    assert feed["consecutive_failures"] == 2


@pytest.mark.integration
async def test_a_success_resets_the_failure_count(clean_status):
    for _ in range(3):
        await record_tick("google_news", ok=False, error="boom")
    await record_tick("google_news", ok=True, items=12)
    row = await _row("google_news")
    assert row["consecutive_failures"] == 0
    assert row["rows_total"] == 12
    # The last error stays readable after the recovery, with its time.
    assert row["last_error"] == "boom"
    assert row["last_error_at"] is not None


@pytest.mark.integration
async def test_a_disabled_poller_is_disabled(api, clean_status, monkeypatch):
    monkeypatch.setattr(get_settings(), "STATION_POLLER_ENABLED", False)
    await record_tick("open_meteo", ok=True, items=6)
    feed = next(f for f in (await _feeds(api))["feeds"] if f["feed"] == "open_meteo")
    assert feed["status"] == "disabled"


@pytest.mark.integration
async def test_rows_total_accumulates_across_ticks(clean_status):
    await record_tick("metar", ok=True, items=100)
    await record_tick("metar", ok=True, items=5)
    await record_tick("metar", ok=True, items=0)
    row = await _row("metar")
    assert row["rows_total"] == 105
    assert row["items_last_tick"] == 0


@pytest.mark.integration
async def test_a_failed_tick_without_a_reason_still_says_why(clean_status):
    await record_tick("metar", ok=False)
    assert (await _row("metar"))["last_error"] == "tick failed"


@pytest.mark.integration
async def test_a_long_error_is_cut_to_the_limit(clean_status):
    await record_tick("metar", ok=False, error="x" * 5000)
    assert len((await _row("metar"))["last_error"]) == MAX_ERROR_LENGTH


# ── The cursor ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_cursor_round_trips(clean_status):
    await record_tick("mastodon", ok=True, items=3, cursor={"mastodon.social#imd": "115"})
    assert await get_cursor("mastodon") == {"mastodon.social#imd": "115"}


@pytest.mark.integration
async def test_a_tick_with_no_cursor_keeps_the_old_one(clean_status):
    await record_tick("mastodon", ok=True, items=3, cursor={"mastodon.social#imd": "115"})
    await record_tick("mastodon", ok=False, error="DNS")
    assert await get_cursor("mastodon") == {"mastodon.social#imd": "115"}


@pytest.mark.integration
async def test_no_cursor_yet_is_empty(clean_status):
    assert await get_cursor("mastodon") == {}


# ── Dead letters (T8) ──────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_no_dead_letters_is_zero(api, clean_status):
    dead = (await _feeds(api))["dead_letters"]
    assert dead["total"] == 0
    assert dead["topic"] == get_settings().KAFKA_DLQ_TOPIC


@pytest.mark.integration
async def test_dead_letters_are_counted(api, clean_status):
    await record_tick(DEAD_LETTER, ok=False, items=1, error="ValueError: bad", kind="pipeline")
    await record_tick(DEAD_LETTER, ok=False, items=1, error="KeyError: x", kind="pipeline")
    body = await _feeds(api)
    assert body["dead_letters"]["total"] == 2
    assert body["dead_letters"]["last_error"] == "KeyError: x"
    # The dead-letter row is not a feed.
    assert DEAD_LETTER not in {f["feed"] for f in body["feeds"]}
