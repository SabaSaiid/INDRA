"""
BUG-062 — `/api/events/distribution` named live events by their enum value.

The hazard donut grouped by `verification_receipt->>'event_type_display'`, a key
only `scripts/seed_national_data.py` writes. Every event the pipeline made fell
through to `URBAN_FLOOD` and the "unknown" grey. It now names each type from the
hazard taxonomy, and a seeded slice of the same name is merged into it.
"""

import json
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.services import hazards

pytestmark = pytest.mark.integration


async def _event(db, event_type, *, status="PENDING_HUMAN_REVIEW", display=None):
    receipt = {"event_type_display": display} if display else {}
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km, center_point,
                 verification_receipt)
            VALUES (CAST(:id AS uuid), :code, CAST(:etype AS event_type_enum), 'MODERATE', 0.5,
                    CAST(:status AS review_status_enum), 'Noise', 1.0,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326),
                    CAST(:receipt AS jsonb))
        """),
        {
            "id": str(uuid.uuid4()),
            "code": f"INDRA-DIST-{uuid.uuid4().hex[:6]}",
            "etype": event_type,
            "status": status,
            "receipt": json.dumps(receipt),
        },
    )


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await wipe_event_tables(session)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_pipeline_event_is_named_from_the_taxonomy(api, db):
    await _event(db, "URBAN_FLOOD")
    await db.commit()

    r = await api.get("/api/events/distribution", params={"by": "hazard", "time_range": "all"})

    assert r.status_code == 200
    assert r.json() == [{"name": "Flood", "count": 1, "value": 1, "color": "#F59E0B"}]


async def test_a_seeded_slice_of_the_same_name_is_merged(api, db):
    await _event(db, "URBAN_FLOOD")
    await _event(db, "URBAN_FLOOD", display="Flood")
    await _event(db, "HEATWAVE")
    await _event(db, "HEATWAVE")
    await _event(db, "HEATWAVE")
    await _event(db, "FOG", status="REJECTED")
    await db.commit()

    r = await api.get("/api/events/distribution", params={"by": "hazard", "time_range": "all"})

    assert r.status_code == 200
    assert r.json() == [
        {"name": "Heatwave", "count": 3, "value": 3, "color": hazards.color_of("HEATWAVE")},
        {"name": "Flood", "count": 2, "value": 2, "color": "#F59E0B"},
    ]


def test_the_events_api_reads_the_taxonomy_rather_than_a_copy():
    from app.api import events

    assert events.EVENT_TYPE_LABELS is hazards.EVENT_TYPE_LABELS
    assert events.IMAGE_GRADIENTS is hazards.IMAGE_GRADIENTS
