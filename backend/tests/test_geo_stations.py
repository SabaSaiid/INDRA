"""GET /api/geo/stations — the Open-Meteo readings the station poller stores."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def stations_db():
    async with async_session() as db:
        await db.execute(text("DELETE FROM station_readings WHERE station_code LIKE 'TEST-%'"))
        await db.commit()
        try:
            yield db
        finally:
            await db.execute(text("DELETE FROM station_readings WHERE station_code LIKE 'TEST-%'"))
            await db.commit()


async def _reading(db, code, mm, age):
    await db.execute(
        text(f"""
            INSERT INTO station_readings
                (station_code, station_name, agency, station_location, rainfall_mm, recorded_at)
            VALUES (:code, :code, 'OPEN_METEO', ST_SetSRID(ST_MakePoint(85.13, 25.59), 4326),
                    :mm, date_trunc('hour', now()) - INTERVAL '{age}')
        """),
        {"code": code, "mm": mm},
    )


async def test_one_row_per_observation_hour_and_the_newest_on_top(api, stations_db):
    # The poller writes the same observation hour on every 10-minute tick.
    for _ in range(3):
        await _reading(stations_db, "TEST-A", 22.1, "1 hour")
    await _reading(stations_db, "TEST-A", 25.0, "0 hours")
    await stations_db.commit()

    rows = (await api.get("/api/geo/stations")).json()
    a = next(r for r in rows if r["station_code"] == "TEST-A")
    assert [p["rainfall_mm"] for p in a["series"]] == [22.1, 25.0]
    assert a["rainfall_mm"] == 25.0


async def test_a_station_silent_for_48_hours_is_left_out(api, stations_db):
    await _reading(stations_db, "TEST-OLD", 5.0, "72 hours")
    await stations_db.commit()

    rows = (await api.get("/api/geo/stations")).json()
    assert "TEST-OLD" not in [r["station_code"] for r in rows]
