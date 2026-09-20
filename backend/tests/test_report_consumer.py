"""
Day 4 T4 — Kafka re-delivery must not re-broadcast NEW_REPORT.

Unit level: the WebSocket manager and process_report are fakes, so no broker
and no database are needed.
"""

import pytest

from app.services import cache
from app.workers import report_consumer


class FakeManager:
    def __init__(self):
        self.messages = []
        self.active_connections = []

    async def broadcast(self, message):
        self.messages.append(message)


@pytest.fixture
def manager(monkeypatch):
    m = FakeManager()
    monkeypatch.setattr(report_consumer, "_ws_manager", m)
    return m


@pytest.fixture
def pipeline_calls(monkeypatch):
    calls = []

    async def _process(db, report):
        calls.append(report.get("id"))
        return None

    import app.services.pipeline as pipeline

    monkeypatch.setattr(pipeline, "process_report", _process)
    return calls


def new_reports(manager):
    return [m for m in manager.messages if m["type"] == "NEW_REPORT"]


async def test_redelivered_message_is_broadcast_once_but_processed_every_time(manager, pipeline_calls):
    for rid in ["A", "B", "A"]:
        await report_consumer.handle_report_message({"id": rid})

    assert [m["report"]["id"] for m in new_reports(manager)] == ["A", "B"]
    assert pipeline_calls == ["A", "B", "A"]


async def test_message_without_id_is_broadcast_and_does_not_raise(manager, pipeline_calls):
    await report_consumer.handle_report_message({"raw_text": "no id"})
    await report_consumer.handle_report_message({"raw_text": "no id"})

    assert len(new_reports(manager)) == 2


async def test_memory_is_capped_and_evicts_the_oldest(manager, pipeline_calls):
    size = cache.MEMORY_SEEN_SIZE
    for i in range(1, size + 2):  # 2001 distinct ids
        await report_consumer.handle_report_message({"id": f"r{i}"})

    assert len(cache._memory_seen) == size
    await report_consumer.handle_report_message({"id": "r1"})

    assert len(new_reports(manager)) == size + 2  # r1 was evicted, so it broadcasts again
    assert len(cache._memory_seen) == size
