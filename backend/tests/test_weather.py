"""
Day 2 T6 — Weather Station Corroboration via Open-Meteo.

Everything except the one `network`-marked test runs against an in-process
httpx.MockTransport, so the failure modes are exercised deterministically
without touching the internet.
"""

import json

import httpx
import pytest

from app.services import weather
from app.services.weather import (
    fetch_rainfall,
    rainfall_to_score,
    weather_score,
)

PATNA = (25.5941, 85.1376)


@pytest.fixture(autouse=True)
def _fresh_cache():
    weather.clear_cache()
    yield
    weather.clear_cache()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(series):
    body = {"hourly": {"time": ["t"] * len(series), "precipitation": series}}
    return lambda request: httpx.Response(200, json=body)


# ── Curve ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "mm, expected",
    [(0.0, 0.0), (2.5, 0.10), (15.6, 0.35), (64.5, 0.70), (115.6, 0.90), (204.5, 1.0), (400.0, 1.0)],
)
def test_curve_breakpoints_are_imd_categories(mm, expected):
    assert rainfall_to_score(mm) == pytest.approx(expected)


def test_curve_is_monotonic():
    scores = [rainfall_to_score(mm) for mm in range(0, 260, 5)]
    assert scores == sorted(scores)


# ── Fetch behaviour ────────────────────────────────────────────────────────────

async def test_sums_the_past_24h_series_and_ignores_null_hours():
    async with _client(_ok([1.0, None, 2.5, 0.5])) as c:
        assert await fetch_rainfall(*PATNA, client=c) == pytest.approx(4.0)


async def test_zero_rainfall_is_a_measurement_not_offline():
    async with _client(_ok([0.0] * 24)) as c:
        score, mm = await weather_score(*PATNA, client=c)
    assert score == 0.0
    assert mm == 0.0


async def test_same_cell_twice_makes_exactly_one_request():
    calls = []

    def handler(request):
        calls.append(request)
        return _ok([3.0])(request)

    async with _client(handler) as c:
        first = await fetch_rainfall(*PATNA, client=c)
        # ~100 m away: same H3 res-8 cell.
        second = await fetch_rainfall(PATNA[0] + 0.0009, PATNA[1], client=c)

    assert first == second == 3.0
    assert len(calls) == 1


async def test_cache_expires_after_ten_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(weather, "_clock", lambda: now[0])
    calls = []

    def handler(request):
        calls.append(request)
        return _ok([1.0])(request)

    async with _client(handler) as c:
        await fetch_rainfall(*PATNA, client=c)
        now[0] += 599
        await fetch_rainfall(*PATNA, client=c)
        now[0] += 2
        await fetch_rainfall(*PATNA, client=c)

    assert len(calls) == 2


async def test_network_unreachable_returns_none():
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    async with _client(handler) as c:
        assert await weather_score(*PATNA, client=c) == (None, None)


async def test_timeout_returns_none():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async with _client(handler) as c:
        assert await fetch_rainfall(*PATNA, client=c) is None


@pytest.mark.parametrize("status", [404, 429, 500, 503])
async def test_non_200_returns_none(status):
    async with _client(lambda r: httpx.Response(status, text="nope")) as c:
        assert await fetch_rainfall(*PATNA, client=c) is None


@pytest.mark.parametrize(
    "body",
    [
        b"<html>not json</html>",
        json.dumps({"hourly": {}}).encode(),
        json.dumps({"hourly": {"precipitation": []}}).encode(),
        json.dumps({"hourly": {"precipitation": [None, None]}}).encode(),
        json.dumps({"hourly": {"precipitation": ["abc"]}}).encode(),
        json.dumps({"reason": "error"}).encode(),
    ],
)
async def test_malformed_response_returns_none_and_logs(body, caplog):
    async with _client(lambda r: httpx.Response(200, content=body)) as c:
        assert await fetch_rainfall(*PATNA, client=c) is None
    assert any("malformed" in rec.message for rec in caplog.records)


async def test_failure_is_cached_briefly_not_for_ten_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(weather, "_clock", lambda: now[0])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    async with _client(handler) as c:
        await fetch_rainfall(*PATNA, client=c)
        await fetch_rainfall(*PATNA, client=c)  # cached failure
        now[0] += 61
        await fetch_rainfall(*PATNA, client=c)  # retried

    assert len(calls) == 2


# ── Live ───────────────────────────────────────────────────────────────────────

@pytest.mark.network
async def test_live_open_meteo_for_patna_never_raises():
    score, mm = await weather_score(*PATNA)
    assert score is None or 0.0 <= score <= 1.0
    assert (score is None) == (mm is None)
