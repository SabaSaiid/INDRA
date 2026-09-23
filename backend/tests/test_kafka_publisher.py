"""
Phase 1 T3 — one Kafka producer per process (services/kafka.py).

Unit level: aiokafka is replaced with a fake module and the TCP probe with a
stub, so no broker is needed.
"""

import asyncio
import sys
import types

import pytest

from app.services import kafka


class FakeProducer:
    built = 0
    fail_start = None   # None, "raise" or "hang"
    fail_send = None    # None or "hang"

    def __init__(self, **kwargs):
        FakeProducer.built += 1
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.sent = []

    async def start(self):
        if FakeProducer.fail_start == "raise":
            raise ConnectionRefusedError("refused")
        if FakeProducer.fail_start == "hang":
            await asyncio.sleep(10)
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send_and_wait(self, topic, value, key=None):
        if FakeProducer.fail_send == "hang":
            await asyncio.sleep(10)
        self.sent.append((topic, value, key))


@pytest.fixture
def broker(monkeypatch):
    """A reachable broker and a working fake aiokafka; tests break one thing at a time."""
    state = {"reachable": True}

    async def probe(servers, timeout=1.5):
        return state["reachable"]

    FakeProducer.built = 0
    FakeProducer.fail_start = None
    FakeProducer.fail_send = None
    monkeypatch.setitem(sys.modules, "aiokafka", types.SimpleNamespace(AIOKafkaProducer=FakeProducer))
    monkeypatch.setattr("app.workers.report_consumer.check_kafka_connection", probe)
    return state


async def test_a_started_publisher_is_ready_and_sends(broker):
    p = kafka.KafkaPublisher("localhost:19092")
    assert not p.ready

    assert await p.ensure_started() is True
    assert p.ready
    await p.publish("indra.raw.reports", b"{}", b"k", timeout=1.0)
    assert p._producer.sent == [("indra.raw.reports", b"{}", b"k")]


async def test_one_producer_for_the_process_not_one_per_call(broker):
    p = kafka.KafkaPublisher("localhost:19092")
    for _ in range(5):
        assert await p.ensure_started()
    assert FakeProducer.built == 1


async def test_an_unreachable_broker_is_not_even_attempted(broker):
    broker["reachable"] = False
    p = kafka.KafkaPublisher("localhost:19092")

    assert await p.ensure_started() is False
    assert not p.ready
    assert FakeProducer.built == 0


async def test_a_failed_start_is_cleaned_up_and_reported_as_not_ready(broker):
    FakeProducer.fail_start = "raise"
    p = kafka.KafkaPublisher("localhost:19092")

    assert await p.ensure_started() is False
    assert not p.ready


async def test_a_hung_start_gives_up_within_the_timeout(broker, monkeypatch):
    monkeypatch.setattr(kafka, "START_TIMEOUT_SECONDS", 0.1)
    FakeProducer.fail_start = "hang"
    p = kafka.KafkaPublisher("localhost:19092")

    started = await asyncio.wait_for(p.ensure_started(), timeout=2.0)
    assert started is False


async def test_publishing_without_a_producer_raises(broker):
    p = kafka.KafkaPublisher("localhost:19092")
    with pytest.raises(RuntimeError, match="not started"):
        await p.publish("t", b"{}", None, timeout=1.0)


async def test_a_hung_send_raises_within_its_cap(broker):
    p = kafka.KafkaPublisher("localhost:19092")
    await p.ensure_started()
    FakeProducer.fail_send = "hang"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(p.publish("t", b"{}", None, timeout=0.1), timeout=2.0)


async def test_reset_stops_the_producer_and_the_next_start_builds_a_fresh_one(broker):
    p = kafka.KafkaPublisher("localhost:19092")
    await p.ensure_started()
    first = p._producer

    await p.reset()
    assert not p.ready
    assert first.stopped

    assert await p.ensure_started()
    assert p._producer is not first
    assert FakeProducer.built == 2


async def test_a_failed_publish_takes_the_producer_out_of_service_until_it_is_rebuilt(broker):
    """A request marks it; requests then skip it; the relay's ensure_started() rebuilds it."""
    p = kafka.KafkaPublisher("localhost:19092")
    await p.ensure_started()
    first = p._producer

    p.mark_unhealthy()
    assert not p.ready

    assert await p.ensure_started() is True
    assert p.ready
    assert p._producer is not first
    assert first.stopped
    assert FakeProducer.built == 2


async def test_an_outage_is_logged_once_not_once_per_attempt(broker, caplog):
    broker["reachable"] = False
    p = kafka.KafkaPublisher("localhost:19092")

    with caplog.at_level("WARNING", logger="indra.services.kafka"):
        for _ in range(3):
            await p.ensure_started()

    assert sum("Kafka producer unavailable" in m for m in caplog.messages) == 1


def test_the_process_has_one_publisher_until_it_is_replaced():
    assert kafka.get_publisher() is kafka.get_publisher()
    fake = object()
    kafka.set_publisher(fake)
    assert kafka.get_publisher() is fake
