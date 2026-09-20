"""
Day 6 T2/T3 — the scheduled Open-Meteo poll, and scoring from what it stored.

`station_readings` was created on Day 1 and never held a row (BUG-008), so layer
1 had no feed on a schedule and layer 7 had no historical table with anything in
it. This file pins both halves:

* every row in that table came from a real Open-Meteo response, and a failed
  request leaves **no row** rather than a zero;
* the weather factor prefers a fresh, near reading over a live request, which is
  what lets an event be scored with the network unplugged.

The unit tests fake the HTTP client; the integration tests use the real database
and never touch the network.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session
from app.models.enums import Agency
from app.workers import station_poller
from app.workers.station_poller import (
    STATIONS,
    fetch_current_precipitation,
    latest_reading_near,
    poll_once,
    station_code,
)

settings = get_settings()

PATNA_LAT, PATNA_LNG = 25.5941, 85.1376


# ── Fake transports ────────────────────────────────────────────────────────────

def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(precipitation, time_str="2026-09-21T06:00"):
    def handler(request):
        return httpx.Response(
            200,
            json={"current": {"time": time_str, "precipitation": precipitation}},
        )
    return handler


def _status(code):
    return lambda request: httpx.Response(code, json={})


def _malformed(request):
    return httpx.Response(200, json={"current": {"time": "2026-09-21T06:00"}})


def _boom(request):
    raise httpx.ConnectError("Network is unreachable")


# ── Reading one station ────────────────────────────────────────────────────────

async def test_a_good_response_yields_millimetres_and_the_observation_time():
    async with _client(_ok(12.5)) as c:
        result = await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c)

    mm, observed_at = result
    assert mm == 12.5
    assert observed_at == datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)


async def test_zero_rainfall_is_a_measurement_not_a_failure():
    async with _client(_ok(0.0)) as c:
        result = await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c)

    assert result is not None
    assert result[0] == 0.0


async def test_a_null_precipitation_is_a_failure_not_a_zero():
    async with _client(_ok(None)) as c:
        assert await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c) is None


@pytest.mark.parametrize("code", [429, 500, 503])
async def test_a_non_200_is_a_failure(code):
    async with _client(_status(code)) as c:
        assert await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c) is None


async def test_a_malformed_body_is_a_failure():
    async with _client(_malformed) as c:
        assert await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c) is None


async def test_a_connection_error_never_escapes():
    async with _client(_boom) as c:
        assert await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c) is None


async def test_a_failure_logs_exactly_one_warning(caplog):
    with caplog.at_level("WARNING", logger="indra.workers.station_poller"):
        async with _client(_boom) as c:
            await fetch_current_precipitation(PATNA_LAT, PATNA_LNG, c)

    assert len(caplog.records) == 1


def test_station_codes_are_stable_and_namespaced():
    assert station_code("Patna") == "OM-PATNA"
    assert len(STATIONS) == 6
    assert set(STATIONS) == {"Patna", "Delhi", "Mumbai", "Chennai", "Kolkata", "Guwahati"}


# ── A tick, against the real table ─────────────────────────────────────────────

pytestmark_integration = pytest.mark.integration


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await session.execute(text("DELETE FROM station_readings"))
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(text("DELETE FROM station_readings"))
            await session.commit()


async def _count(db) -> int:
    return (await db.execute(text("SELECT count(*) FROM station_readings"))).scalar()


@pytest.mark.integration
async def test_one_tick_writes_one_row_per_station(db):
    async with _client(_ok(4.0)) as c:
        written = await poll_once(db, c)

    assert written == 6
    assert await _count(db) == 6


@pytest.mark.integration
async def test_every_row_is_attributed_to_open_meteo_and_nothing_else(db):
    """
    IMD and CWC have no feed. A row claiming either would be a fabricated
    source, which is the one thing this project does not do.
    """
    async with _client(_ok(4.0)) as c:
        await poll_once(db, c)

    agencies = (await db.execute(text("SELECT DISTINCT agency FROM station_readings"))).scalars().all()
    assert agencies == [Agency.OPEN_METEO.value]


@pytest.mark.integration
async def test_unmeasured_columns_are_null_not_zero(db):
    """
    anomaly_score 0.0 would read as "computed, and normal". Anomaly detection is
    out of scope since 20 Sep and does not run at all, so the column stays NULL.
    Same for river_level_m: there is no gauge feed.
    """
    async with _client(_ok(4.0)) as c:
        await poll_once(db, c)

    row = (
        await db.execute(
            text("SELECT anomaly_score, river_level_m, rainfall_mm FROM station_readings LIMIT 1")
        )
    ).first()

    assert row[0] is None
    assert row[1] is None
    assert row[2] == 4.0


@pytest.mark.integration
async def test_the_observation_time_is_stored_not_the_wall_clock(db):
    async with _client(_ok(4.0, time_str="2026-09-21T03:00")) as c:
        await poll_once(db, c)

    recorded = (await db.execute(text("SELECT recorded_at FROM station_readings LIMIT 1"))).scalar()
    assert recorded == datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)


@pytest.mark.integration
async def test_two_ticks_write_twelve_rows_with_no_duplicate_pair(db):
    async with _client(_ok(4.0, time_str="2026-09-21T06:00")) as c:
        await poll_once(db, c)
    async with _client(_ok(5.0, time_str="2026-09-21T07:00")) as c:
        await poll_once(db, c)

    assert await _count(db) == 12
    pairs = (
        await db.execute(
            text(
                "SELECT count(*) FROM ("
                "  SELECT station_code, recorded_at FROM station_readings"
                "  GROUP BY station_code, recorded_at HAVING count(*) > 1"
                ") d"
            )
        )
    ).scalar()
    assert pairs == 0


@pytest.mark.integration
async def test_open_meteo_unreachable_writes_nothing_and_does_not_raise(db):
    async with _client(_boom) as c:
        written = await poll_once(db, c)

    assert written == 0
    assert await _count(db) == 0


@pytest.mark.integration
async def test_a_partial_outage_stores_only_what_answered(db):
    """One station failing must not discard the five that answered."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 2:
            raise httpx.ConnectError("one station down")
        return httpx.Response(
            200, json={"current": {"time": "2026-09-21T06:00", "precipitation": 1.0}}
        )

    async with _client(handler) as c:
        written = await poll_once(db, c)

    assert written == 5
    assert await _count(db) == 5


# ── The weather factor prefers what was polled ─────────────────────────────────

async def _store(db, *, mm, age_minutes, lat, lng, code="OM-TEST"):
    await db.execute(
        text(
            """
            INSERT INTO station_readings
                (id, station_code, station_name, agency, station_location,
                 rainfall_mm, recorded_at)
            VALUES
                (gen_random_uuid(), :code, 'Test', 'OPEN_METEO',
                 ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                 :mm, now() - make_interval(mins => :age))
            """
        ),
        {"code": code, "lat": lat, "lng": lng, "mm": mm, "age": age_minutes},
    )
    await db.commit()


@pytest.mark.integration
async def test_a_fresh_near_reading_is_used(db):
    await _store(db, mm=8.0, age_minutes=5, lat=PATNA_LAT + 0.05, lng=PATNA_LNG)

    found = await latest_reading_near(db, PATNA_LAT, PATNA_LNG)

    assert found is not None
    assert found[0] == 8.0


@pytest.mark.integration
async def test_a_reading_just_inside_the_age_boundary_is_used(db):
    await _store(db, mm=8.0, age_minutes=29, lat=PATNA_LAT, lng=PATNA_LNG)

    assert await latest_reading_near(db, PATNA_LAT, PATNA_LNG) is not None


@pytest.mark.integration
async def test_a_reading_past_the_age_boundary_is_ignored(db):
    await _store(db, mm=8.0, age_minutes=31, lat=PATNA_LAT, lng=PATNA_LNG)

    assert await latest_reading_near(db, PATNA_LAT, PATNA_LNG) is None


@pytest.mark.integration
async def test_a_reading_too_far_away_is_ignored(db):
    # ~0.6 degrees of latitude ≈ 66 km, comfortably outside the 25 km gate.
    await _store(db, mm=8.0, age_minutes=5, lat=PATNA_LAT + 0.6, lng=PATNA_LNG)

    assert await latest_reading_near(db, PATNA_LAT, PATNA_LNG) is None


@pytest.mark.integration
async def test_the_freshest_of_several_candidates_wins(db):
    await _store(db, mm=1.0, age_minutes=20, lat=PATNA_LAT, lng=PATNA_LNG, code="OM-OLD")
    await _store(db, mm=9.0, age_minutes=5, lat=PATNA_LAT, lng=PATNA_LNG, code="OM-NEW")

    found = await latest_reading_near(db, PATNA_LAT, PATNA_LNG)

    assert found[0] == 9.0
    assert found[2] == "OM-NEW"


@pytest.mark.integration
async def test_a_stored_zero_is_a_reading_and_a_stored_null_is_not(db):
    await _store(db, mm=0.0, age_minutes=5, lat=PATNA_LAT, lng=PATNA_LNG)

    found = await latest_reading_near(db, PATNA_LAT, PATNA_LNG)
    assert found is not None and found[0] == 0.0

    await db.execute(text("UPDATE station_readings SET rainfall_mm = NULL"))
    await db.commit()

    assert await latest_reading_near(db, PATNA_LAT, PATNA_LNG) is None


@pytest.mark.integration
async def test_an_empty_table_falls_back_to_live(db):
    assert await latest_reading_near(db, PATNA_LAT, PATNA_LNG) is None


@pytest.mark.integration
async def test_scoring_prefers_the_stored_reading_and_makes_no_http_call(db, monkeypatch):
    """
    The point of T3: with a fresh reading in the table, the pipeline scores the
    weather factor without touching the network.
    """
    from app.services import pipeline

    called = {"n": 0}

    async def _must_not_be_called(lat, lng, client=None):
        called["n"] += 1
        return None, None

    monkeypatch.setattr(pipeline, "weather_score", _must_not_be_called)
    await _store(db, mm=64.5, age_minutes=5, lat=PATNA_LAT, lng=PATNA_LNG)

    score, mm, source = await pipeline._weather_for_cluster(db, PATNA_LAT, PATNA_LNG)

    assert called["n"] == 0
    assert source == "station_reading"
    assert mm == 64.5
    assert score == 0.70   # the IMD "heavy" breakpoint, same curve as a live read


@pytest.mark.integration
async def test_scoring_falls_back_to_live_when_nothing_is_stored(db, monkeypatch):
    from app.services import pipeline

    async def _live(lat, lng, client=None):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _live)

    score, mm, source = await pipeline._weather_for_cluster(db, PATNA_LAT, PATNA_LNG)

    assert source == "open_meteo_live"
    assert (score, mm) == (0.35, 15.6)


@pytest.mark.integration
async def test_the_receipt_names_which_source_the_rainfall_came_from(db):
    from app.services.pipeline import score_cluster

    stats = {
        "count": 3,
        "centroid_lat": PATNA_LAT,
        "centroid_lng": PATNA_LNG,
        "max_pairwise_km": 0.8,
        "radius_km": 0.4,
    }
    scored = score_cluster(
        stats, ["CITIZEN_APP"], 0.35, 15.6,
        report_texts=["water on the road"],
        weather_source="station_reading",
    )

    assert scored["receipt"]["weather"]["source"] == "station_reading"
    weather_factor = [
        f for f in scored["receipt"]["factors"]
        if f["factor"] == "Weather Station Corroboration"
    ][0]
    assert "polled station reading" in weather_factor["evidence"]


def test_the_poller_can_be_turned_off():
    """A kill switch that is never exercised is not a kill switch."""
    assert hasattr(settings, "STATION_POLLER_ENABLED")
    assert settings.STATION_READING_MAX_AGE_MINUTES == 30
    assert settings.STATION_READING_MAX_DISTANCE_KM == 25.0


@pytest.mark.integration
async def test_disabling_the_poller_starts_no_task(monkeypatch, caplog):
    monkeypatch.setattr(station_poller.settings, "STATION_POLLER_ENABLED", False)

    with caplog.at_level("INFO", logger="indra.workers.station_poller"):
        await station_poller.start_station_poller()   # returns immediately

    assert any("disabled" in r.message for r in caplog.records)
