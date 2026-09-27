"""
Phase 4 T4 — the official-warning factor against the database: which SACHET
warnings are in force, which cover the event, and the freshness rule.

The pure scoring (CAP severity → score, family match) is in
test_receipt_v2.py; this file is the SQL half.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.database import async_session
from app.services.official_warnings import official_warning_evidence
from tests.conftest import wipe_event_tables
from tests.phase4_support import insert_warning, sachet_heartbeat, wipe_phase4_rows
from tests.test_pipeline import PATNA_LAT, PATNA_LNG, insert_report

pytestmark = [pytest.mark.integration, pytest.mark.real_sachet_heartbeat]

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(minutes=5)


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        await wipe_phase4_rows(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_phase4_rows(session)
            await wipe_event_tables(session)


async def evidence_at_patna(db, event_type="URBAN_FLOOD", **kwargs):
    e, nearby = await official_warning_evidence(
        db, event_type, now=NOW, lat=PATNA_LAT, lng=PATNA_LNG, **kwargs
    )
    return e, nearby


async def test_an_in_force_severe_heavy_rain_polygon_scores_0_85(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, sender="IMD Patna")
    e, _ = await evidence_at_patna(db)
    assert e.score == 0.85 and e.state == "computed" and e.source == "sachet_cap"
    assert e.reason.startswith("IMD Patna: Severe Heavy Rainfall warning in force until")
    assert "matched by polygon" in e.reason


async def test_a_heat_warning_over_a_flood_event_scores_0(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, event="Heat Wave")
    e, _ = await evidence_at_patna(db)
    assert e.score == 0.0
    assert "for heatwave, not flood" in e.reason


async def test_an_expired_warning_scores_0(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, expires_in_hours=-1)
    e, _ = await evidence_at_patna(db)
    assert e.score == 0.0
    assert e.reason == "no official warning in force covers this event"


async def test_a_warning_not_yet_effective_scores_0(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, effective_hours_ago=-2)
    assert (await evidence_at_patna(db))[0].score == 0.0


async def test_a_cancel_message_is_ignored(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, msg_type="Cancel")
    assert (await evidence_at_patna(db))[0].score == 0.0


async def test_an_exercise_is_ignored(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, status="Exercise")
    assert (await evidence_at_patna(db))[0].score == 0.0


async def test_a_warning_elsewhere_does_not_cover_the_event(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT + 2.0, lng=PATNA_LNG, now=NOW, half_km=20.0)
    assert (await evidence_at_patna(db))[0].score == 0.0


async def test_sachet_last_success_45_minutes_ago_is_offline(db):
    await sachet_heartbeat(db, NOW - timedelta(minutes=45))
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW)
    e, nearby = await evidence_at_patna(db)
    assert e.score is None and e.state == "offline"
    assert nearby is None


async def test_no_heartbeat_at_all_is_offline(db):
    e, _ = await evidence_at_patna(db)
    assert e.state == "offline"


async def test_a_district_only_warning_counts_when_it_names_the_district(db):
    await sachet_heartbeat(db, FRESH)
    await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=NOW, polygon=False,
                         area_desc="Patna, Gaya, Nalanda", raw_severity="Moderate")
    e, _ = await evidence_at_patna(db, district="Patna")
    assert e.score == 0.6 and "matched by district" in e.reason
    assert (await evidence_at_patna(db, district="Bhagalpur"))[0].score == 0.0


async def test_the_footprint_is_the_reports_hull(db):
    await sachet_heartbeat(db, FRESH)
    # A 2 km warning square 3 km north of Patna: the centre is outside it, but
    # one report sits inside, so the event's footprint intersects it.
    north = PATNA_LAT + 3.0 / 111.32
    await insert_warning(db, lat=north, lng=PATNA_LNG, now=NOW, half_km=1.0)
    ids = [
        await insert_report(db, PATNA_LAT, PATNA_LNG, "Road flooded knee deep near the station"),
        await insert_report(db, north, PATNA_LNG, "Waterlogging after heavy rain, knee deep"),
    ]
    assert (await evidence_at_patna(db))[0].score == 0.0
    assert (await evidence_at_patna(db, report_ids=ids))[0].score == 0.85


async def test_a_cyclone_is_told_whether_a_cyclone_warning_is_within_500_km(db):
    await sachet_heartbeat(db, FRESH)
    _, nearby = await evidence_at_patna(db, event_type="CYCLONE")
    assert nearby is False
    # 300 km south, still inside 500 km.
    await insert_warning(db, lat=PATNA_LAT - 2.7, lng=PATNA_LNG, now=NOW, event="Cyclonic Storm",
                         half_km=30.0)
    _, nearby = await evidence_at_patna(db, event_type="CYCLONE")
    assert nearby is True
