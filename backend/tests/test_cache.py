"""
Day 6 T1 — the shared cache, on both of its backends.

The rest of the suite runs on the memory fallback (see `conftest._isolated_cache`),
so this file is the only place the Redis path is exercised. Tests that need a
live Redis carry `@pytest.mark.integration`; everything else runs offline.

What matters here is not that Redis works — it is that **Redis is never
load-bearing**. A stopped Redis must degrade the service and break nothing.
"""

import time

import pytest

from app.services import cache


# ── The memory fallback ────────────────────────────────────────────────────────

async def test_a_missing_key_is_none():
    assert await cache.get_json("wx:absent") is None


async def test_a_stored_value_reads_back_unchanged():
    await cache.set_json("wx:abc", [123.0, 5.5], ttl_seconds=600)

    assert await cache.get_json("wx:abc") == [123.0, 5.5]


async def test_a_stored_null_is_distinguishable_from_a_miss():
    """A remembered Open-Meteo failure is [expiry, None] — not an absent key."""
    await cache.set_json("wx:failed", [123.0, None], ttl_seconds=60)

    assert await cache.get_json("wx:failed") == [123.0, None]
    assert await cache.get_json("wx:never-set") is None


async def test_set_if_absent_is_true_once_then_false():
    assert await cache.set_if_absent("bcast:r1", ttl_seconds=86400) is True
    assert await cache.set_if_absent("bcast:r1", ttl_seconds=86400) is False
    assert await cache.set_if_absent("bcast:r2", ttl_seconds=86400) is True


async def test_the_value_cache_is_capped_and_evicts_the_oldest():
    for i in range(cache.MEMORY_VALUE_SIZE + 10):
        await cache.set_json(f"wx:{i}", [0.0, float(i)], ttl_seconds=600)

    assert len(cache._memory_values) == cache.MEMORY_VALUE_SIZE
    assert await cache.get_json("wx:0") is None          # evicted
    assert await cache.get_json("wx:4100") is not None    # still resident


async def test_clear_drops_both_fallbacks():
    await cache.set_json("wx:x", [0.0, 1.0], ttl_seconds=600)
    await cache.set_if_absent("bcast:x", ttl_seconds=600)

    cache.clear()

    assert await cache.get_json("wx:x") is None
    assert await cache.set_if_absent("bcast:x", ttl_seconds=600) is True


async def test_backend_reports_memory_when_forced():
    assert cache.backend() == "memory"


# ── Redis being down must cost nothing ─────────────────────────────────────────

@pytest.fixture
def broken_redis(monkeypatch):
    """A client whose every command raises, as a stopped container's would."""
    class Exploding:
        async def get(self, *a, **k):
            raise ConnectionError("Connection refused")

        async def set(self, *a, **k):
            raise ConnectionError("Connection refused")

        async def aclose(self):
            pass

    cache.use_memory_only(False)
    monkeypatch.setattr(cache, "_client", Exploding())
    monkeypatch.setattr(cache, "_unavailable_until", 0.0)
    monkeypatch.setattr(cache, "_announced_down", False)
    yield
    cache.use_memory_only(True)


async def test_a_failing_redis_falls_back_instead_of_raising(broken_redis):
    await cache.set_json("wx:down", [999.0, 7.0], ttl_seconds=600)

    assert await cache.get_json("wx:down") == [999.0, 7.0]


async def test_a_failing_redis_still_answers_set_if_absent(broken_redis):
    assert await cache.set_if_absent("bcast:down", ttl_seconds=600) is True
    assert await cache.set_if_absent("bcast:down", ttl_seconds=600) is False


async def test_a_failure_cools_down_instead_of_retrying_every_call(broken_redis):
    """
    One timeout per outage window, not one per call. A 100-report burst against
    a dead Redis must not wait out 100 connect timeouts.
    """
    await cache.get_json("wx:cooldown")

    assert cache._unavailable_until > time.monotonic()
    assert cache.backend() == "memory"


async def test_the_outage_is_logged_once_not_once_per_call(broken_redis, caplog):
    with caplog.at_level("WARNING", logger="indra.services.cache"):
        await cache.get_json("wx:a")
        cache._unavailable_until = 0.0   # let it try again immediately
        await cache.get_json("wx:b")

    warnings = [r for r in caplog.records if "Redis unavailable" in r.message]
    assert len(warnings) == 1


# ── The real thing ─────────────────────────────────────────────────────────────

@pytest.fixture
async def live_redis():
    """A real connection, or the test is skipped. Cleans up its own keys."""
    cache.use_memory_only(False)
    cache._client = None
    cache._unavailable_until = 0.0
    client = await cache._get_client()
    if client is None:
        cache.use_memory_only(True)
        pytest.skip("Redis is not reachable")
    try:
        await client.ping()
    except Exception:
        cache.use_memory_only(True)
        pytest.skip("Redis is not reachable")

    keys = ["wx:pytest-cell", "bcast:pytest-report"]
    for k in keys:
        await client.delete(k)
    yield client
    for k in keys:
        await client.delete(k)
    await cache.close()
    cache.use_memory_only(True)


@pytest.mark.integration
async def test_a_value_round_trips_through_real_redis(live_redis):
    await cache.set_json("wx:pytest-cell", [1.0, 12.5], ttl_seconds=600)

    assert cache.backend() == "redis"
    assert await cache.get_json("wx:pytest-cell") == [1.0, 12.5]


@pytest.mark.integration
async def test_the_reading_ttl_is_the_one_the_caller_asked_for(live_redis):
    await cache.set_json("wx:pytest-cell", [1.0, 12.5], ttl_seconds=600)

    ttl = await live_redis.ttl("wx:pytest-cell")
    assert 595 <= ttl <= 600


@pytest.mark.integration
async def test_a_cached_failure_expires_in_a_minute_not_ten(live_redis):
    await cache.set_json("wx:pytest-cell", [1.0, None], ttl_seconds=60)

    ttl = await live_redis.ttl("wx:pytest-cell")
    assert 55 <= ttl <= 60


@pytest.mark.integration
async def test_set_if_absent_survives_a_restart(live_redis):
    """
    The one thing the in-process OrderedDict could not do. Dropping the client
    and reconnecting stands in for a backend restart: the id must still be known.
    """
    assert await cache.set_if_absent("bcast:pytest-report", ttl_seconds=3600) is True

    await cache.close()          # the "restart"
    cache._unavailable_until = 0.0

    assert await cache.set_if_absent("bcast:pytest-report", ttl_seconds=3600) is False


@pytest.mark.integration
async def test_the_dedup_key_lives_for_a_day(live_redis):
    await cache.set_if_absent("bcast:pytest-report", ttl_seconds=86400)

    ttl = await live_redis.ttl("bcast:pytest-report")
    assert 86300 <= ttl <= 86400
