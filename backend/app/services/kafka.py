"""
INDRA Platform — The process's Kafka producer

One long-lived AIOKafkaProducer for the whole process. Until Phase 1 every
report built its own producer, connected, sent one message and tore it down
again: a TCP connection and a metadata round trip per citizen, and the likely
leak `scripts/burst_reports.py` was written to look for.

**Nothing on a request path connects to Kafka.** `ready` says whether the
producer is up. A request publishes only if it is, and only for as long as its
own short cap allows. Connecting — at startup, and again after an outage — is
the outbox relay's job (`ensure_started`, `reset`). A citizen submitting while
Redpanda is down therefore gets an answer in milliseconds instead of waiting
out aiokafka's 40-second request timeout, and the report waits in the outbox.
"""

import asyncio
import logging
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.services.kafka")

# How long connecting may take before it counts as a failure.
START_TIMEOUT_SECONDS = 5.0


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str):
        self._servers = bootstrap_servers
        self._producer = None
        self._healthy = False
        self._lock = asyncio.Lock()
        self._announced_down = False

    @property
    def ready(self) -> bool:
        """
        True while a started producer is held and its last publish did not fail.
        A request publishes only when this is true, so after one request has
        waited out a dead broker the next ones do not.
        """
        return self._producer is not None and self._healthy

    def mark_unhealthy(self) -> None:
        """
        A publish failed. Stop offering the producer to requests; the relay's
        next ensure_started() rebuilds it. Cheap and synchronous, so a request
        can call it without waiting on anything.
        """
        self._healthy = False

    async def ensure_started(self) -> bool:
        """Start the producer if it is not running, or rebuild it if a publish failed. Never raises."""
        if self.ready:
            return True
        if self._producer is not None:
            await self.reset()
        async with self._lock:
            if self._producer is not None:
                return True

            # A plain TCP probe first. aiokafka logs every refused connection at
            # ERROR, so starting it against a stopped broker every few seconds
            # would bury the log in noise; the report consumer does the same.
            from app.workers.report_consumer import check_kafka_connection

            if not await check_kafka_connection(self._servers):
                self._mark_down("broker not reachable")
                return False

            producer = None
            try:
                # Imported here rather than at module level so that tests can
                # substitute sys.modules["aiokafka"].
                from aiokafka import AIOKafkaProducer

                producer = AIOKafkaProducer(bootstrap_servers=self._servers)
                await asyncio.wait_for(producer.start(), timeout=START_TIMEOUT_SECONDS)
            except Exception as e:
                self._mark_down(f"{type(e).__name__}: {e}")
                if producer is not None:
                    await self._stop_quietly(producer)
                return False

            self._producer = producer
            self._healthy = True
            if self._announced_down:
                logger.info(f"✓ Kafka producer connected again to {self._servers}")
                self._announced_down = False
            else:
                logger.info(f"✓ Kafka producer connected to {self._servers}")
            return True

    async def publish(self, topic: str, value: bytes, key: Optional[bytes], timeout: float) -> None:
        """Send one message and wait for the broker to acknowledge it. Raises on failure or timeout."""
        producer = self._producer
        if producer is None:
            raise RuntimeError("Kafka producer is not started")
        await asyncio.wait_for(producer.send_and_wait(topic, value, key=key), timeout=timeout)

    async def reset(self) -> None:
        """Drop the producer, so the next ensure_started() builds a fresh one."""
        async with self._lock:
            producer, self._producer = self._producer, None
            self._healthy = False
        if producer is not None:
            await self._stop_quietly(producer)

    async def stop(self) -> None:
        """Shutdown. The same as reset(); named for the lifespan that calls it."""
        await self.reset()

    def _mark_down(self, reason: str) -> None:
        if not self._announced_down:
            logger.warning(
                f"Kafka producer unavailable at {self._servers} ({reason}). Reports are kept "
                "in the outbox and published when the broker is back."
            )
            self._announced_down = True

    @staticmethod
    async def _stop_quietly(producer) -> None:
        # stop() flushes, and a flush waits on the broker; bound it.
        try:
            await asyncio.wait_for(producer.stop(), timeout=START_TIMEOUT_SECONDS)
        except Exception as e:
            logger.debug(f"Kafka producer stop failed (ignored): {type(e).__name__}: {e}")


_publisher: Optional[KafkaPublisher] = None


def get_publisher() -> KafkaPublisher:
    """The process's publisher, created on first use and not started until asked."""
    global _publisher
    if _publisher is None:
        _publisher = KafkaPublisher(get_settings().KAFKA_BOOTSTRAP_SERVERS)
    return _publisher


def set_publisher(publisher: Optional[KafkaPublisher]) -> None:
    """Replace the process's publisher. The test suite injects fakes this way; None forgets it."""
    global _publisher
    _publisher = publisher
