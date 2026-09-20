"""
INDRA Platform — Report Consumer Worker
Background aiokafka consumer that reads from indra.raw.reports, runs the
verification pipeline, broadcasts NEW_REPORT / VERIFIED_EVENT WebSocket messages,
and publishes verified events to indra.verified.events.
"""

import json
import logging
import asyncio
from collections import OrderedDict
from typing import Any, Dict, Optional

from app.core.config import get_settings

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
# recently broadcast reports are remembered, oldest evicted first.
#
# Per process only: a restarted backend has an empty memory and will broadcast a
# re-delivered report once more. The demo runs one backend process.
BROADCAST_MEMORY_SIZE = 2000
_recently_broadcast: "OrderedDict[str, None]" = OrderedDict()


def _first_broadcast(report_id: Optional[str]) -> bool:
    """True the first time an id is seen (within memory). No id → always True."""
    if not report_id:
        return True
    if report_id in _recently_broadcast:
        _recently_broadcast.move_to_end(report_id)
        return False
    _recently_broadcast[report_id] = None
    if len(_recently_broadcast) > BROADCAST_MEMORY_SIZE:
        _recently_broadcast.popitem(last=False)
    return True


async def handle_report_message(report_data: Dict[str, Any]) -> None:
    """
    One consumed message: broadcast NEW_REPORT (once per report id), run the
    verification pipeline (every time), broadcast VERIFIED_EVENT if it produced
    or updated an event. Never raises — the consumer loop must survive.
    """
    try:
        report_id = report_data.get("id")
        logger.info(f"Received report: {report_id or 'unknown'}")

        # NEW_REPORT keeps the existing frontend contract. VERIFIED_EVENT is
        # additive on top of it.
        if _ws_manager and _first_broadcast(str(report_id) if report_id else None):
            await _ws_manager.broadcast({
                "type": "NEW_REPORT",
                "report": report_data,
            })

        # Run the verification pipeline. The worker lives outside FastAPI's
        # dependency injection, so it takes a session from the sessionmaker
        # directly rather than via Depends(get_db).
        event = None
        try:
            from app.core.database import async_session
            from app.services.pipeline import process_report

            async with async_session() as db:
                event = await process_report(db, report_data)
        except Exception as e:
            # process_report already fails soft; this guards the session/import
            # layer around it.
            logger.error(f"Pipeline invocation failed: {e}")

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
                group_id="indra-report-processor",
                auto_offset_reset="latest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await consumer.start()
            if kafka_was_offline:
                logger.info(f"✓ Kafka/Redpanda broker reconnected. Report consumer active at {settings.KAFKA_BOOTSTRAP_SERVERS}")
            else:
                logger.info(f"✓ Report consumer connected to {settings.KAFKA_BOOTSTRAP_SERVERS}")
            kafka_was_offline = False
            retry_delay = 5

            async for msg in consumer:
                await handle_report_message(msg.value)

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
