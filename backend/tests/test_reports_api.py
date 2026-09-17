"""
Day 2 T1, T2, T8 — POST /api/reports/submit.

Unit level: the database session and the Kafka producer are both replaced with
in-memory fakes, so these pin the endpoint's own behaviour — what it rejects,
what it stores, and what it publishes — without Docker. The live-DB versions
of the same checks are in test_reports_api_integration.py.
"""

import json
import sys
import types

import pytest
import pytest_asyncio

from app.core.database import get_db


class FakeSession:
    def __init__(self):
        self.inserts = []

    async def execute(self, statement, params=None):
        self.inserts.append(params)

    async def commit(self):
        pass


class FakeProducer:
    sent = []

    def __init__(self, **kwargs):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_and_wait(self, topic, value):
        FakeProducer.sent.append((topic, json.loads(value.decode("utf-8"))))


@pytest.fixture
def session():
    return FakeSession()


@pytest_asyncio.fixture
async def api(session, monkeypatch):
    import httpx

    from app.main import app

    FakeProducer.sent = []
    monkeypatch.setitem(sys.modules, "aiokafka", types.SimpleNamespace(AIOKafkaProducer=FakeProducer))

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def body(lat, lng, text="Knee-deep water on Boring Road near the Patna Women's College"):
    return {"latitude": lat, "longitude": lng, "text": text}


# ── T1: rejection ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lat, lng", [(48.85, 2.35), (-33.87, 151.21)])
async def test_out_of_india_is_422_and_nothing_is_stored_or_published(api, session, lat, lng):
    r = await api.post("/api/reports/submit", json=body(lat, lng))

    assert r.status_code == 422
    assert "outside India" in r.json()["detail"]
    assert session.inserts == []
    assert FakeProducer.sent == []


@pytest.mark.parametrize(
    "lat, lng",
    [(25.5941, 85.1376), (8.09, 77.55), (35.5, 77.0), (28.6139, 77.2090)],
)
async def test_in_india_is_accepted_with_coordinates_unchanged(api, session, lat, lng):
    r = await api.post("/api/reports/submit", json=body(lat, lng))

    assert r.status_code == 202
    assert len(session.inserts) == 1
    assert (session.inserts[0]["lat"], session.inserts[0]["lng"]) == (lat, lng)


# ── T2: message matches the stored row ─────────────────────────────────────────

async def test_published_message_matches_the_stored_row(api, session):
    # Swapped pair: stored coordinates differ from what the client sent, which
    # is exactly the case where the old message diverged from the row.
    r = await api.post("/api/reports/submit", json=body(85.1376, 25.5941))
    assert r.status_code == 202

    row = session.inserts[0]
    (topic, msg), = FakeProducer.sent

    assert msg["id"] == r.json()["id"]
    assert round(msg["latitude"], 6) == round(row["lat"], 6) == 25.5941
    assert round(msg["longitude"], 6) == round(row["lng"], 6) == 85.1376
    assert msg["raw_text"] == row["raw_text"]
    assert "text" not in msg
    assert msg["h3_res8"] == row["h3_cell"] and msg["h3_res8"]
    assert msg["credibility_score"] == row["credibility"]


# ── T8: credibility is computed, not 0.5 ───────────────────────────────────────

async def test_stored_credibility_reflects_report_quality(api, session):
    await api.post("/api/reports/submit", json=body(25.5941, 85.1376))
    await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text="flood"))

    specific, terse = (p["credibility"] for p in session.inserts)
    assert 0.5 <= specific <= 0.7
    assert terse < 0.4


# ── Day 4 T3: no false success ─────────────────────────────────────────────────

class FailingSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.rolled_back = False

    async def execute(self, statement, params=None):
        raise ConnectionRefusedError("postgres is down")

    async def rollback(self):
        self.rolled_back = True


async def test_unstored_report_is_503_and_never_published(api, monkeypatch):
    from app.core.database import get_db
    from app.main import app

    failing = FailingSession()

    async def _db():
        yield failing

    app.dependency_overrides[get_db] = _db
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 503
    assert r.json() == {"detail": "Report could not be stored"}
    assert failing.rolled_back
    assert FakeProducer.sent == []


async def test_stored_but_unpublished_report_is_202_not_queued(api, session, monkeypatch):
    async def _boom(self):
        raise ConnectionRefusedError("redpanda is down")

    monkeypatch.setattr(FakeProducer, "start", _boom)
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    assert r.json()["queued"] is False
    assert len(session.inserts) == 1
    assert FakeProducer.sent == []


async def test_stored_and_published_report_is_queued(api, session):
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    assert r.json()["queued"] is True
    assert len(FakeProducer.sent) == 1
