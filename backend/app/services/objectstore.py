"""
INDRA Platform — Object storage (layer 7, Phase 2 T1)

A thin S3 client over whatever S3-compatible store S3_ENDPOINT_URL names:
SeaweedFS in docker-compose.yml, but MinIO, Garage or real S3 equally, since
nothing here uses anything beyond the plain S3 API.

    put(bucket, key, body)   exists(bucket, key)
    get(bucket, key)         presign(bucket, key)
    ensure_buckets()         ping()

Two buckets:

    indra-lake    the data lake. Phase 2 T9 writes its raw "bronze" layer here:
                  every payload a feed fetched and every message on the report
                  stream, untouched, so anything downstream can be rebuilt.
    indra-media   report photos and videos, from Phase 5.

**The store is never critical.** A report is stored in Postgres and published
through the outbox whether or not the lake is up; `/healthz` reports the store
as a non-critical check, so its loss is `degraded`, never `unhealthy`. Nothing
on a request path awaits this module.

**boto3 is synchronous**, so every call runs in a worker thread
(`asyncio.to_thread`). Called directly from a coroutine it would block the
event loop for the whole request, the same class of bug as BUG-006.

**Path-style addressing** (`http://host:8333/bucket/key`), not virtual-hosted
(`http://bucket.host:8333/key`): a local store has no wildcard DNS, so the
bucket cannot be a hostname.

Unconfigured means empty keys, or the `.env.example` placeholders left in
place. Then `configured()` is False, nothing connects, and every call raises
`ObjectStoreUnavailable` at once rather than waiting out a timeout.
"""

import asyncio
import logging
import threading
from typing import Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.services.objectstore")

_client = None
_client_lock = threading.Lock()
# Buckets confirmed to exist in this process, so the check costs one round trip
# per bucket per process rather than one per write.
_ready_buckets: set = set()

PLACEHOLDER_MARK = "change-me"


class ObjectStoreUnavailable(Exception):
    """The store is not configured, or did not answer. Nothing was written."""


def configured() -> bool:
    """True when real keys are set. Placeholders count as unset."""
    s = get_settings()
    keys = (s.S3_ACCESS_KEY or "", s.S3_SECRET_KEY or "")
    return all(keys) and not any(PLACEHOLDER_MARK in k for k in keys)


def buckets() -> List[str]:
    s = get_settings()
    return [s.S3_LAKE_BUCKET, s.S3_MEDIA_BUCKET]


def _make_client():
    import boto3
    from botocore.config import Config

    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.S3_ENDPOINT_URL,
        aws_access_key_id=s.S3_ACCESS_KEY,
        aws_secret_access_key=s.S3_SECRET_KEY,
        region_name=s.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=s.S3_TIMEOUT_SECONDS,
            read_timeout=s.S3_TIMEOUT_SECONDS,
            # One retry, not boto's default of four: a store that is down should
            # cost a caller seconds, not the better part of a minute.
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _get_client():
    """The process's one client, built on first use. Creation is not thread-safe in boto3."""
    global _client
    if not configured():
        raise ObjectStoreUnavailable(
            "object store not configured: set S3_ACCESS_KEY and S3_SECRET_KEY"
        )
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _make_client()
    return _client


def reset_for_tests(client=None) -> None:
    """Forget the cached client and bucket checks; optionally inject a fake client."""
    global _client
    _client = client
    _ready_buckets.clear()


def _is_missing(error: Exception) -> bool:
    """True for a botocore ClientError that means "no such key or bucket"."""
    response = getattr(error, "response", None) or {}
    code = str((response.get("Error") or {}).get("Code", ""))
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"} or status == 404


async def _call(fn, *args, **kwargs):
    """Run one blocking boto3 call in a worker thread; any failure becomes ObjectStoreUnavailable."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ObjectStoreUnavailable:
        raise
    except Exception as e:
        if _is_missing(e):
            raise
        raise ObjectStoreUnavailable(f"{type(e).__name__}: {e}") from e


# ── Buckets ────────────────────────────────────────────────────────────────────

def _ensure_bucket_sync(name: str) -> bool:
    """Create one bucket if it is missing. True if it was created now."""
    client = _get_client()
    try:
        client.head_bucket(Bucket=name)
        return False
    except Exception as e:
        if not _is_missing(e):
            raise
    try:
        client.create_bucket(Bucket=name)
    except Exception as e:
        # Another process created it between the two calls: the outcome wanted.
        code = str(((getattr(e, "response", None) or {}).get("Error") or {}).get("Code", ""))
        if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            return False
        raise
    return True


async def ensure_buckets() -> List[str]:
    """
    Create `indra-lake` and `indra-media` if they are missing. Returns the ones
    created now: a second call creates nothing and raises nothing.

    Called at startup (non-fatal) and lazily before a first write, so a store
    that came up after the backend still gets its buckets.
    """
    created: List[str] = []
    for name in buckets():
        if name in _ready_buckets:
            continue
        if await _call(_ensure_bucket_sync, name):
            created.append(name)
            logger.info(f"Object store: created bucket {name}")
        _ready_buckets.add(name)
    return created


async def _ensure_bucket(name: str) -> None:
    if name not in _ready_buckets:
        await _call(_ensure_bucket_sync, name)
        _ready_buckets.add(name)


# ── Objects ────────────────────────────────────────────────────────────────────

async def put(
    bucket: str,
    key: str,
    body: bytes,
    content_type: str = "application/octet-stream",
    content_encoding: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    """Write one object. Raises ObjectStoreUnavailable if it could not be written."""
    await _ensure_bucket(bucket)
    kwargs = {"Bucket": bucket, "Key": key, "Body": body, "ContentType": content_type}
    if content_encoding:
        kwargs["ContentEncoding"] = content_encoding
    if metadata:
        kwargs["Metadata"] = {k: str(v) for k, v in metadata.items()}
    await _call(lambda: _get_client().put_object(**kwargs))


async def get(bucket: str, key: str) -> Optional[bytes]:
    """The object's bytes, or None if there is no such object."""

    def _read():
        return _get_client().get_object(Bucket=bucket, Key=key)["Body"].read()

    try:
        return await _call(_read)
    except ObjectStoreUnavailable:
        raise
    except Exception as e:
        if _is_missing(e):
            return None
        raise


async def exists(bucket: str, key: str) -> bool:
    try:
        await _call(lambda: _get_client().head_object(Bucket=bucket, Key=key))
        return True
    except ObjectStoreUnavailable:
        raise
    except Exception as e:
        if _is_missing(e):
            return False
        raise


async def presign(bucket: str, key: str, expires_s: int = 3600) -> str:
    """
    A time-limited GET URL for one object.

    Signed against S3_ENDPOINT_URL, which is 127.0.0.1 on the server: such a
    URL is usable by the backend and by someone on the machine, not by a
    browser elsewhere. Phase 5 serves media through the API for that reason.
    """
    return await _call(
        lambda: _get_client().generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=int(expires_s)
        )
    )


async def list_keys(bucket: str, prefix: str = "", limit: int = 1000) -> List[str]:
    """Keys under a prefix, at most `limit`, in the store's (lexical) order."""

    def _list():
        client = _get_client()
        keys: List[str] = []
        token = None
        while len(keys) < limit:
            kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": min(1000, limit - len(keys))}
            if token:
                kwargs["ContinuationToken"] = token
            page = client.list_objects_v2(**kwargs)
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
        return keys

    return await _call(_list)


async def ping() -> bool:
    """The store answers, with these credentials, for the lake bucket. For /healthz."""
    await _call(lambda: _get_client().head_bucket(Bucket=get_settings().S3_LAKE_BUCKET))
    return True
