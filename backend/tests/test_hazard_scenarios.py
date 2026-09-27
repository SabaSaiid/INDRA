"""
Phase 3 T10's exit criterion: each of the PS's seven categories produces an
event of the right type.

These are the seven scenarios of the former `scripts/run_hazard_demo.py` (five
reports, five devices, spread over the family's radius), kept here as tests:
the demo injectors were deleted on 25 Sep, because running one against the
team database wrote synthetic reports into it. Each scenario
is stored through `store_report()` and run through `process_report()` on the
test database, the same path a report the API accepts takes after Kafka.

Run with `-s` to print each event's type, severity, severity axis and
confidence; the phase file quotes those lines.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.services import pipeline
from app.services.ingest import store_report
from app.services.pipeline import process_report, take_failure

pytestmark = pytest.mark.integration

CITIES = {
    "patna": (25.5941, 85.1376),
    "delhi": (28.6139, 77.2090),
    "lucknow": (26.8467, 80.9462),
    "kolkata": (22.5726, 88.3639),
    "bikaner": (28.0229, 73.3119),
    "mumbai": (19.0760, 72.8777),
    "amritsar": (31.6340, 74.8723),
}

# Offsets from the city centre in units of 0.001°, times the hazard's spread.
OFFSETS = [(0, 0), (4, 3), (-3, 4), (5, -4), (-4, -3)]

SCENARIOS = {
    "flood": ("patna", "URBAN_FLOOD", 1.0, [
        "Road waterlogged after heavy rain, autos stuck",
        "Water entered houses in our colony, knee deep",
        "Ghutno tak paani bhar gaya hai gali mein",
        "भारी बारिश के बाद मोहल्ले में जलभराव",
        "Underpass flooded, traffic diverted",
    ]),
    "heatwave": ("delhi", "HEATWAVE", 8.0, [
        "Extreme heat here, 46 degrees this afternoon",
        "Heatwave in the city, two labourers hospitalised with heatstroke",
        "46 degree hai, loo chal rahi hai, bahar mat niklo",
        "भीषण गर्मी, पारा 45 डिग्री के पार",
        "Scorching heat, roads empty by noon",
    ]),
    "fog": ("lucknow", "FOG", 5.0, [
        "Dense fog on the highway, visibility under 50 m",
        "Thick fog this morning, trains running late",
        "Ghana kohra hai, kuch dikh nahi raha",
        "घना कोहरा छाया है, गाड़ियाँ रेंग रही हैं",
        "Visibility dropped to 100 m near the airport, dense fog",
    ]),
    "thunderstorm": ("kolkata", "THUNDERSTORM", 3.0, [
        "Severe thunderstorm with heavy rain here",
        "Loud thunder for the last half hour, heavy rain",
        "Garaj ke saath tez baarish ho rahi hai",
        "गरज के साथ बारिश शुरू",
        "Thunderstorm passing over the city right now",
    ]),
    "dust_storm": ("bikaner", "DUST_STORM", 3.0, [
        "Dust storm hit the city, sky turned brown",
        "Tez aandhi aayi, dhool hi dhool",
        "धूल भरी आंधी चल रही है",
        "Massive duststorm, everything covered in sand",
        "Sandstorm across the outskirts, dust everywhere",
    ]),
    "strong_wind": ("mumbai", "STRONG_WIND", 3.0, [
        "Strong winds uprooted trees on the main road",
        "Gusty winds, tin sheets flying off roofs",
        "Tez hawa chal rahi hai, hoarding gir gaya",
        "तेज़ हवा से कई पेड़ गिर गए",
        "Winds of 70 km/h here, poles down",
    ]),
    "cold_wave": ("amritsar", "COLD_WAVE", 8.0, [
        "Cold wave here, 3 degrees this morning",
        "Biting cold, people sitting around fires",
        "Kadaake ki thand hai, 4 degree subah",
        "शीतलहर से ठिठुरा शहर",
        "Ground frost in the fields, severe cold",
    ]),
}


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
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
            await session.rollback()
            await wipe_event_tables(session)


@pytest.mark.parametrize("hazard", list(SCENARIOS))
async def test_each_of_the_seven_categories_makes_its_own_event(db, hazard):
    city, expected, spread, texts = SCENARIOS[hazard]
    lat0, lng0 = CITIES[city]
    for (dy, dx), body in zip(OFFSETS, texts):
        stored = await store_report(
            db, source_type="CITIZEN_APP", raw_text=body,
            latitude=round(lat0 + dy * 0.001 * spread, 5), longitude=round(lng0 + dx * 0.001 * spread, 5),
            reporter_hash=f"demo-{uuid.uuid4().hex[:12]}", issue_docket=False,
        )
        await process_report(db, {"id": str(stored.id)})
        assert take_failure() is None

    rows = (await db.execute(text("""
        SELECT CAST(event_type AS text), CAST(severity AS text), confidence_score, verification_receipt,
               (SELECT count(*) FROM raw_reports r WHERE r.event_id = e.id)
        FROM verified_events e
    """))).fetchall()
    assert len(rows) == 1, f"{hazard}: {len(rows)} events"
    event_type, severity, confidence, receipt, members = rows[0]
    basis = receipt["severity_basis"] if "severity_basis" in receipt else receipt.get("severity", {})
    print(f"\n[T10] {hazard:12} {city:9} → {event_type:12} {severity:9} "
          f"axis={basis.get('axis')} value={basis.get('value')} confidence={confidence:.4f} "
          f"reports={members} votes={receipt['event_type_basis']['votes']}")
    assert event_type == expected
    assert members == 5
    if expected not in ("URBAN_FLOOD", "THUNDERSTORM"):
        # Rainfall cannot corroborate heat, cold, fog, dust or wind: offline, with a note.
        weather = next(f for f in receipt["factors"] if "Weather" in f["factor"])
        assert weather["state"] == "offline"
