"""
Regression tests for the events read API against a live database.

These exist because every router in this codebase wraps its query in a
try/except that falls back to demo data, so a broken query returns HTTP 200
with plausible-looking content and nothing in the response distinguishes it
from a working one. `GET /api/events/{id}` was broken this way from the start:
a single bind parameter compared against both a uuid column and a varchar
column made Postgres raise "operator does not exist: character varying = uuid"
on every call, and every lookup silently returned the Patna demo event.

The assertions therefore check for the *real* row, not merely for HTTP 200.
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_event():
    """Insert one real event, yield (id, event_code), then remove it."""
    event_id = uuid.uuid4()
    event_code = f"INDRA-TEST-{str(event_id)[:6]}"
    receipt = (
        '{"confidence_score": 0.81, "factors": ['
        '{"factor": "Weather Station Corroboration", "weight_pct": 25.0, "score": 0.9,'
        ' "weighted_points": 0.225, "evidence": "test"}'
        '], "cluster": {"size": 4}}'
    )

    async with async_session() as db:
        await wipe_event_tables(db)
        await db.execute(
            text("""
                INSERT INTO verified_events
                    (id, event_code, event_type, severity, confidence_score,
                     review_status, quadrant, impact_radius_km, center_point,
                     verification_receipt)
                VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD', 'HIGH', 0.81,
                        'PENDING_HUMAN_REVIEW', 'Unverified Threat', 3.2,
                        ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326),
                        CAST(:receipt AS jsonb))
            """),
            {"id": str(event_id), "code": event_code, "receipt": receipt},
        )
        await db.commit()
        try:
            yield str(event_id), event_code
        finally:
            await wipe_event_tables(db)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_event_detail_by_uuid_returns_the_real_row(api, seeded_event):
    event_id, event_code = seeded_event

    r = await api.get(f"/api/events/{event_id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == event_id
    assert body["event_code"] == event_code
    assert body["confidence_score"] == pytest.approx(0.81)
    # The demo fallback's receipt has no "factors" key at all.
    assert "factors" in body["verification_receipt"]


async def test_event_detail_by_event_code_returns_the_real_row(api, seeded_event):
    event_id, event_code = seeded_event

    r = await api.get(f"/api/events/{event_code}")

    assert r.status_code == 200
    assert r.json()["id"] == event_id


async def test_event_detail_with_a_non_uuid_id_is_a_404(api, seeded_event, monkeypatch):
    """
    The id is a free-text path segment, so a non-UUID must not blow up the uuid
    comparison — it must simply match nothing real.

    This used to assert 200. That was DEMO_MODE=true leaking into the contract:
    with demo data on, the detail endpoint's `empty()` branch answered a
    non-existent event with an invented one, so "matches nothing real" looked like
    a success. With DEMO_MODE=false — the default since 20 Sep — the honest answer
    to "show me this event" when there is no such event is 404.
    """
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "DEMO_MODE", False)

    r = await api.get("/api/events/definitely-not-a-uuid")

    assert r.status_code == 404
    assert r.status_code != 500


async def test_event_detail_with_a_non_uuid_id_in_demo_mode_invents_nothing_real(
    api, seeded_event, monkeypatch
):
    """
    With demo data on, the same request answers 200 with a demo event — but it must
    never be mistaken for the seeded row, and it must never be a 500.
    """
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "DEMO_MODE", True)

    r = await api.get("/api/events/definitely-not-a-uuid")

    assert r.status_code == 200
    _, event_code = seeded_event
    assert r.json()["event_code"] != event_code


async def test_events_list_returns_the_real_row(api, seeded_event):
    event_id, event_code = seeded_event

    r = await api.get("/api/events")

    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    assert events[0]["event_code"] == event_code
    assert events[0]["lat"] == pytest.approx(25.5941, abs=1e-4)
    assert events[0]["lng"] == pytest.approx(85.1376, abs=1e-4)


class TestLocationIsServedFromColumns:
    """
    BUG-033. The events API read the place name out of
    `verification_receipt->>'city'`, a key only the synthetic seeder ever
    wrote, so every pipeline-produced event was served as "Unknown" while
    demo data looked correct. It reads columns now.
    """

    async def test_an_event_with_a_district_serves_it(self, api, seeded_event):
        event_id, _ = seeded_event

        async with async_session() as db:
            await db.execute(
                text("""
                    UPDATE verified_events
                    SET district = 'Patna', state = 'Bihar', place_precision = 'district'
                    WHERE id = CAST(:id AS uuid)
                """),
                {"id": event_id},
            )
            await db.commit()

        listed = next(
            e for e in (await api.get("/api/events")).json() if e["id"] == event_id
        )
        assert listed["city"] == "Patna"
        assert listed["state"] == "Bihar"
        assert listed["place_precision"] == "district"

        detail = (await api.get(f"/api/events/{event_id}")).json()
        assert detail["city"] == "Patna"
        assert detail["place_precision"] == "district"

    async def test_an_unplaced_event_serves_null_not_the_word_unknown(
        self, api, seeded_event
    ):
        """
        The fixture leaves district NULL. The old code turned that into the
        string "Unknown", which the frontend then rendered as a place name and
        could not distinguish from a real one.
        """
        event_id, _ = seeded_event

        listed = next(
            e for e in (await api.get("/api/events")).json() if e["id"] == event_id
        )
        assert listed["city"] is None
        assert listed["state"] is None

        detail = (await api.get(f"/api/events/{event_id}")).json()
        assert detail["city"] is None

    async def test_the_word_unknown_is_gone_from_the_events_payload(
        self, api, seeded_event
    ):
        import json as _json

        body = _json.dumps((await api.get("/api/events")).json())
        assert '"Unknown"' not in body
