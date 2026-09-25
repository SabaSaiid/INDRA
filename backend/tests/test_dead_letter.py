"""
Phase 2 T8 — a failing message is retried, then dead-lettered (BUG-081).

Before T8, offsets were auto-committed and the pipeline never raised, so a
report the pipeline crashed on was logged and dropped. These drive
`process_message` with a fake consumer and fake messages: what is committed,
what is sought back to, and what reaches the dead-letter topic.
"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.services import cache, kafka
from app.workers import report_consumer
from app.workers.report_consumer import failure_key, process_message


class FakeConsumer:
    def __init__(self):
        self.commits = []
        self.seeks = []

    async def commit(self, offsets):
        self.commits.append({(tp.topic, tp.partition): off for tp, off in offsets.items()})

    def seek(self, tp, offset):
        self.seeks.append(((tp.topic, tp.partition), offset))


class FakePublisher:
    def __init__(self, fail=False):
        self.ready = True
        self.fail = fail
        self.sent = []

    async def ensure_started(self):
        self.ready = True

    async def publish(self, topic, value, key, timeout):
        if self.fail:
            raise ConnectionRefusedError("redpanda is down")
        self.sent.append((topic, json.loads(value.decode("utf-8")), key))

    def mark_unhealthy(self):
        self.ready = False


def _msg(offset=7, value=None):
    return SimpleNamespace(
        topic="indra.raw.reports", partition=0, offset=offset,
        key=b"report-key", value=value if value is not None else {"id": "abc"},
    )


@pytest.fixture
def consumer():
    return FakeConsumer()


@pytest.fixture
def publisher():
    fake = FakePublisher()
    kafka.set_publisher(fake)
    return fake


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(get_settings(), "PIPELINE_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(get_settings(), "PIPELINE_MAX_ATTEMPTS", 3)


@pytest.fixture
def pipeline_result(monkeypatch):
    """Set .error to what handle_report_message returns; None is success."""
    state = SimpleNamespace(error=None, calls=0)

    async def handle(report):
        state.calls += 1
        return state.error

    monkeypatch.setattr(report_consumer, "handle_report_message", handle)
    return state


async def test_success_commits_the_next_offset(consumer, publisher, pipeline_result):
    assert await process_message(consumer, _msg(offset=7)) == "ok"
    assert consumer.commits == [{("indra.raw.reports", 0): 8}]
    assert consumer.seeks == []
    assert publisher.sent == []


async def test_a_failure_is_retried_twice_then_dead_lettered(consumer, publisher, pipeline_result):
    pipeline_result.error = "OperationalError: connection refused"
    msg = _msg(offset=7)

    assert await process_message(consumer, msg) == "retry"
    assert await process_message(consumer, msg) == "retry"
    assert consumer.commits == []
    assert consumer.seeks == [(("indra.raw.reports", 0), 7)] * 2

    assert await process_message(consumer, msg) == "dead_lettered"
    assert consumer.commits == [{("indra.raw.reports", 0): 8}]
    (topic, record, key), = publisher.sent
    assert topic == get_settings().KAFKA_DLQ_TOPIC
    assert key == b"report-key"
    assert record["payload"] == {"id": "abc"}
    assert record["error"] == "OperationalError: connection refused"
    assert record["attempts"] == 3
    assert record["source"] == {"topic": "indra.raw.reports", "partition": 0, "offset": 7}


async def test_the_next_message_is_processed_after_a_dead_letter(consumer, publisher, pipeline_result):
    pipeline_result.error = "boom"
    for _ in range(3):
        await process_message(consumer, _msg(offset=7))
    pipeline_result.error = None
    assert await process_message(consumer, _msg(offset=8)) == "ok"
    assert consumer.commits[-1] == {("indra.raw.reports", 0): 9}


async def test_a_success_on_retry_clears_the_count(consumer, publisher, pipeline_result):
    msg = _msg(offset=7)
    pipeline_result.error = "transient"
    await process_message(consumer, msg)
    pipeline_result.error = None
    assert await process_message(consumer, msg) == "ok"
    # Counted per message, and forgotten once it succeeds.
    assert await cache.incr(failure_key(msg), 60) == 1


async def test_failures_are_counted_per_message_not_per_report(consumer, publisher, pipeline_result):
    pipeline_result.error = "boom"
    await process_message(consumer, _msg(offset=7, value={"id": "same"}))
    await process_message(consumer, _msg(offset=7, value={"id": "same"}))
    # The same report replayed from the DLQ is a new message with fresh tries.
    assert await process_message(consumer, _msg(offset=50, value={"id": "same"})) == "retry"


async def test_a_message_that_is_not_json_is_dead_lettered_at_once(consumer, publisher, pipeline_result):
    msg = _msg(value=report_consumer._decode(b"\xff not json"))
    assert await process_message(consumer, msg) == "dead_lettered"
    assert pipeline_result.calls == 0
    assert publisher.sent[0][1]["error"] == "message is not JSON"


async def test_if_the_dead_letter_topic_is_unreachable_nothing_is_committed(consumer, pipeline_result):
    kafka.set_publisher(FakePublisher(fail=True))
    pipeline_result.error = "boom"
    msg = _msg(offset=7)
    for _ in range(3):
        outcome = await process_message(consumer, msg)
    assert outcome == "retry"
    assert consumer.commits == []


def test_decode_never_raises():
    assert report_consumer._decode(b'{"id": "x"}') == {"id": "x"}
    assert report_consumer._decode(b"[1, 2]") == {"_undecodable": "[1, 2]"}
    assert report_consumer._decode(b"") == {"_undecodable": ""}


# ── What counts as a failure ───────────────────────────────────────────────────

@pytest.mark.integration
async def test_an_unknown_report_id_is_skipped_not_a_failure(monkeypatch):
    monkeypatch.setattr(report_consumer, "_ws_manager", None)
    error = await report_consumer.handle_report_message(
        {"id": "00000000-0000-0000-0000-000000000000"}
    )
    assert error is None


@pytest.mark.integration
async def test_a_pipeline_crash_is_reported_as_a_failure(monkeypatch):
    from app.services import pipeline

    async def explode(db, report_id):
        raise RuntimeError("the pipeline broke")

    monkeypatch.setattr(pipeline, "_load_report", explode)
    monkeypatch.setattr(report_consumer, "_ws_manager", None)
    error = await report_consumer.handle_report_message(
        {"id": "00000000-0000-0000-0000-000000000001"}
    )
    assert error == "RuntimeError: the pipeline broke"


@pytest.mark.integration
async def test_a_dead_letter_is_counted_in_feed_status(consumer, publisher, pipeline_result):
    from app.core.database import async_session

    async with async_session() as db:
        await db.execute(text("DELETE FROM feed_status WHERE feed = 'dead_letter'"))
        await db.commit()
    pipeline_result.error = "boom"
    for _ in range(3):
        await process_message(consumer, _msg(offset=99))
    async with async_session() as db:
        row = (await db.execute(
            text("SELECT rows_total, last_error FROM feed_status WHERE feed = 'dead_letter'")
        )).one()
        await db.execute(text("DELETE FROM feed_status WHERE feed = 'dead_letter'"))
        await db.commit()
    assert tuple(row) == (1, "boom")
