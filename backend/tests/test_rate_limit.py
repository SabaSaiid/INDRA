"""
Phase 5 T8 — anti-flooding rate limits (`app/services/rate_limit.py`,
`cache.sliding_window`, `core/client_ip.py`).

T8's table row for row, with B10's change: the per-IP limit is 300 in
production (CGNAT), so the plan's "31st from one IP" row is run with the limit
set to 30, as the phase file says. The suite runs on the cache's per-process
memory window, which is exactly T8's "Redis stopped" row; the Redis window is
checked against a real Redis at the end.
"""

import httpx
import pytest
from starlette.requests import Request

from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.services import cache, rate_limit
from tests.phase5_support import (  # noqa: F401  (fixtures)
    FLOOD_TEXT, PATNA, api, db, device, filed, salted, submit, tokens,
)


def _request(peer: str, **headers) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/", "client": (peer, 5000),
        "headers": [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()],
    })


# ── The client's address ───────────────────────────────────────────────────────

def test_forwarded_headers_count_only_from_the_machine_itself():
    assert client_ip(_request("127.0.0.1", x_forwarded_for="49.36.1.2")) == "49.36.1.2"
    assert client_ip(_request("::1", x_forwarded_for="49.36.1.2")) == "49.36.1.2"
    # Sent straight to port 8000 from outside: ignored, the real peer is used.
    assert client_ip(_request("203.0.113.9", x_forwarded_for="49.36.1.2")) == "203.0.113.9"
    assert client_ip(_request("203.0.113.9", cf_connecting_ip="49.36.1.2")) == "203.0.113.9"


def test_the_proxys_own_entry_wins_over_the_clients_claims():
    """Caddy appends what it saw; anything before it is whatever the client wrote."""
    assert client_ip(_request("127.0.0.1", x_forwarded_for="1.1.1.1, 49.36.1.2")) == "49.36.1.2"
    assert client_ip(_request("127.0.0.1", cf_connecting_ip="49.36.9.9",
                              x_forwarded_for="49.36.1.2")) == "49.36.9.9"
    assert client_ip(_request("127.0.0.1")) == "127.0.0.1"


# ── The window ─────────────────────────────────────────────────────────────────

async def test_a_sliding_window_admits_the_limit_then_says_when_to_retry():
    assert await cache.sliding_window("t", 2, 10, now=0.0) == (True, 0)
    assert await cache.sliding_window("t", 2, 10, now=1.0) == (True, 0)
    assert await cache.sliding_window("t", 2, 10, now=2.0) == (False, 8)
    assert await cache.sliding_window("t", 2, 10, now=9.5) == (False, 1)
    # The oldest has left the window: one more fits.
    assert await cache.sliding_window("t", 2, 10, now=10.5) == (True, 0)


async def test_a_refused_request_does_not_push_the_window_out():
    for t in (0.0, 1.0):
        await cache.sliding_window("r", 2, 10, now=t)
    for t in (2.0, 3.0, 4.0, 5.0):  # a script hammering away
        assert (await cache.sliding_window("r", 2, 10, now=t))[0] is False
    assert (await cache.sliding_window("r", 2, 10, now=11.5))[0] is True


async def test_a_limit_of_0_refuses_everything_for_a_window():
    """An operator shutting submissions off: a 429 with a full window, never a 500."""
    assert await cache.sliding_window("zero", 0, 600, now=0.0) == (False, 600)
    assert await cache.sliding_window("zero", 0, 600, now=5.0) == (False, 600)


async def test_windows_are_per_key():
    assert (await cache.sliding_window("a", 1, 10, now=0.0))[0] is True
    assert (await cache.sliding_window("b", 1, 10, now=0.0))[0] is True
    assert (await cache.sliding_window("a", 1, 10, now=1.0))[0] is False


# ── T8's table, through the API ────────────────────────────────────────────────

@pytest.mark.integration
async def test_ten_reports_from_one_device_then_the_eleventh_is_429(api, db, salted):
    for _ in range(10):
        assert (await submit(api, 1)).status_code == 202
    r = await submit(api, 1)
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 600
    assert "from this device" in r.json()["detail"]
    # Nothing of the 11th was stored; another device is unaffected.
    assert (await submit(api, 2)).status_code == 202


@pytest.mark.integration
async def test_the_31st_report_from_one_address_is_429(api, db, salted, monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_IP", 30)
    for n in range(30):
        assert (await submit(api, n)).status_code == 202, n
    r = await submit(api, 99)
    assert r.status_code == 429 and "from this network" in r.json()["detail"]


@pytest.mark.integration
async def test_an_official_report_is_exempt(api, db, tokens, monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_IP", 1)
    body = {"latitude": PATNA[0], "longitude": PATNA[1], "text": FLOOD_TEXT}
    for _ in range(3):
        r = await api.post("/api/reports/official", json=body, headers=tokens["commander"])
        assert r.status_code == 202, r.text


@pytest.mark.integration
async def test_a_forwarded_header_from_outside_cannot_choose_its_own_bucket(db, salted, monkeypatch):
    from app.main import app

    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_IP", 2)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as outside:
        codes = [
            (await submit(outside, n, headers={"X-Forwarded-For": f"10.0.0.{n}"})).status_code
            for n in range(3)
        ]
    assert codes == [202, 202, 429]


@pytest.mark.integration
async def test_behind_the_proxy_each_client_has_its_own_bucket(api, db, salted, monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_IP", 2)
    codes = [(await submit(api, n, headers={"X-Forwarded-For": f"49.36.0.{n}"})).status_code
             for n in range(4)]
    assert codes == [202, 202, 202, 202]


@pytest.mark.integration
async def test_refusals_are_visible_in_meta_sources(api, db, salted, monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_REPORTER", 1)
    await submit(api, 1)
    assert (await submit(api, 1)).status_code == 429
    assert (await submit(api, 1)).status_code == 429
    body = (await api.get("/api/meta/sources")).json()
    assert body["rate_limited"]["rejected_24h"] == 2
    assert body["rate_limited"]["per_reporter"] == "1 per 10 min"
    assert body["rate_limited"]["per_ip"] == "300 per 10 min"


async def test_docket_lookups_are_60_a_minute_per_address(api):
    # A malformed docket answers 404 without touching the database; the limit comes first.
    for _ in range(60):
        assert (await api.get("/api/reports/track/NOT-A-DOCKET")).status_code == 404
    r = await api.get("/api/reports/track/NOT-A-DOCKET")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert await rate_limit.rejected_last_24h() == 1


async def test_a_submit_over_the_limit_needs_no_database(api, monkeypatch):
    """The 429 is decided before anything is stored or even read."""
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REPORTS_PER_REPORTER", 0)
    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "test-salt")
    assert (await submit(api, 1)).status_code == 429


async def test_limits_can_be_switched_off(api, monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_TRACK_PER_IP_PER_MINUTE", 0)
    assert (await api.get("/api/reports/track/NOT-A-DOCKET")).status_code == 404


def test_the_published_defaults():
    s = get_settings()
    assert (s.RATE_LIMIT_WINDOW_SECONDS, s.RATE_LIMIT_REPORTS_PER_REPORTER, s.RATE_LIMIT_REPORTS_PER_IP,
            s.RATE_LIMIT_TRACK_PER_IP_PER_MINUTE) == (600, 10, 300, 60)


# ── With Redis up, and with it failing ─────────────────────────────────────────

@pytest.fixture
async def live_redis():
    cache.use_memory_only(False)
    cache._client = None
    cache._unavailable_until = 0.0
    client = await cache._get_client()
    try:
        await client.ping()
    except Exception:
        cache.use_memory_only(True)
        pytest.skip("Redis is not reachable")
    await client.delete("rl:pytest")
    yield client
    await client.delete("rl:pytest")
    await cache.close()
    cache.use_memory_only(True)


@pytest.mark.integration
async def test_the_redis_window_matches_the_memory_window(live_redis):
    assert await cache.sliding_window("rl:pytest", 2, 10, now=1000.0) == (True, 0)
    assert await cache.sliding_window("rl:pytest", 2, 10, now=1001.0) == (True, 0)
    assert await cache.sliding_window("rl:pytest", 2, 10, now=1002.0) == (False, 8)
    assert cache.backend() == "redis"
    assert await live_redis.zcard("rl:pytest") == 2  # the refused one was not added
    assert await cache.sliding_window("rl:pytest", 2, 10, now=1010.5) == (True, 0)
    await live_redis.delete("rl:pytest")
    assert await cache.sliding_window("rl:pytest", 0, 10, now=1020.0) == (False, 10)
    assert cache.backend() == "redis"  # answered by the script, not by the fallback


async def test_a_failing_redis_still_limits_per_process(monkeypatch):
    class Exploding:
        async def eval(self, *a, **k):
            raise ConnectionError("Connection refused")

    cache.use_memory_only(False)
    monkeypatch.setattr(cache, "_client", Exploding())
    monkeypatch.setattr(cache, "_unavailable_until", 0.0)
    monkeypatch.setattr(cache, "_announced_down", False)
    try:
        assert (await cache.sliding_window("down", 1, 10, now=0.0))[0] is True
        assert (await cache.sliding_window("down", 1, 10, now=1.0))[0] is False
    finally:
        cache.use_memory_only(True)
