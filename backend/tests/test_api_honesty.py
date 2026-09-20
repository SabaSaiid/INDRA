"""
T8 (Day 5) — the API must not serve a number the database did not provide, and
must not be readable by any page on the internet.

Four long-standing untruths, each with its own section below:

1. GET /api/dashboard/summary invented KPIs on a DB error regardless of DEMO_MODE
   (covered in tests/test_demo_mode.py, now that the endpoint is in its list).
2. The dedup gates were module constants, so they could not be tuned from .env.
3. CORS was allow_origins=["*"] together with allow_credentials=True.
4. GET /api/scenario and POST /api/demo/trigger served a fabricated event.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings


@pytest_asyncio.fixture
async def api():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── CORS is an allow-list, not a wildcard ─────────────────────────────────────

async def test_an_unknown_origin_gets_no_cors_header(api):
    """
    allow_origins=["*"] with allow_credentials=True is forbidden by the CORS spec,
    and Starlette resolves the contradiction by echoing back whatever Origin it is
    sent. Any page on the internet could therefore read this API with the viewer's
    credentials attached.
    """
    r = await api.get("/api/info", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "http://127.0.0.1:3000"]
)
async def test_the_dashboard_origins_still_work(api, origin):
    """The command center must keep working — this is the point of the allow-list."""
    r = await api.get("/api/info", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


async def test_a_preflight_from_an_unknown_origin_is_not_approved(api):
    r = await api.request(
        "OPTIONS",
        "/api/reports/submit",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_cors_origins_parses_a_comma_separated_list():
    settings = get_settings()
    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_cors_origins_never_contains_a_wildcard():
    """
    A regression guard with teeth: "*" here, combined with allow_credentials, is
    the whole vulnerability this fix removes.
    """
    assert "*" not in get_settings().cors_origins


# ── The fabricated scenario surface is gone ───────────────────────────────────

async def test_the_scenario_endpoint_is_gone(api):
    """
    GET /api/scenario served data/samples/patna_flood_scenario.json as though it
    were a real verified event: 127 signals, confidence 0.94, AUTO_PUBLISHED,
    "IMD AWS recorded 92mm rainfall", two "CWC river level sensors", ten "verified
    multimedia evidence". None of it existed. There is no IMD or CWC feed, vision
    analysis is permanently offline, and the real pipeline cannot reach 0.94.
    """
    assert (await api.get("/api/scenario")).status_code == 404


async def test_the_demo_trigger_endpoint_is_gone(api):
    """
    POST /api/demo/trigger broadcast that fabrication to the dashboard over the
    live WebSocket as a DEMO_PULSE, alongside genuine VERIFIED_EVENT messages.
    """
    assert (await api.post("/api/demo/trigger")).status_code == 404


def test_the_fabricated_scenario_file_is_deleted():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "data" / "samples" / "patna_flood_scenario.json").exists()


# ── Dedup gates come from settings ────────────────────────────────────────────

def test_dedup_defaults_are_unchanged():
    """
    Moving these into settings must not have moved their values. Changing dedup
    behaviour on a day spent changing the scoring would make any regression
    impossible to attribute.
    """
    settings = get_settings()
    assert settings.DEDUP_COSINE_THRESHOLD == 0.88
    assert settings.DEDUP_GPS_DELTA_KM == 1.0
    assert settings.DEDUP_TIME_DELTA_MINUTES == 15
    assert settings.DEDUP_LEVENSHTEIN_THRESHOLD == 0.75


def test_the_module_constants_still_match_the_settings():
    """Several docstrings cite COSINE_THRESHOLD = 0.88 by name; keep them true."""
    from app.services import dedup

    settings = get_settings()
    assert dedup.COSINE_THRESHOLD == settings.DEDUP_COSINE_THRESHOLD
    assert dedup.GPS_DELTA_KM == settings.DEDUP_GPS_DELTA_KM
    assert dedup.TIME_DELTA_MINUTES == settings.DEDUP_TIME_DELTA_MINUTES
    assert dedup.LEVENSHTEIN_THRESHOLD == settings.DEDUP_LEVENSHTEIN_THRESHOLD


def test_the_gps_gate_is_really_read_from_settings(monkeypatch):
    """
    Proof the setting is load-bearing rather than decorative.

    Two reports 800 m apart are duplicates under the 1.0 km default. Tighten the
    gate to 0.5 km and they stop being duplicates. Uses the GPS gate rather than
    the cosine one so the assertion holds whether or not the embedding model is
    available — the text is identical either way.
    """
    from app.services.dedup import DedupService

    now = datetime.now(timezone.utc)
    body = "Water entering ground floor shops near Kankarbagh main road"
    # ~0.8 km north of the first point.
    existing = [(body, 25.5941, 85.1376, now - timedelta(minutes=2))]

    service = DedupService()
    settings = get_settings()

    monkeypatch.setattr(settings, "DEDUP_GPS_DELTA_KM", 1.0)
    assert service.find_duplicate(body, 25.6013, 85.1376, now, existing) == 0

    monkeypatch.setattr(settings, "DEDUP_GPS_DELTA_KM", 0.5)
    assert service.find_duplicate(body, 25.6013, 85.1376, now, existing) is None


def test_the_time_gate_is_really_read_from_settings(monkeypatch):
    from app.services.dedup import DedupService

    now = datetime.now(timezone.utc)
    body = "Kankarbagh underpass completely submerged, cars stuck"
    existing = [(body, 25.5941, 85.1376, now - timedelta(minutes=10))]

    service = DedupService()
    settings = get_settings()

    monkeypatch.setattr(settings, "DEDUP_TIME_DELTA_MINUTES", 15)
    assert service.find_duplicate(body, 25.5941, 85.1376, now, existing) == 0

    monkeypatch.setattr(settings, "DEDUP_TIME_DELTA_MINUTES", 5)
    assert service.find_duplicate(body, 25.5941, 85.1376, now, existing) is None


# ── The legacy prototype dashboard is gone ────────────────────────────────────

async def test_the_legacy_dashboard_is_gone(api):
    """
    /legacy served app/templates/index.html, a 1,069-line static mockup built
    before the pipeline existed. It claimed telemetry this system does not have:
    "IMD AWS Station 42410 registered 92.4mm rain pulse", "CWC Gauge: Ganga level
    rising 4.2cm/hr at Digha Ghat", "PyTorch Vision detected waist-deep
    floodwater (Prob: 0.91)", "127 Signals". No IMD or CWC feed exists and vision
    analysis is permanently offline.

    It exercised no code path and nothing referenced it. The real command center
    is the Next.js app on port 3000.
    """
    assert (await api.get("/legacy")).status_code == 404


def test_no_html_templates_are_served_from_the_backend():
    """
    The backend serves JSON and a WebSocket, not pages.

    app/templates/ held the prototype mockup; with it gone there is no server-side
    HTML left to drift out of step with the API. A new template appearing here
    would mean a second, hand-written view of the data — which is how the /legacy
    page came to claim IMD and CWC feeds that never existed.

    Deliberately a structural check rather than a grep for the old claim strings:
    main.py's comments quote several of them verbatim to record why they went, and
    that explanation is worth keeping.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"

    assert not (app_dir / "templates").exists()
    assert list(app_dir.rglob("*.html")) == []
