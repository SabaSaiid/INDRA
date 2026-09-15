"""
INDRA Platform — Report Consumer Worker
Background aiokafka consumer that reads from indra.raw.reports,
runs dedup, and broadcasts NEW_REPORT WebSocket messages.
"""

import json
import logging
import asyncio
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.workers.report_consumer")
settings = get_settings()

# Reference to the WebSocket manager — set by main.py at startup
_ws_manager = None


def set_ws_manager(manager):
    global _ws_manager
    _ws_manager = manager


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
                try:
                    report_data = msg.value
                    logger.info(f"Received report: {report_data.get('id', 'unknown')}")

                    # Broadcast to WebSocket clients
                    if _ws_manager:
                        await _ws_manager.broadcast({
                            "type": "NEW_REPORT",
                            "report": report_data,
                        })

                except Exception as e:
                    logger.error(f"Error processing report message: {e}")

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
