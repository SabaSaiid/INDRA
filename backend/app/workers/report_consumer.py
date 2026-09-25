"""
INDRA Platform — Report Consumer Worker
Background aiokafka consumer that reads from indra.raw.reports, runs the
verification pipeline, broadcasts NEW_REPORT / VERIFIED_EVENT WebSocket messages,
and publishes verified events to indra.verified.events.

**A failing message is retried, then dead-lettered (Phase 2 T8).** Offsets were
auto-committed and the pipeline never raises, so a report the pipeline crashed
on was logged and silently dropped: nothing retried it and nothing recorded it.
Now offsets are committed by hand, after each message is dealt with:

* the pipeline succeeded (event or not)            → commit, next message;
* it failed, fewer than PIPELINE_MAX_ATTEMPTS times → seek back and retry it
  after PIPELINE_RETRY_DELAY_SECONDS (the count is kept in Redis, per message);
* it failed the last time                          → publish it, with the
  error, to KAFKA_DLQ_TOPIC; commit; next message.

So one bad message holds its partition for a few seconds at most and can never
block it, and every message the pipeline gave up on is kept where
`scripts/replay_dlq.py` can send it back. A message whose report id is not in
the database is not a failure — the pipeline skips it, as it always has.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.services import cache

logger = logging.getLogger("indra.workers.report_consumer")
settings = get_settings()

# Reference to the WebSocket manager — set by main.py at startup
_ws_manager = None


def set_ws_manager(manager):
    global _ws_manager
    _ws_manager = manager


# Kafka delivers at least once: after a rebalance or a restart before the offset
# was committed, the same report arrives again. The pipeline is idempotent on
# re-delivery (a linked or suppressed report is skipped), but the live feed is
# not, so a re-delivered message would show the same report twice. The ids of
# recently broadcast reports are remembered in Redis for 24 hours, and in process
# memory (oldest evicted first) whenever Redis is unavailable.
#
# On the memory path this is per process: a restarted backend has an empty memory
# and will broadcast a re-delivered report once more. With Redis answering, a
# restart no longer re-broadcasts — which was the whole point of moving it.
# Flushing Redis forgets, deliberately; that is recorded in bug.md as BY-DESIGN.
BROADCAST_MEMORY_TTL_SECONDS = 24 * 60 * 60

# Source types a poller collects rather than a person files.
COLLECTED_SOURCE_TYPES = {"SOCIAL_MEDIA", "NEWS_MEDIA"}
BROADCAST_KEY_PREFIX = "bcast:"


async def _first_broadcast(report_id: Optional[str]) -> bool:
    """True the first time an id is seen (within memory). No id → always True."""
    if not report_id:
        return True
    return await cache.set_if_absent(
        BROADCAST_KEY_PREFIX + report_id,
        ttl_seconds=BROADCAST_MEMORY_TTL_SECONDS,
    )


async def handle_report_message(report_data: Dict[str, Any]) -> Optional[str]:
    """
    One consumed message: broadcast NEW_REPORT (once per report id), run the
    verification pipeline (every time), broadcast VERIFIED_EVENT if it produced
    or updated an event. Never raises — the consumer loop must survive.

    Returns None when the message was dealt with, or why the pipeline failed on
    it, which the consumer loop counts towards the dead-letter topic.
    """
    failure: Optional[str] = None
    try:
        report_id = report_data.get("id")
        logger.info(f"Received report: {report_id or 'unknown'}")

        # NEW_REPORT keeps the existing frontend contract. VERIFIED_EVENT is
        # additive on top of it.
        #
        # A post or headline a poller collected goes out as NEW_FEED_ITEM, not
        # NEW_REPORT (Phase 2). The dashboard refetches its panels on every
        # NEW_REPORT, and one news tick stores dozens of headlines at once: as
        # NEW_REPORTs they would trigger dozens of refetches in a second, on
        # every open screen. The new type is additive, so a dashboard that does
        # not listen for it is unaffected.
        if _ws_manager and await _first_broadcast(str(report_id) if report_id else None):
            collected = report_data.get("source_type") in COLLECTED_SOURCE_TYPES
            await _ws_manager.broadcast({
                "type": "NEW_FEED_ITEM" if collected else "NEW_REPORT",
                "report": report_data,
            })

        # Run the verification pipeline. The worker lives outside FastAPI's
        # dependency injection, so it takes a session from the sessionmaker
        # directly rather than via Depends(get_db).
        event = None
        try:
            from app.core.database import async_session
            from app.services import pipeline

            async with async_session() as db:
                event = await pipeline.process_report(db, report_data)
            # process_report fails soft and returns None; this tells a crash
            # from "no event", in the same task (see pipeline.take_failure).
            failure = pipeline.take_failure()
        except Exception as e:
            # process_report already fails soft; this guards the session/import
            # layer around it — a database that is down, for one.
            logger.error(f"Pipeline invocation failed: {e}")
            failure = f"{type(e).__name__}: {e}"

        # None is a normal outcome — a duplicate, or a report with too little
        # corroboration to be an event yet.
        if event and _ws_manager:
            await _ws_manager.broadcast({
                "type": "VERIFIED_EVENT",
                "event": event,
            })
            logger.info(
                f"Broadcast VERIFIED_EVENT {event.get('event_code')} "
                f"to {len(getattr(_ws_manager, 'active_connections', []))} client(s)"
            )

        # Outbound half of the stream: the same event goes to indra.verified.events.
        if event:
            from app.services.event_publisher import publish_verified_event

            await publish_verified_event(event)

    except Exception as e:
        logger.error(f"Error processing report message: {e}")
        failure = failure or f"{type(e).__name__}: {e}"

    return failure


# ── Retries and the dead-letter topic (Phase 2 T8) ─────────────────────────────

FAILURE_KEY_PREFIX = "pipeline:fail:"
# Long enough to outlive any retry sequence; short enough that the keys go.
FAILURE_COUNT_TTL_SECONDS = 24 * 60 * 60


def _decode(raw: bytes) -> Dict[str, Any]:
    """
    The message value as a dict. A body that is not JSON is wrapped rather than
    raised: a deserialiser that raises inside the consumer's iterator would
    stop the loop on that message forever.
    """
    try:
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {"_undecodable": raw.decode("utf-8", "replace")}
    except Exception:
        return {"_undecodable": raw.decode("utf-8", "replace") if raw else ""}


def failure_key(msg) -> str:
    """Per message, not per report: a replayed message is a new one and gets fresh tries."""
    return f"{FAILURE_KEY_PREFIX}{msg.topic}:{msg.partition}:{msg.offset}"


async def dead_letter(msg, error: str, attempts: int) -> bool:
    """
    Publish one message to the dead-letter topic with why it failed. True if it
    was published; False leaves it to be retried, so nothing is lost while
    Kafka itself is the problem.
    """
    from app.services import kafka
    from app.services.feed_status import DEAD_LETTER, record_tick

    record = {
        "payload": msg.value,
        "error": error,
        "attempts": attempts,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "source": {"topic": msg.topic, "partition": msg.partition, "offset": msg.offset},
    }
    publisher = kafka.get_publisher()
    try:
        if not publisher.ready:
            await publisher.ensure_started()
        await publisher.publish(
            settings.KAFKA_DLQ_TOPIC,
            json.dumps(record).encode("utf-8"),
            msg.key,
            timeout=5.0,
        )
    except Exception as e:
        logger.error(f"Could not dead-letter {msg.topic}[{msg.partition}]@{msg.offset}: {e}")
        return False

    await record_tick(DEAD_LETTER, ok=True, items=1, error=error, kind="stream")
    logger.error(
        f"Dead-lettered {msg.topic}[{msg.partition}]@{msg.offset} after {attempts} "
        f"attempt(s): {error}"
    )
    return True


async def process_message(consumer, msg) -> str:
    """
    Deal with one message and move its partition on, or not. Returns what
    happened: "ok", "retry" or "dead_lettered". See the module docstring.
    """
    from aiokafka import TopicPartition

    tp = TopicPartition(msg.topic, msg.partition)
    key = failure_key(msg)

    if isinstance(msg.value, dict) and "_undecodable" in msg.value:
        error, attempts = "message is not JSON", settings.PIPELINE_MAX_ATTEMPTS
    else:
        error = await handle_report_message(msg.value)
        if error is None:
            await consumer.commit({tp: msg.offset + 1})
            await cache.delete(key)
            return "ok"
        attempts = await cache.incr(key, FAILURE_COUNT_TTL_SECONDS)

    if attempts >= settings.PIPELINE_MAX_ATTEMPTS and await dead_letter(msg, error, attempts):
        await consumer.commit({tp: msg.offset + 1})
        await cache.delete(key)
        return "dead_lettered"

    logger.warning(
        f"Pipeline failed on {msg.topic}[{msg.partition}]@{msg.offset} "
        f"(attempt {attempts} of {settings.PIPELINE_MAX_ATTEMPTS}); retrying: {error}"
    )
    consumer.seek(tp, msg.offset)
    await asyncio.sleep(settings.PIPELINE_RETRY_DELAY_SECONDS)
    return "retry"


async def check_kafka_connection(bootstrap_servers: str, timeout: float = 1.5) -> bool:
    """Checks if the Kafka/Redpanda broker port is open without raising library errors."""
    try:
        first_server = bootstrap_servers.split(",")[0].strip()
        host, port_str = first_server.split(":")
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port_str)),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def start_report_consumer():
    """
    Long-running coroutine that consumes from Redpanda/Kafka topic
    and broadcasts new reports to WebSocket clients.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.warning("aiokafka not available — report consumer disabled")
        return

    consumer: Optional[AIOKafkaConsumer] = None
    retry_delay = 5
    kafka_was_offline = False

    while True:
        try:
            # Check if broker is reachable before letting aiokafka attempt connection
            is_alive = await check_kafka_connection(settings.KAFKA_BOOTSTRAP_SERVERS)
            if not is_alive:
                if not kafka_was_offline:
                    logger.info(
                        f"ℹ Kafka/Redpanda broker offline at {settings.KAFKA_BOOTSTRAP_SERVERS}. "
                        "Background report consumer waiting (run './start.sh infra up' to start Docker services)."
                    )
                    kafka_was_offline = True
                await asyncio.sleep(15)
                continue

            consumer = AIOKafkaConsumer(
                settings.KAFKA_REPORTS_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=settings.KAFKA_CONSUMER_GROUP,
                # "latest" meant a brand-new consumer group started at the tail
                # and permanently skipped everything already in the topic — so
                # on a cold start where the producer ran first, reports were
                # accepted with a 202 and silently never processed (BUG-039).
                # This only applies when the group has no committed offset, so
                # an existing deployment resumes exactly where it left off.
                auto_offset_reset="earliest",
                # Committed by hand after each message (process_message), so a
                # message is only passed once it succeeded or was dead-lettered.
                enable_auto_commit=False,
                value_deserializer=_decode,
            )
            await consumer.start()
            if kafka_was_offline:
                logger.info(f"✓ Kafka/Redpanda broker reconnected. Report consumer active at {settings.KAFKA_BOOTSTRAP_SERVERS}")
            else:
                logger.info(f"✓ Report consumer connected to {settings.KAFKA_BOOTSTRAP_SERVERS}")
            kafka_was_offline = False
            retry_delay = 5

            async for msg in consumer:
                await process_message(consumer, msg)

        except asyncio.CancelledError:
            logger.info("Report consumer shutting down...")
            break

        except Exception as e:
            if not kafka_was_offline:
                logger.info(
                    f"ℹ Kafka/Redpanda broker offline at {settings.KAFKA_BOOTSTRAP_SERVERS}. "
                    "Background report consumer waiting."
                )
                kafka_was_offline = True
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # exponential backoff

        finally:
            if consumer:
                try:
                    await consumer.stop()
                except Exception:
                    pass
