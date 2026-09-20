"""
INDRA Platform — Shared cache (Redis, with an in-memory fallback)

Redis has been declared in `docker-compose.yml` and checked by `/healthz` since
Day 1 while no code connected to it. This module is the connection, and it has
exactly two customers:

* `services/weather.py` — the Open-Meteo reading per H3 res-8 cell, so a burst of
  reports from one cell makes one HTTP call rather than fifty.
* `workers/report_consumer.py` — the set of report ids already broadcast as
  `NEW_REPORT`, so a Kafka re-delivery does not show the same report twice.

**Redis is never load-bearing.** Every call falls back to process memory on any
error, so a stopped Redis degrades the service (`/healthz` says `degraded`) and
breaks nothing. What is lost in the fallback is only what memory cannot do:
surviving a restart, and sharing state between processes.

After a failure the client is not retried for RETRY_COOLDOWN_SECONDS. Without
that, every call during an outage would wait out its own connect timeout, and a
100-report burst would stall behind them.

Expiry is expressed twice on purpose: Redis is given a real TTL (so
`redis-cli TTL wx:<cell>` is meaningful and memory is reclaimed), and the caller
may also record its own expiry inside the value. `weather.py` does the latter,
which is what keeps its cache behaviour identical on both backends and testable
through a single injected clock.
"""

import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.services.cache")
settings = get_settings()

# How long to stop trying after a Redis error, so an outage costs one timeout
# rather than one timeout per call.
RETRY_COOLDOWN_SECONDS = 30.0

# The connect/command timeout. Deliberately short: this is a cache, and waiting
# on it is always worse than missing it.
SOCKET_TIMEOUT_SECONDS = 0.5

# Bound on the in-memory fallbacks. Both are per process and lost on restart.
MEMORY_VALUE_SIZE = 4096
MEMORY_SEEN_SIZE = 2000

_client = None                      # redis.asyncio.Redis | None
_unavailable_until: float = 0.0     # monotonic deadline; 0 = may try
_announced_down = False             # so an outage logs once, not once per call

# Fallbacks. `_memory_values` mirrors set_json/get_json; `_memory_seen` mirrors
# set_if_absent, oldest evicted first.
_memory_values: "OrderedDict[str, Any]" = OrderedDict()
_memory_seen: "OrderedDict[str, None]" = OrderedDict()

# Tests pin this to True so the suite is deterministic and runs with no Redis:
# a shared Redis would otherwise carry ids between test runs for 24 hours.
_memory_only = False


def use_memory_only(flag: bool = True) -> None:
    """Force the fallback path. Used by the test suite and by nothing else."""
    global _memory_only
    _memory_only = flag


def clear() -> None:
    """Drop the in-memory fallbacks. Does not touch Redis."""
    _memory_values.clear()
    _memory_seen.clear()


def backend() -> str:
    """`redis` or `memory` — what the last call actually used. For logs."""
    if _memory_only or _client is None or _unavailable_until > time.monotonic():
        return "memory"
    return "redis"


async def _get_client():
    """The Redis client, or None if it is unavailable or cooling down."""
    global _client, _unavailable_until

    if _memory_only:
        return None
    if _unavailable_until > time.monotonic():
        return None
    if _client is not None:
        return _client

    try:
        import redis.asyncio as redis

        _client = redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
            decode_responses=True,
        )
        return _client
    except Exception as e:
        _mark_down(f"client construction failed: {type(e).__name__}: {e}")
        return None


def _mark_down(reason: str) -> None:
    global _unavailable_until, _announced_down
    _unavailable_until = time.monotonic() + RETRY_COOLDOWN_SECONDS
    if not _announced_down:
        logger.warning(
            f"Redis unavailable, falling back to process memory ({reason}). "
            f"Retrying in {RETRY_COOLDOWN_SECONDS:.0f}s."
        )
        _announced_down = True


def _mark_up() -> None:
    global _announced_down
    if _announced_down:
        logger.info("Redis is answering again — cache is shared once more")
        _announced_down = False


async def get_json(key: str) -> Optional[Any]:
    """The stored value, or None if the key is absent. Never raises."""
    client = await _get_client()
    if client is not None:
        try:
            raw = await client.get(key)
            _mark_up()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            _mark_down(f"GET {key}: {type(e).__name__}: {e}")
    return _memory_values.get(key)


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    """Store a JSON-serialisable value under a TTL. Never raises."""
    client = await _get_client()
    if client is not None:
        try:
            await client.set(key, json.dumps(value), ex=max(1, int(ttl_seconds)))
            _mark_up()
            return
        except Exception as e:
            _mark_down(f"SET {key}: {type(e).__name__}: {e}")

    _memory_values[key] = value
    _memory_values.move_to_end(key)
    while len(_memory_values) > MEMORY_VALUE_SIZE:
        _memory_values.popitem(last=False)


async def set_if_absent(key: str, ttl_seconds: int) -> bool:
    """
    True the first time this key is seen, False afterwards — `SET NX EX`.

    On the memory path the answer is only as good as this process's memory: a
    restart forgets, which is precisely the limitation Redis removes here.
    """
    client = await _get_client()
    if client is not None:
        try:
            was_set = await client.set(key, "1", ex=max(1, int(ttl_seconds)), nx=True)
            _mark_up()
            return bool(was_set)
        except Exception as e:
            _mark_down(f"SET NX {key}: {type(e).__name__}: {e}")

    if key in _memory_seen:
        _memory_seen.move_to_end(key)
        return False
    _memory_seen[key] = None
    while len(_memory_seen) > MEMORY_SEEN_SIZE:
        _memory_seen.popitem(last=False)
    return True


async def close() -> None:
    """Release the connection at shutdown. Never raises."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as e:
            logger.warning(f"Redis close failed (ignored): {type(e).__name__}: {e}")
        finally:
            _client = None
