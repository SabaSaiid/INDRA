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


# ── The relay ──────────────────────────────────────────────────────────────────

from app.workers import outbox_relay  # noqa: E402


async def test_kafka_back_every_waiting_report_is_published_oldest_first(api, db, publisher):
    publisher.fail = True
    ids = []
    for _ in range(10):
        ids.append((await api.post("/api/reports/submit", json=REPORT)).json()["id"])

    # Still down: the batch stops at the first row and records why.
    assert await outbox_relay.relay_once(db, publisher) == (0, 1)
    attempts = (await db.execute(text("SELECT attempts FROM outbox ORDER BY id"))).scalars().all()
    assert attempts == [1] + [0] * 9
    assert "redpanda is down" in await _count(db, "SELECT last_error FROM outbox ORDER BY id LIMIT 1")

    # Back up: one pass drains all ten, in the order they were stored.
    publisher.fail = False
    assert await outbox_relay.relay_once(db, publisher) == (10, 0)
    assert [key for _, _, key in publisher.sent] == ids
    assert await _count(db, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0


async def test_two_relays_publish_each_row_exactly_once(db, publisher):
    await db.execute(text("""
        INSERT INTO outbox (topic, key, payload)
        SELECT 'indra.raw.reports', g::text, jsonb_build_object('id', g::text)
        FROM generate_series(1, 500) AS g
    """))
    await db.commit()

    async def relay_until_empty():
        total = 0
        async with async_session() as session:
            while True:
                published, failed = await outbox_relay.relay_once(session, publisher)
                if published == 0 and failed == 0:
                    return total
                total += published

    first, second = await asyncio.gather(relay_until_empty(), relay_until_empty())

    # Both relays did real work — they ran side by side — and between them
    # every row went exactly once.
    assert first > 0 and second > 0
    assert first + second == 500
    keys = [key for _, _, key in publisher.sent]
    assert len(keys) == 500
    assert len(set(keys)) == 500
    assert await _count(db, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0


async def test_a_resent_message_is_byte_for_byte_the_first(db, publisher):
    """
    The crash window: the broker acknowledged, the process died before the
    commit that marks the row. The next pass sends it again — identical, so
    the consumer's existing idempotency applies (test_report_consumer:
    broadcast once; test_pipeline: no second event, a duplicate stays skipped).
    """
    publisher.ready = False
    await ingest.store_report(
        db, source_type="CITIZEN_APP", raw_text="Water on the road",
        latitude=25.5941, longitude=85.1376,
    )
    publisher.ready = True

    assert await outbox_relay.relay_once(db, publisher) == (1, 0)
    await db.execute(text("UPDATE outbox SET published_at = NULL"))
    await db.commit()
    assert await outbox_relay.relay_once(db, publisher) == (1, 0)

    first, second = publisher.sent
    assert first == second


async def test_published_rows_are_pruned_after_seven_days_and_waiting_ones_never(db):
    await db.execute(text("""
        INSERT INTO outbox (topic, key, payload, created_at, published_at) VALUES
            ('t', 'old-published',   '{}', NOW() - INTERVAL '9 days',  NOW() - INTERVAL '8 days'),
            ('t', 'recent-published','{}', NOW() - INTERVAL '2 days',  NOW() - INTERVAL '1 day'),
            ('t', 'old-waiting',     '{}', NOW() - INTERVAL '30 days', NULL)
    """))
    await db.commit()

    assert await outbox_relay.cleanup_published(db) == 1
    left = (await db.execute(text("SELECT key FROM outbox ORDER BY key"))).scalars().all()
    assert left == ["old-waiting", "recent-published"]


# ── The relay loop's timing (no database) ──────────────────────────────────────

async def _run_loop(monkeypatch, starts, passes, iterations):
    """
    Drive start_outbox_relay() for a fixed number of sleeps. `starts` scripts
    ensure_started(); `passes` scripts relay_once(). Returns the sleep delays.
    """
    starts, passes = iter(starts), iter(passes)
    delays, resets = [], []

    class Scripted:
        async def ensure_started(self):
            return next(starts)

        async def reset(self):
            resets.append(True)

    async def fake_relay_once(db, publisher):
        return next(passes)

    async def fake_cleanup(db):
        return 0

    async def fake_sleep(seconds):
        delays.append(seconds)
        if len(delays) >= iterations:
            raise asyncio.CancelledError

    monkeypatch.setattr(kafka, "_publisher", Scripted())
    monkeypatch.setattr(outbox_relay, "relay_once", fake_relay_once)
    monkeypatch.setattr(outbox_relay, "cleanup_published", fake_cleanup)
    monkeypatch.setattr(outbox_relay.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await outbox_relay.start_outbox_relay()
    return delays, resets


async def test_while_the_broker_is_down_the_relay_keeps_probing_every_two_seconds(monkeypatch):
    delays, _ = await _run_loop(monkeypatch, starts=[False] * 5, passes=[], iterations=5)
    assert delays == [2.0] * 5


async def test_failed_publishes_back_off_to_thirty_seconds_and_success_resets(monkeypatch):
    delays, resets = await _run_loop(
        monkeypatch,
        starts=[True] * 7,
        passes=[(0, 1)] * 5 + [(3, 0), (0, 0)],
        iterations=7,
    )
    assert delays == [4.0, 8.0, 16.0, 30.0, 30.0, 2.0, 2.0]
    assert len(resets) == 5


async def test_a_full_batch_goes_round_again_without_sleeping(monkeypatch):
    delays, _ = await _run_loop(
        monkeypatch,
        starts=[True] * 3,
        passes=[(outbox_relay.BATCH_SIZE, 0), (outbox_relay.BATCH_SIZE, 0), (7, 0)],
        iterations=3,
    )
    assert delays == [0, 0, 2.0]
