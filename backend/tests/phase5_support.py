"""
Helpers for Phase 5's database tests: the API client, operator tokens, a
clean database, citizen reports filed through the real route, and events to
put them in.

A device is an `X-Reporter-Id`; with REPORTER_SALT set (the `salted`
fixture), its keyed hash is what the report stores and what the media and
withdrawal routes check ownership against.
"""

import json
import uuid
from typing import Dict, List, Optional

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session
from tests.conftest import wipe_event_tables

PATNA = (25.5941, 85.1376)
FLOOD_TEXT = "Knee deep water outside my house in Kankarbagh, drain overflowing"
_TOKENS: Dict[str, Dict[str, str]] = {}


@pytest_asyncio.fixture
async def api():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def tokens(api, accounts):
    if not _TOKENS:
        for user, (password, *_rest) in accounts.items():
            r = await api.post("/api/auth/token", data={"username": user, "password": password})
            assert r.status_code == 200, r.text
            _TOKENS[user] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _TOKENS


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


@pytest.fixture
def salted(monkeypatch):
    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "test-salt")


@pytest.fixture
def broadcasts(monkeypatch):
    """Every WebSocket message the app sends, instead of sending it."""
    from app.main import ws_manager

    sent: List[dict] = []

    async def record(message):
        sent.append(message)

    monkeypatch.setattr(ws_manager, "broadcast", record)
    return sent


def device(n: int) -> Dict[str, str]:
    return {"X-Reporter-Id": f"device-{n:04d}-0000-4000-8000-000000000000"}


async def submit(api, n: int = 1, text_: str = FLOOD_TEXT, lat: float = PATNA[0], lng: float = PATNA[1],
                 headers: Optional[Dict[str, str]] = None, **extra) -> httpx.Response:
    """POST /api/reports/submit as device n."""
    return await api.post(
        "/api/reports/submit",
        json={"latitude": lat, "longitude": lng, "text": text_, **extra},
        headers={**device(n), **(headers or {})},
    )


async def filed(api, n: int = 1, **kw) -> Dict[str, str]:
    """A report filed by device n: {"id", "docket"}. Fails the test if it was not 202."""
    r = await submit(api, n, **kw)
    assert r.status_code == 202, r.text
    return r.json()


async def make_event(db, *, status: str = "PENDING_HUMAN_REVIEW", report_ids=()) -> str:
    """An event, with the given reports in it."""
    event_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO verified_events
                (id, event_code, event_type, severity, confidence_score, review_status, quadrant,
                 impact_radius_km, center_point, verification_receipt, hazard_family)
            VALUES (CAST(:id AS uuid), :code, 'URBAN_FLOOD', 'MODERATE', 0.5,
                    CAST(:status AS review_status_enum), 'Noise', 1.0,
                    ST_SetSRID(ST_MakePoint(85.1376, 25.5941), 4326), CAST(:receipt AS jsonb), 'water')
        """),
        {"id": event_id, "code": f"INDRA-P5-{event_id[:8]}", "status": status,
         "receipt": json.dumps({"confidence_score": 0.5})},
    )
    if report_ids:
        await db.execute(
            text("UPDATE raw_reports SET event_id = CAST(:e AS uuid) WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"e": event_id, "ids": [str(r) for r in report_ids]},
        )
    await db.commit()
    return event_id


async def report_row(db, report_id) -> dict:
    row = (await db.execute(
        text("SELECT * FROM raw_reports WHERE id = CAST(:id AS uuid)"), {"id": str(report_id)}
    )).fetchone()
    await db.commit()
    return dict(row._mapping) if row else None


async def media_rows(db, report_id=None) -> List[dict]:
    where = "WHERE report_id = CAST(:id AS uuid)" if report_id else ""
    rows = (await db.execute(
        text(f"SELECT * FROM report_media {where} ORDER BY created_at, id"),
        {"id": str(report_id)} if report_id else {},
    )).fetchall()
    await db.commit()
    return [dict(r._mapping) for r in rows]
