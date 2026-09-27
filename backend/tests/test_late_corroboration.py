"""
Phase 4 T5 — late corroboration: an event re-scored when evidence arrives
after it. Each row of the plan's T5 table is a test below.

Events are made the way production makes them, through the pipeline; the
warning or observation that arrives later is written to the database and then
handed to rescore_open_events as the poller would hand it.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from app.services import audit, cache, clock, late_corroboration, pipeline
from tests.conftest import wipe_event_tables
from tests.phase4_support import insert_metar, insert_warning, sachet_heartbeat, wipe_phase4_rows
from tests.test_pipeline import CLUSTER_TEXTS, PATNA_LAT, PATNA_LNG, insert_report

pytestmark = [pytest.mark.integration, pytest.mark.real_sachet_heartbeat]

VIDP = (28.567, 77.117)


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


@pytest.fixture(autouse=True)
def fresh_pending():
    late_corroboration._reset_for_tests()
    yield
    late_corroboration._reset_for_tests()


@pytest.fixture
def broadcasts(monkeypatch):
    from app.main import ws_manager
    from app.services import event_publisher

    sent = []

    async def record(message):
        sent.append(message)

    async def publish(event):
        return True

    monkeypatch.setattr(ws_manager, "broadcast", record)
    monkeypatch.setattr(event_publisher, "publish_verified_event", publish)
    return sent


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


async def patna_flood(db):
    """The five Patna reports through the pipeline: one flood event, no warning."""
    ids = [await insert_report(db, lat, lng, body) for lat, lng, body in CLUSTER_TEXTS]
    event = None
    for rid in ids:
        event = await pipeline.process_report(db, {"id": str(rid)}) or event
    assert event is not None
    return event


async def stored(db, event_id):
    row = (await db.execute(
        text("""
            SELECT confidence_score, CAST(verdict AS text), CAST(review_status AS text),
                   verification_receipt
            FROM verified_events WHERE id = CAST(:id AS uuid)
        """),
        {"id": str(event_id)},
    )).fetchone()
    await db.commit()
    return row


async def late_rows(db, event_id=None):
    rows = await audit.fetch_rows(db, event_id)
    await db.commit()
    return [r for r in rows if r["action_taken"] == "LATE_CORROBORATION"]


async def warning_trigger(db, **kwargs):
    now = clock.now()
    identifier = await insert_warning(db, lat=PATNA_LAT, lng=PATNA_LNG, now=now, **kwargs)
    row = (await db.execute(
        text("SELECT event, headline, sent_at, msg_type FROM agency_alerts WHERE identifier = :i"),
        {"i": identifier},
    )).fetchone()
    await db.commit()
    return late_corroboration.sachet_trigger(
        identifier, event=row[0], headline=row[1], sent_at=row[2], msg_type=row[3]
    )


async def test_a_warning_twenty_minutes_later_raises_the_open_flood_event(db, broadcasts):
    await sachet_heartbeat(db, clock.now())
    event = await patna_flood(db)
    before = await stored(db, event["id"])
    assert before[1] == "UNCONFIRMED" and before[2] == "QUARANTINED"

    trigger = await warning_trigger(db)
    totals = await late_corroboration.rescore_open_events([trigger], async_session)

    after = await stored(db, event["id"])
    assert totals["changed"] == 1
    assert after[0] > before[0]
    # The warning's 0.85 × 0.10 over the 0.80 coverage: +0.10625.
    assert abs((after[0] - before[0]) - 0.10625) < 0.0003
    assert after[1] == "CORROBORATED"
    assert after[2] in ("PENDING_HUMAN_REVIEW", "AUTO_PUBLISHED")
    rows = await late_rows(db, event["id"])
    assert len(rows) == 1
    assert rows[0]["details"]["trigger"] == trigger.key
    assert rows[0]["details"]["before"]["verdict"] == "UNCONFIRMED"
    assert rows[0]["details"]["after"]["verdict"] == "CORROBORATED"
    assert [m["type"] for m in broadcasts] == ["VERIFIED_EVENT"]
    assert after[3]["late_corroboration"]["trigger"] == trigger.key
    snapshots = (await db.execute(
        text("SELECT trigger FROM event_snapshots WHERE event_id = CAST(:id AS uuid) ORDER BY at"),
        {"id": event["id"]},
    )).scalars().all()
    assert snapshots[-1] == f"late:{trigger.key}"


async def test_a_human_approval_stands_while_confidence_and_verdict_move(db, broadcasts):
    await sachet_heartbeat(db, clock.now())
    event = await patna_flood(db)
    await db.execute(
        text("""
            UPDATE verified_events SET review_status = 'HUMAN_APPROVED',
                verification_receipt = verification_receipt || '{"human_review": {"action": "approve",
                    "operator_id": "OP-CMD-001", "reason": "field team confirmed", "at": "x"}}'::jsonb
            WHERE id = CAST(:id AS uuid)
        """),
        {"id": event["id"]},
    )
    await db.commit()
    before = await stored(db, event["id"])

    await late_corroboration.rescore_open_events([await warning_trigger(db)], async_session)

    after = await stored(db, event["id"])
    assert after[2] == "HUMAN_APPROVED"
    assert after[0] > before[0] and after[1] == "CORROBORATED"
    assert len(await late_rows(db, event["id"])) == 1


async def test_the_same_warning_twice_changes_nothing_the_second_time(db, broadcasts):
    await sachet_heartbeat(db, clock.now())
    event = await patna_flood(db)
    trigger = await warning_trigger(db)

    await late_corroboration.rescore_open_events([trigger], async_session)
    await late_corroboration.rescore_open_events([trigger], async_session)
    assert len(await late_rows(db, event["id"])) == 1

    # Without the cache's marks, the re-score runs and still writes nothing.
    cache.clear()
    totals = await late_corroboration.rescore_open_events([trigger], async_session)
    assert totals["processed"] == 1 and totals["changed"] == 0
    assert len(await late_rows(db, event["id"])) == 1
    assert len(broadcasts) == 1


async def test_a_warning_of_another_family_touches_no_event(db, broadcasts):
    await sachet_heartbeat(db, clock.now())
    event = await patna_flood(db)
    trigger = await warning_trigger(db, event="Heat Wave")
    assert trigger.families == ("thermal",)

    totals = await late_corroboration.rescore_open_events([trigger], async_session)

    assert totals["candidates"] == 0
    assert await late_rows(db, event["id"]) == []


async def test_sixty_matching_events_are_fifty_now_and_ten_on_the_next_tick(db, broadcasts):
    await sachet_heartbeat(db, clock.now())
    for i in range(60):
        await db.execute(
            text("""
                INSERT INTO verified_events
                    (id, event_code, event_type, severity, confidence_score, review_status, quadrant,
                     impact_radius_km, center_point, verification_receipt, hazard_family, updated_at)
                VALUES (gen_random_uuid(), :code, 'URBAN_FLOOD', 'MODERATE', 0.5, 'QUARANTINED', 'Noise',
                        0.5, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), '{}'::jsonb, 'water', NOW())
            """),
            {"code": f"INDRA-P4-{i:03d}", "lat": PATNA_LAT + i * 0.001, "lng": PATNA_LNG},
        )
    await db.commit()
    trigger = await warning_trigger(db)

    first = await late_corroboration.rescore_open_events([trigger], async_session)
    assert (first["candidates"], first["processed"], first["deferred"]) == (60, 50, 10)
    assert [t.key for t in late_corroboration.pending()] == [trigger.key]

    second = await late_corroboration.rescore_open_events([], async_session)
    assert (second["processed"], second["deferred"]) == (10, 0)
    assert late_corroboration.pending() == []


async def test_a_fog_event_is_rescored_when_vidp_reports_fog_ten_minutes_later(db, broadcasts):
    # 14 km east of the airport, inside Delhi.
    lat, lng = VIDP[0], VIDP[1] + 14.0 / (111.32 * 0.878)
    texts = [
        "Dense fog here, visibility under 50 metres on the road",
        "Very dense fog, visibility near zero, cannot see the next car",
        "Thick fog this morning, visibility below 100 metres",
    ]
    ids = [await insert_report(db, lat + 0.002 * i, lng, body) for i, body in enumerate(texts)]
    event = None
    for rid in ids:
        event = await pipeline.process_report(db, {"id": str(rid)}) or event
    assert event is not None and event["event_type"] == "FOG"
    before = await stored(db, event["id"])
    weather_before = before[3]["evidence"]["weather_station"]
    assert weather_before["state"] == "offline"

    later = clock.now() + timedelta(minutes=10)
    await insert_metar(db, station="VIDP", lat=VIDP[0], lng=VIDP[1], recorded_at=later,
                       visibility_m=150, weather_codes=["FG"])
    triggers = late_corroboration.metar_triggers([{
        "station_code": "VIDP", "recorded_at": later, "weather_codes": ["FG"], "visibility_m": 150,
    }])
    assert [t.families for t in triggers] == [("visibility",)]

    with clock.frozen(later + timedelta(minutes=2)):
        totals = await late_corroboration.rescore_open_events(triggers, async_session)

    after = await stored(db, event["id"])
    assert totals["changed"] == 1
    weather_after = after[3]["evidence"]["weather_station"]
    assert weather_after["source"] == "airport_metar" and weather_after["score"] == 0.85
    assert "VIDP" in weather_after["reason"]


def test_an_unremarkable_observation_is_no_trigger():
    assert late_corroboration.metar_families({"weather_codes": ["HZ"], "visibility_m": 4000,
                                              "gust_kmh": 20, "temperature_c": 31}) == ()


@pytest.mark.parametrize("obs, families", [
    ({"weather_codes": ["TS", "RA+"]}, ("convective", "water")),
    ({"weather_codes": ["VCTS"]}, ("convective",)),
    ({"weather_codes": ["DS"]}, ("convective",)),
    ({"weather_codes": ["SQ"]}, ("convective",)),
    ({"weather_codes": ["GR"]}, ("convective",)),
    ({"visibility_m": 600}, ("visibility",)),
    ({"gust_kmh": 39}, ("convective",)),
    ({"temperature_c": 40}, ("thermal",)),
    ({"temperature_c": 10}, ("thermal",)),
])
def test_what_a_metar_observation_triggers(obs, families):
    assert late_corroboration.metar_families(obs) == families
