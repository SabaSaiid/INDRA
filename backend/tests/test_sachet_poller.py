"""
The SACHET poller — layer 1's official-warning feed.

What this file pins, in order of how much damage the bug would do:

1. **A re-poll updates the row; it never appends.** The feed republishes an alert
   as a CAP `Update` under the same identifier. An insert-only poller multiplies
   every warning by the number of revisions, and any corroboration count read off
   the table then climbs without a single new warning being issued — a confidence
   score rising on its own is exactly the failure the receipt exists to prevent.
2. **ETag caching works, and a truncated feed does not poison it.** Storing the
   ETag before the body parsed would mean a bad response is cached as good and
   never re-fetched.
3. **One failed alert costs one alert**, not the tick.
4. **A missing polygon stays NULL.** No bounding box is invented from the
   district codes.

Unit tests fake the HTTP client with captured payloads; the integration tests use
the real database and never touch the network.
"""

import pathlib

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session
from app.models.enums import Severity
from app.workers import sachet_poller
from app.workers.sachet_poller import fetch_index, poll_once

settings = get_settings()

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
RSS = (FIXTURES / "sachet_rss_sample.xml").read_bytes()
CAP = (FIXTURES / "sachet_cap_sample.xml").read_bytes()
POLYGON = (FIXTURES / "sachet_polygon_sample.xml").read_bytes()

# The identifier of the first item in the captured RSS fixture.
FIRST_ID = "1789957059562006"


@pytest.fixture(autouse=True)
def _clear_etag():
    """The ETag is module state; a leftover makes the next test see a 304."""
    sachet_poller._reset_etag_for_tests()
    yield
    sachet_poller._reset_etag_for_tests()


# ── Fake transports ────────────────────────────────────────────────────────

def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _feed(rss=RSS, cap=CAP, polygon=POLYGON, etag=None, calls=None):
    """A whole SACHET feed: index, CAP documents and polygons."""
    def handler(request):
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if "rss_india" in url:
            headers = {"ETag": etag} if etag else {}
            if etag and request.headers.get("If-None-Match") == etag:
                return httpx.Response(304, headers=headers)
            return httpx.Response(200, content=rss, headers=headers)
        if "FetchPolygonXMLFile" in url:
            if polygon is None:
                return httpx.Response(404)
            return httpx.Response(200, content=polygon)
        if "FetchXMLFile" in url:
            if cap is None:
                return httpx.Response(500)
            return httpx.Response(200, content=cap)
        return httpx.Response(404)
    return handler


def _boom(request):
    raise httpx.ConnectError("Network is unreachable")


# ── The index ──────────────────────────────────────────────────────────────

async def test_index_parses_the_real_feed():
    async with _client(_feed()) as c:
        items = await fetch_index(c)
    assert len(items) == 3
    assert items[0].identifier == FIRST_ID


async def test_index_sends_if_none_match_and_honours_304():
    calls = []
    async with _client(_feed(etag='W/"abc123"', calls=calls)) as c:
        first = await fetch_index(c)
        assert len(first) == 3
        # Second poll: same ETag goes out, 304 comes back, no items.
        second = await fetch_index(c)
        assert second is None
    assert sum("rss_india" in u for u in calls) == 2


async def test_truncated_feed_does_not_poison_the_etag():
    """
    A body that parses to zero alerts must not be cached as good — otherwise the
    next poll sends its ETag, is told 304, and the feed is never read again.
    """
    async with _client(_feed(rss=b"<rss><channel></channel></rss>", etag='W/"bad"')) as c:
        assert await fetch_index(c) is None
    assert sachet_poller._index_etag is None


async def test_index_failure_is_none_not_an_exception():
    async with _client(_boom) as c:
        assert await fetch_index(c) is None
    async with _client(lambda r: httpx.Response(503)) as c:
        assert await fetch_index(c) is None


# ── A tick, against the real table ─────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await session.execute(text("DELETE FROM agency_alerts"))
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(text("DELETE FROM agency_alerts"))
            await session.commit()


async def _count(db) -> int:
    return (await db.execute(text("SELECT count(*) FROM agency_alerts"))).scalar()


@pytest.mark.integration
async def test_one_tick_stores_every_alert_in_the_feed(db):
    async with _client(_feed()) as c:
        written, seen = await poll_once(db, c)
    assert (written, seen) == (3, 3)
    assert await _count(db) == 3


@pytest.mark.integration
async def test_stored_alert_carries_the_agencys_own_severity(db):
    async with _client(_feed()) as c:
        await poll_once(db, c)

    row = (
        await db.execute(
            text(
                "SELECT sender, raw_severity, severity::text, certainty, urgency, event "
                "FROM agency_alerts LIMIT 1"
            )
        )
    ).first()
    sender, raw_severity, severity, certainty, urgency, event = row
    assert sender == "Gujarat-SDMA"
    assert raw_severity == "Moderate"
    assert severity == Severity.MODERATE.value
    assert certainty == "Likely"
    assert urgency == "Expected"
    assert event == "Light Rain"


@pytest.mark.integration
async def test_repolling_updates_in_place_and_never_appends(db):
    """
    The defect that would quietly inflate every corroboration count in the
    platform. Three ticks over an unchanged feed must leave three rows.
    """
    for _ in range(3):
        sachet_poller._reset_etag_for_tests()
        async with _client(_feed()) as c:
            await poll_once(db, c)

    assert await _count(db) == 3


@pytest.mark.integration
async def test_a_cap_update_overwrites_the_previous_revision(db):
    async with _client(_feed()) as c:
        await poll_once(db, c)

    revised = CAP.replace(b"<cap:severity>Moderate</cap:severity>",
                          b"<cap:severity>Severe</cap:severity>")
    # A later pubDate is what marks the item as republished.
    newer_rss = RSS.replace(b"21 Sep 2026 02:28:50", b"21 Sep 2026 09:28:50")

    sachet_poller._reset_etag_for_tests()
    async with _client(_feed(rss=newer_rss, cap=revised)) as c:
        written, _ = await poll_once(db, c)

    assert written >= 1
    assert await _count(db) == 3
    severities = [
        r[0]
        for r in (
            await db.execute(text("SELECT severity::text FROM agency_alerts"))
        ).all()
    ]
    assert Severity.HIGH.value in severities


@pytest.mark.integration
async def test_already_current_alerts_are_not_refetched(db):
    """
    Rule 2: the steady state costs one conditional request, not 99 CAP fetches.
    """
    async with _client(_feed()) as c:
        await poll_once(db, c)

    calls = []
    sachet_poller._reset_etag_for_tests()
    async with _client(_feed(calls=calls)) as c:
        written, seen = await poll_once(db, c)

    assert (written, seen) == (0, 3)
    assert not any("FetchXMLFile" in u for u in calls)


@pytest.mark.integration
async def test_polygon_is_stored_in_gujarat_not_siberia(db):
    """
    End to end through PostGIS: the swapped-coordinate bug survives every unit
    test if the WKT is built correctly and then handed to ST_GeomFromText with
    the arguments in the wrong order.
    """
    async with _client(_feed()) as c:
        await poll_once(db, c)

    row = (
        await db.execute(
            text(
                "SELECT ST_X(ST_Centroid(area_polygon)), ST_Y(ST_Centroid(area_polygon)), "
                "       ST_SRID(area_polygon), polygon_points "
                "FROM agency_alerts WHERE area_polygon IS NOT NULL LIMIT 1"
            )
        )
    ).first()
    assert row is not None, "no alert stored a polygon"
    lng, lat, srid, points = row
    assert srid == 4326
    assert 72.0 < lng < 73.5, f"longitude {lng} is not in Gujarat"
    assert 20.5 < lat < 21.5, f"latitude {lat} is not in Gujarat"
    assert points == 40


@pytest.mark.integration
async def test_a_missing_polygon_stays_null(db):
    """A district-code-only alert is real. An invented bbox would not be."""
    async with _client(_feed(polygon=None)) as c:
        written, _ = await poll_once(db, c)

    assert written == 3
    nulls = (
        await db.execute(
            text("SELECT count(*) FROM agency_alerts WHERE area_polygon IS NULL")
        )
    ).scalar()
    assert nulls == 3


@pytest.mark.integration
async def test_district_codes_are_stored(db):
    async with _client(_feed()) as c:
        await poll_once(db, c)

    codes = (
        await db.execute(
            text("SELECT district_codes FROM agency_alerts WHERE district_codes IS NOT NULL LIMIT 1")
        )
    ).scalar()
    assert codes == ["444", "453", "462"]


@pytest.mark.integration
async def test_one_bad_cap_document_does_not_lose_the_others(db):
    """Rule 4. The first alert 500s; the remaining two must still land."""
    seen_ids = []

    def handler(request):
        url = str(request.url)
        if "rss_india" in url:
            return httpx.Response(200, content=RSS)
        if "FetchPolygonXMLFile" in url:
            return httpx.Response(200, content=POLYGON)
        if "FetchXMLFile" in url:
            seen_ids.append(url)
            if len(seen_ids) == 1:
                return httpx.Response(500)
            return httpx.Response(200, content=CAP)
        return httpx.Response(404)

    async with _client(handler) as c:
        written, seen = await poll_once(db, c)

    assert seen == 3
    assert written == 2
    assert await _count(db) == 2


@pytest.mark.integration
async def test_unreachable_feed_writes_nothing_and_does_not_raise(db):
    async with _client(_boom) as c:
        assert await poll_once(db, c) == (0, 0)
    assert await _count(db) == 0


@pytest.mark.integration
async def test_fetches_are_capped_per_tick(db, monkeypatch):
    """A cold start sees ~99 new alerts; the burst is bounded."""
    monkeypatch.setattr(settings, "SACHET_MAX_FETCHES_PER_TICK", 1)
    async with _client(_feed()) as c:
        written, seen = await poll_once(db, c)

    assert seen == 3
    assert written == 1
    assert await _count(db) == 1
