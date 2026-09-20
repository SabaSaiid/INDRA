"""
Day 4 — verified events are produced to KAFKA_EVENTS_TOPIC.

Unit level: aiokafka is replaced with a fake, so no broker is needed. The live
check (rpk consume within 5s) is the integration-level drill in backend-todo.md.
"""

import asyncio
import json
import sys
import types

import pytest

from app.core.config import get_settings
from app.services import event_publisher
from app.workers import report_consumer

EVENT = {"id": "8c1f0000-0000-0000-0000-000000000001", "event_code": "WX-EV-TEST-A", "merged": False}


class FakeProducer:
    sent = []
    fail_on = None  # "start" | "send" | "hang"
    stopped = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def start(self):
        if FakeProducer.fail_on == "start":
            raise ConnectionError("broker down")
        if FakeProducer.fail_on == "hang":
            await asyncio.sleep(60)

    async def send_and_wait(self, topic, value, key=None):
        if FakeProducer.fail_on == "send":
            raise RuntimeError("send failed")
        FakeProducer.sent.append((topic, key, json.loads(value.decode("utf-8"))))

    async def stop(self):
        FakeProducer.stopped += 1


@pytest.fixture(autouse=True)
def fake_kafka(monkeypatch):
    FakeProducer.sent = []
    FakeProducer.fail_on = None
    FakeProducer.stopped = 0
    monkeypatch.setitem(sys.modules, "aiokafka", types.SimpleNamespace(AIOKafkaProducer=FakeProducer))


async def test_event_goes_to_the_events_topic_keyed_by_id():
    assert await event_publisher.publish_verified_event(EVENT) is True

    assert FakeProducer.sent == [
        (get_settings().KAFKA_EVENTS_TOPIC, EVENT["id"].encode("utf-8"), EVENT)
    ]
    assert FakeProducer.stopped == 1


@pytest.mark.parametrize("failure", ["start", "send"])
async def test_broker_failure_returns_false_and_still_stops_the_producer(failure):
    FakeProducer.fail_on = failure

    assert await event_publisher.publish_verified_event(EVENT) is False
    assert FakeProducer.sent == []
    assert FakeProducer.stopped == 1


async def test_hung_broker_is_cut_off_by_the_timeout(monkeypatch):
    monkeypatch.setattr(event_publisher, "PUBLISH_TIMEOUT_S", 0.1)
    FakeProducer.fail_on = "hang"

    assert await asyncio.wait_for(event_publisher.publish_verified_event(EVENT), timeout=2) is False


@pytest.fixture
def pipeline_returns(monkeypatch):
    import app.services.pipeline as pipeline

    def _set(result):
        async def _process(db, report):
            return result

        monkeypatch.setattr(pipeline, "process_report", _process)

    monkeypatch.setattr(report_consumer, "_ws_manager", None)
    return _set


async def test_consumer_publishes_the_event_the_pipeline_returned(pipeline_returns):
    pipeline_returns(EVENT)

    await report_consumer.handle_report_message({"id": "r-publish-1"})

    assert [payload for _, _, payload in FakeProducer.sent] == [EVENT]


async def test_consumer_publishes_nothing_when_there_is_no_event(pipeline_returns):
    pipeline_returns(None)

    await report_consumer.handle_report_message({"id": "r-publish-2"})

    assert FakeProducer.sent == []
