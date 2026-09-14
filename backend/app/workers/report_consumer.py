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

    while True:
        try:
            consumer = AIOKafkaConsumer(
                settings.KAFKA_REPORTS_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="indra-report-processor",
                auto_offset_reset="latest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await consumer.start()
            logger.info(f"✓ Report consumer connected to {settings.KAFKA_BOOTSTRAP_SERVERS}")

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
            logger.warning(f"Report consumer connection error: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # exponential backoff

        finally:
            if consumer:
                try:
                    await consumer.stop()
                except Exception:
                    pass
