"""
Phase 2 T3 — the METAR poller against the test database.

AWC is replaced by httpx's MockTransport serving the 24 Sep cache file, so
these run offline. The rows are T3's table's poller half: the same station and
time in two ticks, a 304, a corrupt download or HTTP 500. Then the station
endpoint that serves them, and the guarantee that METAR never leaks into the
Open-Meteo rainfall layer.
"""

import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import feed_status
from app.workers import metar_poller

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent / "fixtures" / "metar_cache_24sep.csv.gz"
LAST_MODIFIED = "Thu, 24 Sep 2026 05:45:00 GMT"


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await session.execute(text("DELETE FROM station_readings WHERE feed = 'metar'"))
        await session.execute(text("DELETE FROM feed_status WHERE feed = 'metar'"))
        await session.commit()
        metar_poller._reset_for_tests()
        try:
            yield session
        finally:
            await session.execute(text("DELETE FROM station_readings WHERE feed = 'metar'"))
            await session.execute(text("DELETE FROM feed_status WHERE feed = 'metar'"))
            await session.commit()
            metar_poller._reset_for_tests()


@pytest.fixture
def lake_calls(monkeypatch):
    from app.services import lake

    calls = []

    async def fake_put_raw(source, payload, content_type, **kwargs):
        calls.append((source, payload, content_type, kwargs))
        return True

    monkeypatch.setattr(lake, "put_raw", fake_put_raw)
    return calls


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serve(body: bytes, status: int = 200, seen: list = None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.append(dict(request.headers))
        if status == 200:
            return httpx.Response(200, content=body, headers={"Last-Modified": LAST_MODIFIED})
        return httpx.Response(status)
    return handler


async def _count(db, where="TRUE"):
    return (await db.execute(
        text(f"SELECT count(*) FROM station_readings WHERE feed = 'metar' AND {where}")
    )).scalar()


# ── One tick ───────────────────────────────────────────────────────────────────

async def test_a_tick_stores_every_indian_station(db, lake_calls):
    async with _client(_serve(FIXTURE.read_bytes())) as client:
        written, seen = await metar_poller.poll_once(db, client)
    assert (written, seen) == (105, 105)
    assert metar_poller.last_tick_error is None
    assert await _count(db) == 105


async def test_neighbouring_countries_are_not_stored(db, lake_calls):
    async with _client(_serve(FIXTURE.read_bytes())) as client:
        await metar_poller.poll_once(db, client)
    assert await _count(db, "station_code IN ('VNKT', 'OPKC', 'VCBI', 'VGHS')") == 0


async def test_rows_are_aerodrome_observations_with_no_rainfall(db, lake_calls):
    async with _client(_serve(FIXTURE.read_bytes())) as client:
        await metar_poller.poll_once(db, client)
    row = (await db.execute(text("""
        SELECT CAST(agency AS text), station_name, rainfall_mm, temperature_c, weather_codes,
               raw_observation, ST_Y(station_location), recorded_at
        FROM station_readings WHERE feed = 'metar' AND station_code = 'VIDP'
    """))).one()
    assert row[0] == "AERODROME_METAR"
    assert "Delhi" in row[1]
    assert row[2] is None
    assert row[3] == 31
    assert row[4] == ["HZ"]
    assert row[5].startswith("METAR VIDP 240530Z")
    assert row[6] == pytest.approx(28.57, abs=0.05)
    assert row[7] == datetime(2026, 9, 24, 5, 30, tzinfo=timezone.utc)


async def test_the_same_station_and_time_in_two_ticks_is_one_row(db, lake_calls):
    body = FIXTURE.read_bytes()
    async with _client(_serve(body)) as client:
        first = await metar_poller.poll_once(db, client)
        metar_poller._reset_for_tests()  # forget Last-Modified: force a full re-read
        second = await metar_poller.poll_once(db, client)
    assert first == (105, 105)
    assert second == (0, 105)
    assert await _count(db) == 105


async def test_the_next_tick_sends_if_modified_since(db, lake_calls):
    seen = []
    async with _client(_serve(FIXTURE.read_bytes(), seen=seen)) as client:
        await metar_poller.poll_once(db, client)
        await metar_poller.poll_once(db, client)
    assert "if-modified-since" not in seen[0]
    assert seen[1]["if-modified-since"] == LAST_MODIFIED


async def test_304_stores_nothing_and_is_not_an_error(db, lake_calls):
    async with _client(_serve(b"", status=304)) as client:
        assert await metar_poller.poll_once(db, client) == (0, 0)
    assert metar_poller.last_tick_error is None
    assert lake_calls == []


@pytest.mark.parametrize(
    "body, status, error",
    [
        (b"\x1f\x8b" + b"broken", 200, "unreadable"),
        (b"", 500, "HTTP 500"),
    ],
)
async def test_a_bad_download_is_one_warning_and_a_failed_tick(db, lake_calls, caplog, body, status, error):
    async with _client(_serve(body, status=status)) as client:
        assert await metar_poller.poll_once(db, client) == (0, 0)
    assert error in metar_poller.last_tick_error
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and r.name.endswith("metar_poller")]
    assert len(warnings) == 1
    assert await _count(db) == 0


async def test_a_corrupt_file_is_fetched_again_not_skipped_as_unchanged(db, lake_calls):
    seen = []
    async with _client(_serve(b"\x1f\x8b" + b"broken", seen=seen)) as client:
        await metar_poller.poll_once(db, client)
        await metar_poller.poll_once(db, client)
    assert "if-modified-since" not in seen[1]


async def test_the_lake_gets_indian_rows_only(db, lake_calls):
    async with _client(_serve(FIXTURE.read_bytes())) as client:
        await metar_poller.poll_once(db, client)
    (source, payload, content_type, kwargs), = lake_calls
    assert (source, content_type) == ("metar", "text/csv")
    lines = payload.decode().splitlines()
    assert len(lines) == 1 + 105
    assert not any(",VNKT," in line or ",OPKC," in line for line in lines)
    assert len(payload) < len(gzip.decompress(FIXTURE.read_bytes()))


# ── The heartbeat ──────────────────────────────────────────────────────────────

async def _heartbeat():
    async with async_session() as s:
        return (await s.execute(
            text("SELECT * FROM feed_status WHERE feed = 'metar'")
        )).mappings().first()


async def test_run_tick_records_a_successful_heartbeat_with_the_cursor(db, lake_calls, monkeypatch):
    async def fetch(client, since):
        return metar_poller.FetchResult("ok", FIXTURE.read_bytes(), LAST_MODIFIED)

    monkeypatch.setattr(metar_poller, "fetch_cache", fetch)
    assert await metar_poller.run_tick() == (105, 105)
    beat = await _heartbeat()
    assert beat["consecutive_failures"] == 0
    assert beat["items_last_tick"] == 105
    assert beat["cursor"] == {"last_modified": LAST_MODIFIED}


async def test_run_tick_records_a_failure(db, lake_calls, monkeypatch):
    async def fetch(client, since):
        return metar_poller.FetchResult("failed", error="METAR cache returned HTTP 500")

    monkeypatch.setattr(metar_poller, "fetch_cache", fetch)
    await metar_poller.run_tick()
    beat = await _heartbeat()
    assert beat["consecutive_failures"] == 1
    assert beat["last_error"] == "METAR cache returned HTTP 500"


async def test_a_restart_resumes_from_the_stored_cursor(db, lake_calls, monkeypatch):
    await feed_status.record_tick("metar", ok=True, cursor={"last_modified": LAST_MODIFIED})
    asked = []

    async def fetch(client, since):
        asked.append(since)
        return metar_poller.FetchResult("not_modified", last_modified=since)

    monkeypatch.setattr(metar_poller, "fetch_cache", fetch)
    await metar_poller.run_tick()
    assert asked == [LAST_MODIFIED]


# ── GET /api/stations/latest ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _insert(db, code, recorded_at, temp):
    await db.execute(text("""
        INSERT INTO station_readings (station_code, station_name, agency, feed, recorded_at,
                                      temperature_c, weather_codes, station_location)
        VALUES (:c, :c, 'AERODROME_METAR', 'metar', :at, :t, ARRAY['HZ'],
                ST_SetSRID(ST_MakePoint(77.1, 28.5), 4326))
    """), {"c": code, "at": recorded_at, "t": temp})
    await db.commit()


async def test_latest_is_the_newest_reading_per_station(api, db):
    now = datetime.now(timezone.utc)
    await _insert(db, "VIDP", now - timedelta(minutes=60), 30.0)
    await _insert(db, "VIDP", now - timedelta(minutes=30), 31.0)
    await _insert(db, "VABB", now - timedelta(minutes=30), 27.0)

    body = (await api.get("/api/stations/latest?feed=metar")).json()
    by_code = {s["station_code"]: s for s in body["stations"]}
    assert body["count"] == 2
    assert by_code["VIDP"]["temperature_c"] == 31.0
    assert by_code["VIDP"]["weather_codes"] == ["HZ"]
    assert by_code["VIDP"]["lat"] == pytest.approx(28.5)


async def test_a_station_silent_too_long_is_left_out(api, db):
    await _insert(db, "VIDP", datetime.now(timezone.utc) - timedelta(hours=4), 30.0)
    body = (await api.get("/api/stations/latest?feed=metar&max_age_hours=3")).json()
    assert body["count"] == 0


async def test_an_unknown_feed_is_422(api):
    assert (await api.get("/api/stations/latest?feed=bogus")).status_code == 422


async def test_metar_never_leaks_into_the_rainfall_layer(api, db):
    await _insert(db, "VIDP", datetime.now(timezone.utc) - timedelta(minutes=10), 30.0)
    rows = (await api.get("/api/geo/stations")).json()
    assert "VIDP" not in {r["station_code"] for r in rows}
