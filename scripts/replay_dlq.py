#!/usr/bin/env python3
"""
Send the messages the pipeline gave up on back into the report stream.

The report consumer retries a message the pipeline fails on, and after
PIPELINE_MAX_ATTEMPTS failures publishes it to the dead-letter topic
(`indra.raw.reports.dlq`) with the error and moves on (Phase 2 T8). Once the
cause is fixed — a migration that had not run, a bug since deployed — this
script republishes each one's original message to `indra.raw.reports`, where
the pipeline processes it like any other. Processing is idempotent, so a
report that did get through in the meantime is simply skipped.

    python scripts/replay_dlq.py --list        # show what is waiting; change nothing
    python scripts/replay_dlq.py               # replay everything waiting
    python scripts/replay_dlq.py --limit 10    # replay the first ten

It reads the dead-letter topic as its own consumer group,
`indra-dlq-replay`, and commits each message only after republishing it, so a
replay that stops half-way resumes where it stopped and never sends one twice
on purpose. `--list` reads without committing.

Run it from the repo root with the backend's virtualenv, against the same
Kafka as the platform (KAFKA_BOOTSTRAP_SERVERS in .env).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

GROUP_ID = "indra-dlq-replay"
# How long to wait for another message before deciding the topic is drained.
IDLE_TIMEOUT_MS = 5000


async def run(list_only: bool, limit: int) -> int:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

    from app.core.config import get_settings

    settings = get_settings()
    consumer = AIOKafkaConsumer(
        settings.KAFKA_DLQ_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=None if list_only else GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = None if list_only else AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )

    await consumer.start()
    if producer:
        await producer.start()
    done = 0
    try:
        while limit <= 0 or done < limit:
            batch = await consumer.getmany(timeout_ms=IDLE_TIMEOUT_MS, max_records=1)
            if not batch:
                break
            for tp, messages in batch.items():
                for msg in messages:
                    try:
                        record = json.loads(msg.value.decode("utf-8"))
                    except Exception as e:
                        print(f"  offset {msg.offset}: unreadable dead-letter record ({e}); skipped")
                        record = None

                    source = (record or {}).get("source") or {}
                    report_id = ((record or {}).get("payload") or {}).get("id")
                    print(
                        f"  {tp.topic}[{tp.partition}]@{msg.offset}  report {report_id}  "
                        f"from {source.get('topic')}[{source.get('partition')}]@{source.get('offset')}  "
                        f"after {(record or {}).get('attempts')} attempt(s): {(record or {}).get('error')}"
                    )

                    if not list_only and record and isinstance(record.get("payload"), dict):
                        await producer.send_and_wait(
                            settings.KAFKA_REPORTS_TOPIC,
                            json.dumps(record["payload"]).encode("utf-8"),
                            key=msg.key,
                        )
                    if not list_only:
                        await consumer.commit({TopicPartition(tp.topic, tp.partition): msg.offset + 1})
                    done += 1
    finally:
        await consumer.stop()
        if producer:
            await producer.stop()

    verb = "waiting" if list_only else "replayed"
    print(f"{done} message(s) {verb}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="show what is waiting; change nothing")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    args = parser.parse_args()
    return asyncio.run(run(args.list, args.limit))


if __name__ == "__main__":
    sys.exit(main())
