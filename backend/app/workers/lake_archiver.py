"""
INDRA Platform — Report stream archiver (layers 2 and 7, Phase 2 T9)

A second consumer of `indra.raw.reports`, in its own group, `indra-archive`.
Kafka delivers the whole stream to every group independently, so the pipeline
(`indra-report-processor`) and this archiver each see every message, and
neither can slow the other down. That is what a message bus is for, and this
is the first time INDRA has used it for it.

Every message is appended, untouched, as one JSON line:

    {"kafka_topic", "kafka_partition", "kafka_offset", "kafka_timestamp",
     "received_at", "key", "payload"}

and the buffer is written to the lake as one gzipped object under
`raw/source=reports/…` every LAKE_FLUSH_SECONDS or LAKE_FLUSH_BYTES, whichever
comes first. Kafka may deliver a message twice; the partition and offset on
each line are what lets Phase 6's compaction keep one copy.

**Nothing is lost when the store is down.** Offsets are committed only after
the object is written. If a write fails, the buffer is dropped and the
consumer seeks back to the first message it held, then waits and reads the
same messages again. Its memory never grows with the outage, and Kafka keeps
the messages meanwhile.

Off when the object store is not configured, or LAKE_ARCHIVE_ENABLED is false.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.workers.lake_archiver")

GROUP_ID = "indra-archive"
SOURCE = "reports"
# How long to wait after a failed write before reading the messages again.
RETRY_AFTER_FAILURE_SECONDS = 10.0


def archive_line(msg) -> Dict[str, Any]:
    """One Kafka message as the line the lake keeps."""
    raw = msg.value or b""
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except Exception:
        # Kept, not dropped: bronze is what arrived, readable or not.
        payload = {"_undecodable": raw.decode("utf-8", "replace")}
    return {
        "kafka_topic": msg.topic,
        "kafka_partition": msg.partition,
        "kafka_offset": msg.offset,
        "kafka_timestamp": msg.timestamp,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "key": msg.key.decode("utf-8", "replace") if msg.key else None,
        "payload": payload,
    }


class Buffer:
    """Lines waiting to be written, and the offsets they cover."""

    def __init__(self):
        self.lines: List[bytes] = []
        self.size = 0
        self.first_at: Optional[float] = None
        self.next_offsets: Dict[Any, int] = {}   # TopicPartition → offset to commit
        self.first_offsets: Dict[Any, int] = {}  # TopicPartition → where to rewind to

    def add(self, msg) -> None:
        line = (json.dumps(archive_line(msg), ensure_ascii=False) + "\n").encode("utf-8")
        self.lines.append(line)
        self.size += len(line)
        if self.first_at is None:
            self.first_at = time.monotonic()
        from aiokafka import TopicPartition

        tp = TopicPartition(msg.topic, msg.partition)
        self.next_offsets[tp] = max(self.next_offsets.get(tp, 0), msg.offset + 1)
        self.first_offsets[tp] = min(self.first_offsets.get(tp, msg.offset), msg.offset)

    def due(self, now: float) -> bool:
        settings = get_settings()
        if not self.lines:
            return False
        return (
            self.size >= settings.LAKE_FLUSH_BYTES
            or now - (self.first_at or now) >= settings.LAKE_FLUSH_SECONDS
        )

    def clear(self) -> None:
        self.__init__()


async def flush(consumer, buffer: Buffer) -> bool:
    """
    Write the buffer as one object, then commit its offsets. True on success.
    On failure nothing is committed and the consumer is rewound to what was.
    """
    from app.services import lake

    now = datetime.now(timezone.utc)
    key = lake.object_key(SOURCE, now, "jsonl")
    try:
        await lake.put_object(
            key,
            b"".join(buffer.lines),
            "application/x-ndjson",
            {"source": SOURCE, "lines": str(len(buffer.lines)), "fetched_at": now.isoformat()},
        )
    except Exception as e:
        logger.warning(
            f"Archive write failed ({len(buffer.lines)} messages); nothing committed, "
            f"re-reading them in {RETRY_AFTER_FAILURE_SECONDS:.0f}s: {type(e).__name__}: {e}"
        )
        # Rewind each partition to the first message this buffer held: exactly
        # the messages whose offsets were never committed. (seek_to_committed
        # would not do for a partition that has no committed offset yet.)
        for tp, offset in buffer.first_offsets.items():
            consumer.seek(tp, offset)
        buffer.clear()
        return False

    await consumer.commit(dict(buffer.next_offsets))
    logger.info(f"Archived {len(buffer.lines)} messages to {key}")
    buffer.clear()
    return True


async def start_lake_archiver() -> None:
    """The lifespan task."""
    settings = get_settings()
    from app.services import objectstore

    if not settings.LAKE_ARCHIVE_ENABLED:
        logger.info("Lake archiver disabled (LAKE_ARCHIVE_ENABLED=false)")
        return
    if not objectstore.configured():
        logger.info("Lake archiver off: the object store is not configured")
        return

    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.warning("aiokafka not available — lake archiver disabled")
        return

    from app.workers.report_consumer import check_kafka_connection

    retry_delay = 5
    while True:
        consumer = None
        try:
            if not await check_kafka_connection(settings.KAFKA_BOOTSTRAP_SERVERS):
                await asyncio.sleep(15)
                continue
            consumer = AIOKafkaConsumer(
                settings.KAFKA_REPORTS_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=GROUP_ID,
                # A new group starts at the beginning: the first run archives
                # whatever the topic still retains.
                auto_offset_reset="earliest",
                enable_auto_commit=False,
            )
            await consumer.start()
            logger.info(f"✓ Lake archiver consuming {settings.KAFKA_REPORTS_TOPIC} as {GROUP_ID}")
            retry_delay = 5

            buffer = Buffer()
            paused_until = 0.0
            while True:
                if paused_until > time.monotonic():
                    # Waiting out a failed write, reading nothing. The client
                    # heartbeats in the background, and the pause is far inside
                    # Kafka's max poll interval, so the group stays alive.
                    await asyncio.sleep(1)
                    continue
                batch = await consumer.getmany(timeout_ms=1000, max_records=500)
                for messages in batch.values():
                    for msg in messages:
                        buffer.add(msg)
                if buffer.due(time.monotonic()):
                    if not await flush(consumer, buffer):
                        paused_until = time.monotonic() + RETRY_AFTER_FAILURE_SECONDS

        except asyncio.CancelledError:
            logger.info("Lake archiver shutting down...")
            raise
        except Exception as e:
            logger.warning(f"Lake archiver restarting after an error: {type(e).__name__}: {e}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        finally:
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass
