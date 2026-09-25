"""
INDRA Platform — Outbox relay

Publishes every outbox row the request could not: reports stored while Kafka
was down, and any whose immediate publish failed or timed out. It runs in the
API process, beside the report consumer and the pollers (main.py).

    every RELAY_INTERVAL_SECONDS:
        SELECT … FROM outbox WHERE published_at IS NULL
        ORDER BY id LIMIT BATCH_SIZE FOR UPDATE SKIP LOCKED
        publish them oldest first, then mark the ones that went

* **SKIP LOCKED** lets two relays — two processes, later — run at once without
  publishing a row twice: each takes the rows the other has not locked. It is
  also the lock a request takes for its own immediate publish.
* **A batch stops at its first failure.** The broker is almost certainly down,
  and trying the other rows would only fail them too. That row's `attempts`
  and `last_error` say why it is waiting, the producer is dropped so the next
  attempt builds a fresh one, and the relay backs off, doubling up to
  MAX_BACKOFF_SECONDS while the broker answers but will not take messages.
* **While the broker does not answer at all** the relay keeps probing every
  RELAY_INTERVAL_SECONDS. A refused TCP connection costs next to nothing, and
  it means the backlog starts draining within seconds of Redpanda coming back.
* **A full batch** means more rows are waiting, so the relay goes round again
  without sleeping.
* **Rows are never deleted** except published ones older than RETENTION_DAYS,
  once a day.

Delivery is at least once. A crash between the broker's acknowledgement and
the commit that marks the row sends it again on the next pass, byte for byte.
The consumer is built for that: a report it has already linked or suppressed
is skipped, and NEW_REPORT is broadcast once per report id
(workers/report_consumer.py).
"""

import asyncio
import json
import logging
import time
from typing import Tuple

from sqlalchemy import text

from app.services import kafka
from app.services.ingest import encode_message

logger = logging.getLogger("indra.workers.outbox_relay")

RELAY_INTERVAL_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
BATCH_SIZE = 200
PUBLISH_TIMEOUT_SECONDS = 5.0
RETENTION_DAYS = 7
CLEANUP_EVERY_SECONDS = 24 * 60 * 60


async def relay_once(db, publisher) -> Tuple[int, int]:
    """
    One pass over the waiting rows. Returns (published, failed); failed is 0
    or 1, because a batch stops at its first failure.
    """
    rows = (
        await db.execute(
            text("""
                SELECT id, topic, key, payload
                FROM outbox
                WHERE published_at IS NULL
                ORDER BY id
                LIMIT :n
                FOR UPDATE SKIP LOCKED
            """),
            {"n": BATCH_SIZE},
        )
    ).fetchall()
    if not rows:
        await db.rollback()
        return 0, 0

    published = []
    failed = 0
    for row_id, topic, key, payload in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        try:
            await publisher.publish(
                topic,
                encode_message(payload),
                key.encode("utf-8") if key else None,
                timeout=PUBLISH_TIMEOUT_SECONDS,
            )
        except Exception as e:
            failed = 1
            await db.execute(
                text("""
                    UPDATE outbox SET attempts = attempts + 1, last_error = :err
                    WHERE id = :id
                """),
                {"id": row_id, "err": f"{type(e).__name__}: {e}"[:500]},
            )
            break
        published.append(row_id)

    if published:
        await db.execute(
            text("UPDATE outbox SET published_at = NOW() WHERE id = ANY(CAST(:ids AS bigint[]))"),
            {"ids": published},
        )
    await db.commit()
    return len(published), failed


async def cleanup_published(db) -> int:
    """Delete published rows older than RETENTION_DAYS. Unpublished rows are never touched."""
    result = await db.execute(
        text("DELETE FROM outbox WHERE published_at < NOW() - make_interval(days => :days)"),
        {"days": RETENTION_DAYS},
    )
    await db.commit()
    return result.rowcount or 0


async def start_outbox_relay() -> None:
    """The relay loop. Never returns except by cancellation; no single failure stops it."""
    from app.core.database import async_session

    publisher = kafka.get_publisher()
    backoff = RELAY_INTERVAL_SECONDS
    last_cleanup = float("-inf")
    logger.info(f"✓ Outbox relay started — every {RELAY_INTERVAL_SECONDS:.0f}s, {BATCH_SIZE} rows a pass")

    while True:
        delay = RELAY_INTERVAL_SECONDS
        try:
            if await publisher.ensure_started():
                async with async_session() as db:
                    published, failed = await relay_once(db, publisher)
                if published:
                    logger.info(f"Outbox relay published {published} waiting report(s)")
                if failed:
                    await publisher.reset()
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    delay = backoff
                else:
                    backoff = RELAY_INTERVAL_SECONDS
                    if published == BATCH_SIZE:
                        delay = 0

            if time.monotonic() - last_cleanup >= CLEANUP_EVERY_SECONDS:
                async with async_session() as db:
                    deleted = await cleanup_published(db)
                last_cleanup = time.monotonic()
                if deleted:
                    logger.info(f"Outbox relay pruned {deleted} published row(s) older than {RETENTION_DAYS} days")
        except asyncio.CancelledError:
            logger.info("Outbox relay shutting down...")
            raise
        except Exception as e:
            # The task must outlive any single failure, including a database
            # that is not up yet on a cold start.
            logger.warning(f"Outbox relay pass failed (non-fatal): {type(e).__name__}: {e}")
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            delay = backoff

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("Outbox relay shutting down...")
            raise
