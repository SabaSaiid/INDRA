"""
Phase 1 T3 — the transactional outbox (BUG-060), against a real database.

The guarantees under test are Postgres's: one transaction for the report and
its message, and a row lock that keeps the request and the relay from
publishing the same row. A fake publisher stands in for Kafka, so a "broker
outage" is a flag.
"""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import wipe_event_tables

from app.core.database import async_session
from app.services import ingest, kafka

pytestmark = pytest.mark.integration

REPORT = {"latitude": 25.5941, "longitude": 85.1376, "text": "Knee-deep water near Gandhi Maidan"}


class RecordingPublisher:
    """Stands in for the process's KafkaPublisher. `fail` is the broker being down."""

    def __init__(self):
        self.ready = True
        self.fail = False
        self.sent = []

    async def publish(self, topic, value, key, timeout):
        await asyncio.sleep(0)   # let concurrent relays interleave, as real I/O would
        if self.fail:
            raise ConnectionRefusedError("redpanda is down")
        self.sent.append((topic, json.loads(value.decode("utf-8")), key.decode("utf-8")))

    async def ensure_started(self):
        return self.ready and not self.fail

    async def reset(self):
        pass


@pytest.fixture
def publisher():
    fake = RecordingPublisher()
    kafka.set_publisher(fake)
    return fake


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


@pytest_asyncio.fixture
async def api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _count(db, sql):
    return (await db.execute(text(sql))).scalar()


# ── Storing and the immediate publish ──────────────────────────────────────────

async def test_kafka_up_the_message_is_published_within_a_second(api, db, publisher):
    r = await api.post("/api/reports/submit", json=REPORT)

    assert r.status_code == 202
    assert r.json()["queued"] is True
    created, published = (
        await db.execute(
            text("SELECT created_at, published_at FROM outbox WHERE key = :id"),
            {"id": r.json()["id"]},
        )
    ).one()
    assert published is not None
    assert published - created < timedelta(seconds=1)
    (topic, msg, key), = publisher.sent
    assert (msg["id"], key) == (r.json()["id"], r.json()["id"])


async def test_kafka_down_every_report_is_kept_and_waits(api, db, publisher):
    publisher.fail = True

    for _ in range(10):
        r = await api.post("/api/reports/submit", json=REPORT)
        assert r.status_code == 202
        assert (r.json()["queued"], r.json()["will_retry"]) == (False, True)

    assert await _count(db, "SELECT count(*) FROM raw_reports") == 10
    assert await _count(db, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 10
    assert publisher.sent == []


async def test_a_report_that_cannot_be_stored_leaves_no_message(db, publisher):
    with pytest.raises(ingest.StoreError):
        await ingest.store_report(
            db, source_type="NOT_A_SOURCE", raw_text="Water on the road",
            latitude=25.5941, longitude=85.1376,
        )

    assert await _count(db, "SELECT count(*) FROM raw_reports") == 0
    assert await _count(db, "SELECT count(*) FROM outbox") == 0
    assert publisher.sent == []


async def test_a_message_that_cannot_be_stored_takes_its_report_with_it(db, publisher, monkeypatch):
    """The atomicity itself: the outbox insert fails after the report insert succeeded."""
    monkeypatch.setattr(
        ingest, "_INSERT_OUTBOX", text("INSERT INTO outbox (no_such_column) VALUES (1) RETURNING id")
    )

    with pytest.raises(ingest.StoreError):
        await ingest.store_report(
            db, source_type="CITIZEN_APP", raw_text="Water on the road",
            latitude=25.5941, longitude=85.1376,
        )

    assert await _count(db, "SELECT count(*) FROM raw_reports") == 0
    assert publisher.sent == []


async def test_a_row_the_relay_holds_is_left_to_the_relay(db, publisher):
    publisher.ready = False
    stored = await ingest.store_report(
        db, source_type="CITIZEN_APP", raw_text="Water on the road",
        latitude=25.5941, longitude=85.1376,
    )
    outbox_id = await _count(db, "SELECT id FROM outbox")
    publisher.ready = True

    async with async_session() as relay:
        # The relay's lock, held while the request tries to publish.
        await relay.execute(text("SELECT id FROM outbox WHERE id = :id FOR UPDATE"), {"id": outbox_id})
        queued = await ingest.publish_now(db, outbox_id, "t", str(stored.id), {"id": str(stored.id)})
        await relay.rollback()

    assert queued is False
    assert publisher.sent == []
    assert await _count(db, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 1
