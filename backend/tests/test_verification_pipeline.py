"""
Phase 4 through the whole pipeline: evidence gathered from the database and
stored with the event.

* T2/T3: a fabricated heatwave near Delhi's airport is CONTRADICTED by the
  airport's own thermometer, over a model that says it is hot;
* T2: the METAR query's distance, window and civil flag;
* T6: warning-tense headlines of the district count as news context, by
  publisher.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import clock, pipeline
from app.services.weather import HOURLY_VARIABLES, HourlySeries
from tests.conftest import wipe_event_tables
from tests.phase4_support import insert_metar, wipe_phase4_rows
from tests.test_pipeline import PATNA_LAT, PATNA_LNG, insert_report

pytestmark = pytest.mark.integration

VIDP = (28.567, 77.117)
# 14 km east of the airport.
NEAR_VIDP = (VIDP[0], VIDP[1] + 14.0 / (111.32 * 0.878))

# 1.3 km apart: outside citizen dedup's 1 km (these texts are near
# paraphrases, and dedup rightly suppresses them closer together), well inside
# the thermal family's 25 km clustering radius.
SPACING = 0.012

HEAT_TEXTS = [
    "Heatwave here, 47 degree today, unbearable heat",
    "Severe heatwave, temperature 47 degree, loo chal rahi hai",
    "Extreme heat, 47 degree in the afternoon, heatwave",
    "Heatwave conditions, mercury touched 47 degree",
    "Scorching heatwave, 47 degree celsius today",
]


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        await wipe_phase4_rows(session)
        await session.execute(text("DELETE FROM raw_reports WHERE source_meta->>'p4_test' = 'true'"))
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(text("DELETE FROM raw_reports WHERE source_meta->>'p4_test' = 'true'"))
            await wipe_phase4_rows(session)
            await wipe_event_tables(session)


def hot_model(monkeypatch, temperature=44.0):
    """The model says it is hot all day: the station will have to overrule it."""
    now = clock.now().replace(minute=0, second=0, microsecond=0)
    times = tuple(now - timedelta(hours=30) + timedelta(hours=h) for h in range(48))
    values = {name: tuple(None for _ in times) for name in HOURLY_VARIABLES}
    values["temperature_2m"] = tuple(temperature for _ in times)
    series = HourlySeries(times, values, 216.0, "open-meteo forecast")

    async def _hourly(lat, lng, client=None):
        return series

    monkeypatch.setattr(pipeline, "fetch_hourly", _hourly)


async def test_a_fabricated_heatwave_near_vidp_is_contradicted_by_the_airport(db, monkeypatch):
    hot_model(monkeypatch)
    now = clock.now()
    for hours_ago, temperature in ((20, 24.0), (14, 26.7), (8, 25.0), (2, 23.0)):
        await insert_metar(db, station="VIDP", lat=VIDP[0], lng=VIDP[1],
                           recorded_at=now - timedelta(hours=hours_ago), temperature_c=temperature)
    event = None
    for i, body in enumerate(HEAT_TEXTS):
        rid = await insert_report(db, NEAR_VIDP[0] + SPACING * i, NEAR_VIDP[1], body)
        event = await pipeline.process_report(db, {"id": str(rid)}) or event

    assert event is not None and event["event_type"] == "HEATWAVE"
    assert event["verdict"] == "CONTRADICTED"
    assert event["review_status"] != "AUTO_PUBLISHED"
    receipt = event["verification_receipt"]
    weather = receipt["evidence"]["weather_station"]
    assert weather["source"] == "airport_metar" and weather["score"] == 0.0
    assert weather["contradiction"] is True
    assert "VIDP" in receipt["contradictions"][0]["reason"]
    assert "26.7 °C" in receipt["contradictions"][0]["reason"]
    # The model said 44 °C; the measurement was used, and the receipt says so.
    assert "44.0 °C" in weather["reason"] and "disagree" in weather["reason"]
    assert "contradicted" in receipt["routing"]["caps"]
    stored = (await db.execute(
        text("SELECT CAST(verdict AS text) FROM verified_events WHERE id = CAST(:e AS uuid)"),
        {"e": event["id"]},
    )).scalar()
    await db.commit()
    assert stored == "CONTRADICTED"


async def test_the_same_heatwave_with_a_hot_airport_is_corroborated(db, monkeypatch):
    hot_model(monkeypatch, temperature=46.0)
    now = clock.now()
    await insert_metar(db, station="VIDP", lat=VIDP[0], lng=VIDP[1],
                       recorded_at=now - timedelta(hours=5), temperature_c=46.0)
    event = None
    for i, body in enumerate(HEAT_TEXTS):
        rid = await insert_report(db, NEAR_VIDP[0] + SPACING * i, NEAR_VIDP[1], body)
        event = await pipeline.process_report(db, {"id": str(rid)}) or event

    assert event["verdict"] == "CORROBORATED"
    weather = event["verification_receipt"]["evidence"]["weather_station"]
    assert weather["source"] == "airport_metar" and weather["score"] == 0.9
    assert event["verification_receipt"]["contradictions"] == []


async def test_the_metar_query_measures_distance_and_names_civil_airports(db):
    now = clock.now()
    await insert_metar(db, station="VIDP", lat=VIDP[0], lng=VIDP[1],
                       recorded_at=now - timedelta(hours=1), visibility_m=150, weather_codes=["FG"])
    await insert_metar(db, station="VIDP", lat=VIDP[0], lng=VIDP[1],
                       recorded_at=now - timedelta(hours=9), visibility_m=100)

    rows = await pipeline._metar_observations(db, NEAR_VIDP[0], NEAR_VIDP[1],
                                               now - timedelta(hours=3), now)
    await db.commit()

    assert len(rows) == 1
    assert rows[0]["station_code"] == "VIDP" and rows[0]["civil"] is True
    assert 13.5 < rows[0]["distance_km"] < 14.5
    far = await pipeline._metar_observations(db, PATNA_LAT, PATNA_LNG, now - timedelta(hours=3), now)
    await db.commit()
    assert far == []


async def test_warning_headlines_of_the_district_count_as_news_by_publisher(db):
    now = clock.now()
    for domain, name in (("thehindu.com", "The Hindu"), ("timesofindia.indiatimes.com", "Times of India"),
                         ("thehindu.com", "The Hindu")):
        await db.execute(
            text("""
                INSERT INTO raw_reports (id, source_type, raw_text, district, hazard_family, flags,
                                         observed_at, source_meta)
                VALUES (gen_random_uuid(), 'NEWS_MEDIA', 'IMD warns of heavy rain in Patna', 'Patna',
                        'water', ARRAY['not_an_observation'], :at,
                        jsonb_build_object('publisher_domain', CAST(:d AS text),
                                           'publisher', CAST(:n AS text), 'p4_test', 'true'))
            """),
            {"at": now - timedelta(minutes=30), "d": domain, "n": name},
        )
    await db.commit()
    rid = await insert_report(db, PATNA_LAT, PATNA_LNG, "Road flooded knee deep near the market")
    reports = await pipeline._cluster_reports(db, [rid])

    async def _weather(lat, lng):
        return 0.35, 15.6

    pipeline_weather = pipeline.weather_score
    pipeline.weather_score = _weather
    try:
        bundle = await pipeline._gather_evidence(
            db, event_type="URBAN_FLOOD", lat=PATNA_LAT, lng=PATNA_LNG, reports=reports,
            district="Patna",
        )
    finally:
        pipeline.weather_score = pipeline_weather
    await db.commit()

    news = bundle["news"]
    assert news["count"] == 2 and news["score"] == 0.75
    assert news["publishers"] == ["The Hindu", "Times of India"]
    assert news["forecast_items"] == 3
    other_district = await pipeline._gather_evidence(
        db, event_type="URBAN_FLOOD", lat=PATNA_LAT, lng=PATNA_LNG, reports=reports, district="Gaya",
    )
    await db.commit()
    assert other_district["news"]["score"] is None
