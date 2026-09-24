"""
INDRA Platform — The data lake's raw ("bronze") layer (layer 7, Phase 2 T9)

A data lake keeps an untouched copy of everything it was given, from which every
table INDRA builds can be rebuilt: a parser fixed next month re-reads last
month's METAR files; Phase 6 compacts all of it into Parquet for DuckDB.

Everything lands in the `indra-lake` bucket under one layout, partitioned the way
Hive, Spark and DuckDB all read:

    raw/source=<source>/date=YYYY-MM-DD/hour=HH/<fetched_at>-<uuid>.<ext>.gz

    source=reports      every message on indra.raw.reports, as JSON Lines
                        (workers/lake_archiver.py, its own consumer group)
    source=metar        each tick's Indian METAR rows, CSV
    source=mastodon     each tag-timeline page, JSON, authors redacted to their
                        keyed hash (the one rule bronze bends: BUG-087)
    source=google_news  each query's RSS, XML
    source=sachet       each CAP document fetched, XML

Dates and hours are UTC, as in every lake: an IST partition would put 00:00–05:30
IST in the previous day's folder for anyone reading it from elsewhere.

**The lake is never on the critical path.** `put_raw` never raises. A failed
write is logged, and for the next BREAKER_SECONDS every write is skipped at
once rather than each waiting out the store's timeout, so a lake that is down
costs the pollers nothing. What a poller skipped is gone from the lake (the
rows are still in Postgres); the report stream is different, and is never
skipped: its archiver commits Kafka offsets only after the object is written.
"""

import gzip
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

from app.core.config import get_settings
from app.services import objectstore

logger = logging.getLogger("indra.services.lake")

# After a failed write, skip writes for this long.
BREAKER_SECONDS = 60.0

EXTENSIONS = {
    "text/csv": "csv",
    "application/json": "json",
    "application/x-ndjson": "jsonl",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/rss+xml": "xml",
}

_open_until: float = 0.0
_skipped_while_open = 0


def _reset_for_tests() -> None:
    global _open_until, _skipped_while_open
    _open_until = 0.0
    _skipped_while_open = 0


def object_key(source: str, fetched_at: datetime, extension: str) -> str:
    """raw/source=<source>/date=…/hour=…/<fetched_at>-<uuid>.<ext>.gz, in UTC."""
    ts = fetched_at.astimezone(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%S") + f"{ts.microsecond // 1000:03d}Z"
    return (
        f"raw/source={source}/date={ts:%Y-%m-%d}/hour={ts:%H}/"
        f"{stamp}-{uuid.uuid4().hex[:12]}.{extension}.gz"
    )


def _as_bytes(payload: Union[bytes, str, Dict[str, Any], list]) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def put_object(key: str, body: bytes, content_type: str, metadata: Dict[str, str]) -> None:
    """Write one gzipped object to the lake bucket. Raises ObjectStoreUnavailable."""
    await objectstore.put(
        get_settings().S3_LAKE_BUCKET,
        key,
        gzip.compress(body),
        content_type=content_type,
        content_encoding="gzip",
        metadata=metadata,
    )


async def put_raw(
    source: str,
    payload: Union[bytes, str, Dict[str, Any], list],
    content_type: str = "application/octet-stream",
    fetched_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Keep one raw payload, exactly as fetched. Returns its key, or None if it
    was not written (store unconfigured, down, or recently down). Never raises.
    """
    global _open_until, _skipped_while_open

    if not objectstore.configured():
        return None
    if _open_until > time.monotonic():
        _skipped_while_open += 1
        return None

    fetched_at = fetched_at or datetime.now(timezone.utc)
    key = object_key(source, fetched_at, EXTENSIONS.get(content_type, "bin"))
    meta = {"source": source, "fetched_at": fetched_at.astimezone(timezone.utc).isoformat()}
    # S3 metadata travels as HTTP headers, which must be ASCII: a Hindi news
    # query ("भारी बारिश") is percent-encoded rather than refused.
    meta.update({
        k: quote(str(v), safe=" ,:;/@=+-_.#") for k, v in (metadata or {}).items() if v is not None
    })
    try:
        await put_object(key, _as_bytes(payload), content_type, meta)
    except Exception as e:
        _open_until = time.monotonic() + BREAKER_SECONDS
        logger.warning(
            f"Lake write failed for source={source}; skipping lake writes for "
            f"{BREAKER_SECONDS:.0f}s (the data itself is stored): {type(e).__name__}: {e}"
        )
        return None

    if _skipped_while_open:
        logger.info(f"Lake writing again; {_skipped_while_open} raw payload(s) were skipped while it was down")
        _skipped_while_open = 0
    return key
