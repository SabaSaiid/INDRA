"""
BUG-034 — the KPI strip's numbers must mean what their labels say.

"Verified Events" counted every event the pipeline had not rejected, so the
one event in the live database — confidence 0.4984, QUARANTINED, quadrant
"Noise" — was advertised as verified. The system's own scoring called it
noise and the dashboard promoted it on the way to the screen.

This is BUG-024's shape in a new place. That was a fabricated event; this is
a real event wearing a status the engine never gave it, and it is harder to
catch because there is nothing in the response to disbelieve.
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
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _seed(db, review_status: str, severity: str = "MODERATE") -> None:
    event_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score,
                 review_status, quadrant, impact_radius_km, center_point)
            VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD',
                    CAST(:sev AS severity_enum), 0.5,
                    CAST(:status AS review_status_enum), 'Noise', 1.0,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326))
        """),
        {
            "id": str(event_id),
            "code": f"INDRA-KPI-{str(event_id)[:6]}",
            "status": review_status,
            "sev": severity,
        },
    )


@pytest_asyncio.fixture
async def clean_db():
    async with async_session() as db:
        await wipe_event_tables(db)
        try:
            yield db
        finally:
            await wipe_event_tables(db)


async def _summary(api):
    r = await api.get("/api/dashboard/summary")
    assert r.status_code == 200
    return r.json()


async def test_a_quarantined_event_is_not_counted_as_verified(api, clean_db):
    """The exact shape of the live defect: one quarantined event, nothing else."""
    await _seed(clean_db, "QUARANTINED")
    await clean_db.commit()

    summary = await _summary(api)
    assert summary["verified_events"] == 0
    assert summary["awaiting_review"] == 1


async def test_an_escalated_event_is_awaiting_review_not_verified(api, clean_db):
    await _seed(clean_db, "PENDING_HUMAN_REVIEW")
    await clean_db.commit()

    summary = await _summary(api)
    assert summary["verified_events"] == 0
    assert summary["awaiting_review"] == 1


@pytest.mark.parametrize("status", ["AUTO_PUBLISHED", "HUMAN_APPROVED"])
async def test_a_genuinely_verified_event_is_counted(api, clean_db, status):
    await _seed(clean_db, status)
    await clean_db.commit()

    summary = await _summary(api)
    assert summary["verified_events"] == 1
    assert summary["awaiting_review"] == 0


async def test_a_rejected_event_is_counted_in_neither(api, clean_db):
    """An operator dismissing an event must not have it reappear as a total."""
    await _seed(clean_db, "REJECTED")
    await clean_db.commit()

    summary = await _summary(api)
    assert summary["verified_events"] == 0
    assert summary["awaiting_review"] == 0


async def test_the_split_loses_nothing(api, clean_db):
    """
    Correcting the number must not hide anything: every non-rejected event
    still appears in exactly one of the two tiles. That is why the fix is a
    split and not simply a tighter filter.
    """
    for status in [
        "AUTO_PUBLISHED", "HUMAN_APPROVED",
        "PENDING_HUMAN_REVIEW", "QUARANTINED", "QUARANTINED",
    ]:
        await _seed(clean_db, status)
    await _seed(clean_db, "REJECTED")
    await clean_db.commit()

    summary = await _summary(api)
    assert summary["verified_events"] == 2
    assert summary["awaiting_review"] == 3
    assert summary["verified_events"] + summary["awaiting_review"] == 5


async def test_active_alerts_is_reported(api, clean_db):
    """
    The count exists at all. 112 real CAP warnings were being polled, parsed
    and stored, and appeared on no surface of the console (BUG-037).
    """
    summary = await _summary(api)
    assert "active_alerts" in summary
    assert isinstance(summary["active_alerts"], int)
    assert summary["active_alerts"] >= 0
