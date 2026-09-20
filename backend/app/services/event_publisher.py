"""
INDRA Platform — Verified Event Publisher

Publishes every event the pipeline creates or updates to `KAFKA_EVENTS_TOPIC`
(`indra.verified.events`), completing the outbound half of layer 2: reports come
in on `indra.raw.reports`, verified events go out here.

Design notes
------------
* **Same payload as the `VERIFIED_EVENT` WebSocket message.** A downstream
  consumer (alerting, analytics) sees exactly what the dashboard sees.
* **Keyed by event id.** Kafka keeps one key on one partition, so a created event
  and its later merges arrive in order. `merged` in the payload tells them apart.
* **Fail soft, bounded.** The event is already committed to Postgres; a broker
  failure is logged and reported as False, never raised, and the whole attempt
  is capped at `PUBLISH_TIMEOUT_S` so a hung broker cannot stall the consumer.
"""

import asyncio
import json
import logging

from app.core.config import get_settings

logger = logging.getLogger("indra.services.event_publisher")
settings = get_settings()

PUBLISH_TIMEOUT_S = 5.0


async def _send(event: dict) -> None:
    # Imported here, like api/reports.py, so tests can swap in a fake aiokafka.
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    try:
        await producer.start()
        await producer.send_and_wait(
            settings.KAFKA_EVENTS_TOPIC,
            json.dumps(event).encode("utf-8"),
            key=str(event.get("id", "")).encode("utf-8"),
        )
    finally:
        try:
            await producer.stop()
        except Exception:
            pass


async def publish_verified_event(event: dict) -> bool:
    """Publish one verified event. True if the broker acknowledged it. Never raises."""
    try:
        await asyncio.wait_for(_send(event), timeout=PUBLISH_TIMEOUT_S)
        logger.info(f"Published {event.get('event_code')} to {settings.KAFKA_EVENTS_TOPIC}")
        return True
    except asyncio.TimeoutError:
        logger.warning(
            f"Publishing {event.get('event_code')} to {settings.KAFKA_EVENTS_TOPIC} "
            f"timed out after {PUBLISH_TIMEOUT_S}s (non-fatal, event is stored)"
        )
    except Exception as e:
        logger.warning(
            f"Could not publish {event.get('event_code')} to {settings.KAFKA_EVENTS_TOPIC} "
            f"(non-fatal, event is stored): {e}"
        )
    return False
