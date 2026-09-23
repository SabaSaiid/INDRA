"""
Day 2 T1, T2, T8 — POST /api/reports/submit.

Unit level: the database session and the Kafka producer are both replaced with
in-memory fakes, so these pin the endpoint's own behaviour — what it rejects,
what it stores, and what it publishes — without Docker. The live-DB versions
of the same checks are in test_reports_api_integration.py.
"""

import json
import sys
import types

import pytest
import pytest_asyncio

from app.core.database import get_db


class FakeSession:
    def __init__(self):
        self.inserts = []

    async def execute(self, statement, params=None):
        self.inserts.append(params)

    async def commit(self):
        pass


class FakeProducer:
    sent = []

    def __init__(self, **kwargs):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_and_wait(self, topic, value):
        FakeProducer.sent.append((topic, json.loads(value.decode("utf-8"))))


@pytest.fixture
def session():
    return FakeSession()


@pytest_asyncio.fixture
async def api(session, monkeypatch):
    import httpx

    from app.main import app

    FakeProducer.sent = []
    monkeypatch.setitem(sys.modules, "aiokafka", types.SimpleNamespace(AIOKafkaProducer=FakeProducer))

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def body(lat, lng, text="Knee-deep water on Boring Road near the Patna Women's College"):
    return {"latitude": lat, "longitude": lng, "text": text}


# ── T1: rejection ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lat, lng", [(48.85, 2.35), (-33.87, 151.21)])
async def test_out_of_india_is_422_and_nothing_is_stored_or_published(api, session, lat, lng):
    r = await api.post("/api/reports/submit", json=body(lat, lng))

    assert r.status_code == 422
    assert "outside India" in r.json()["detail"]
    assert session.inserts == []
    assert FakeProducer.sent == []


@pytest.mark.parametrize(
    "lat, lng",
    [(25.5941, 85.1376), (8.09, 77.55), (35.5, 77.0), (28.6139, 77.2090)],
)
async def test_in_india_is_accepted_with_coordinates_unchanged(api, session, lat, lng):
    r = await api.post("/api/reports/submit", json=body(lat, lng))

    assert r.status_code == 202
    assert len(session.inserts) == 1
    assert (session.inserts[0]["lat"], session.inserts[0]["lng"]) == (lat, lng)


# ── T2: message matches the stored row ─────────────────────────────────────────

async def test_published_message_matches_the_stored_row(api, session):
    # Swapped pair: stored coordinates differ from what the client sent, which
    # is exactly the case where the old message diverged from the row.
    r = await api.post("/api/reports/submit", json=body(85.1376, 25.5941))
    assert r.status_code == 202

    row = session.inserts[0]
    (topic, msg), = FakeProducer.sent

    assert msg["id"] == r.json()["id"]
    assert round(msg["latitude"], 6) == round(row["lat"], 6) == 25.5941
    assert round(msg["longitude"], 6) == round(row["lng"], 6) == 85.1376
    assert msg["raw_text"] == row["raw_text"]
    assert "text" not in msg
    assert msg["h3_res8"] == row["h3_cell"] and msg["h3_res8"]
    assert msg["credibility_score"] == row["credibility"]


# ── T8: credibility is computed, not 0.5 ───────────────────────────────────────

async def test_stored_credibility_reflects_report_quality(api, session):
    await api.post("/api/reports/submit", json=body(25.5941, 85.1376))
    await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text="flood"))

    specific, terse = (p["credibility"] for p in session.inserts)
    assert 0.5 <= specific <= 0.7
    assert terse < 0.4


# ── Day 4 T3: no false success ─────────────────────────────────────────────────

class FailingSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.rolled_back = False

    async def execute(self, statement, params=None):
        raise ConnectionRefusedError("postgres is down")

    async def rollback(self):
        self.rolled_back = True


async def test_unstored_report_is_503_and_never_published(api, monkeypatch):
    from app.core.database import get_db
    from app.main import app

    failing = FailingSession()

    async def _db():
        yield failing

    app.dependency_overrides[get_db] = _db
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 503
    assert r.json() == {"detail": "Report could not be stored"}
    assert failing.rolled_back
    assert FakeProducer.sent == []


async def test_stored_but_unpublished_report_is_202_not_queued(api, session, monkeypatch):
    async def _boom(self):
        raise ConnectionRefusedError("redpanda is down")

    monkeypatch.setattr(FakeProducer, "start", _boom)
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    assert r.json()["queued"] is False
    assert len(session.inserts) == 1
    assert FakeProducer.sent == []


async def test_stored_and_published_report_is_queued(api, session):
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    assert r.json()["queued"] is True
    assert len(FakeProducer.sent) == 1


# ── Day 5 T2: per-report analysis is stored at ingest ──────────────────────────

def _stored_analysis(session):
    """The analysis JSON from the insert the endpoint just performed."""
    assert session.inserts, "nothing was inserted"
    raw = session.inserts[-1]["analysis"]
    return None if raw is None else json.loads(raw)


async def test_every_stored_report_carries_an_analysis(api, session):
    r = await api.post(
        "/api/reports/submit",
        json=body(25.5941, 85.1376, text="Water 3 feet deep near Gandhi Maidan"),
    )
    assert r.status_code == 202

    analysis = _stored_analysis(session)
    assert analysis is not None
    assert set(analysis) == {
        "cleaned_text",
        "language",
        "depth_cm",
        "depth_basis",
        "keywords",
        "places",
        "url_count",
        "phone_count",
        "extracted_at",
    }
    assert analysis["depth_cm"] == 91          # 3 ft
    assert analysis["depth_basis"] == "measure:feet"
    assert analysis["language"] == "en"


@pytest.mark.parametrize(
    "text_in,depth_cm,language",
    [
        ("Water 3 feet deep near Gandhi Maidan", 91, "en"),
        ("घुटने तक पानी भरा है", 50, "hi"),
        ("2.5 ft paani Kankarbagh main road", 76, "hinglish"),
        ("flood", None, "en"),
    ],
)
async def test_analysis_extracts_depth_and_language(api, session, text_in, depth_cm, language):
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text=text_in))
    assert r.status_code == 202

    analysis = _stored_analysis(session)
    assert analysis["depth_cm"] == depth_cm
    assert analysis["language"] == language


async def test_places_are_gazetteer_cities_not_landmarks(api, session):
    """
    `places` resolves the gazetteer, so it holds cities — not street landmarks.

    Worth pinning because it is easy to read the field name as "landmarks" and
    then claim the system extracts them. "Gandhi Maidan" is a landmark and does
    not appear; "Patna" is a gazetteer city and does.
    """
    await api.post(
        "/api/reports/submit",
        json=body(25.5941, 85.1376, text="Flooding in Patna near Gandhi Maidan"),
    )
    analysis = _stored_analysis(session)
    assert analysis["places"] == ["Patna"]
    assert "Gandhi Maidan" not in analysis["places"]


@pytest.mark.parametrize(
    "text_in",
    [
        "flood",                 # exactly min_length
        "x" * 2000,              # exactly max_length
        "🌊🌊🌊🌊🌊",                # emoji only, no letters at all
        "देखो! पानी… <script>alert(1)</script>",   # mixed script and markup
        "     ok     ",          # padded to length with whitespace
        "3 ft 3 ft 3 ft 3 ft",   # repeated depth mentions
    ],
)
async def test_odd_text_still_yields_an_analysis(api, session, text_in):
    """
    Extraction must survive anything ingest accepts, without raising.

    Note the emoji-only case: detect_language divides by the number of letters,
    so a report with zero letters would be a ZeroDivisionError if the guard were
    dropped.
    """
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text=text_in))
    assert r.status_code == 202

    analysis = _stored_analysis(session)
    assert analysis is not None
    assert isinstance(analysis["cleaned_text"], str)
    assert analysis["language"] in {"en", "hi", "hinglish"}


@pytest.mark.parametrize("text_in", ["", "oops", "x" * 2001])
async def test_text_outside_the_schema_bounds_is_422_and_stores_nothing(api, session, text_in):
    """
    The real contract, pinned: text is 5-2000 characters.

    Written after a test of mine assumed ingest accepted a 2-character and a
    4000-character report; it does not, and it is right not to. Validation
    rejecting them before any analysis runs is the behaviour worth keeping.
    """
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text=text_in))
    assert r.status_code == 422
    assert session.inserts == []


async def test_a_failing_analyser_still_stores_the_report(api, session, monkeypatch, caplog):
    """
    A disaster report is not worth losing to a regex.

    If extraction raises, the report is stored with analysis NULL and the client
    still gets 202. The WARNING is the only trace, and it names the report id.
    """
    from app.api import reports as reports_api

    def _boom(_text):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(reports_api, "extract_metadata", _boom)

    with caplog.at_level("WARNING", logger="indra.api.reports"):
        r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    assert _stored_analysis(session) is None
    assert any("Analysis failed" in m for m in caplog.messages)


async def test_analysis_never_modifies_raw_text(api, session):
    """
    raw_text is the evidence; cleaned_text is a derived convenience.

    The stored raw_text must be byte-identical to what the citizen sent, even
    though cleaned_text normalises it.
    """
    messy = "Water   here  https://x.co/a  ２ ft"
    await api.post("/api/reports/submit", json=body(25.5941, 85.1376, text=messy))

    params = session.inserts[-1]
    assert params["raw_text"] == messy

    analysis = _stored_analysis(session)
    assert analysis["cleaned_text"] != messy
    assert "<URL>" in analysis["cleaned_text"]


class TestIngestStoresTheLocation:
    """
    BUG-033: the ingest path resolved a location and discarded it on the very
    next line, because raw_reports had no column to put it in. The field-
    reports map layer needs it, and the resolved name was a dead variable for
    the whole life of the endpoint.
    """

    async def test_a_report_with_gps_is_stored_with_its_district(self, api, session):
        response = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))
        assert response.status_code == 202

        stored = session.inserts[0]
        assert stored["district"] == "Patna"
        assert stored["state"] == "Bihar"

    async def test_a_report_we_cannot_place_stores_null_not_a_placeholder(
        self, api, session, monkeypatch
    ):
        """
        NULL, never "Unknown" and never "India Node". A name the database does
        not have must stay absent so the map can say so.
        """
        monkeypatch.setattr(
            "app.api.reports.sanitize_coordinates",
            lambda *a, **k: (25.5941, 85.1376, "", ""),
        )
        response = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))
        assert response.status_code == 202

        stored = session.inserts[0]
        assert stored["district"] is None
        assert stored["state"] is None


# ── Phase 1 T2: observed_at, hazard and X-Reporter-Id ──────────────────────────

import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services import ingest


def _now():
    return datetime.now(timezone.utc)


async def test_existing_clients_send_none_of_the_new_fields_and_nothing_changes(api, session):
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376))

    assert r.status_code == 202
    row = session.inserts[0]
    # observed_at None: the INSERT falls back to NOW(), the same instant as created_at.
    assert row["observed_at"] is None
    assert row["citizen_hazard"] is None
    assert row["reporter_hash"] is None


@pytest.mark.parametrize(
    "offset",
    [timedelta(hours=-2), timedelta(minutes=4), timedelta(days=-6, hours=-23)],
    ids=["2h-ago", "4min-ahead", "6d23h-ago"],
)
async def test_a_plausible_observed_at_is_stored_as_sent(api, session, offset):
    when = _now() + offset
    r = await api.post(
        "/api/reports/submit", json={**body(25.5941, 85.1376), "observed_at": when.isoformat()}
    )

    assert r.status_code == 202
    assert session.inserts[0]["observed_at"] == when


@pytest.mark.parametrize(
    "value",
    [
        (_now() + timedelta(hours=1)).isoformat(),
        (_now() - timedelta(days=8)).isoformat(),
        "2026-09-23T10:00:00",          # no timezone: ambiguous, so refused
        "yesterday",
    ],
    ids=["1h-ahead", "8d-ago", "naive", "not-a-time"],
)
async def test_an_implausible_observed_at_is_422_and_nothing_is_stored(api, session, value):
    r = await api.post("/api/reports/submit", json={**body(25.5941, 85.1376), "observed_at": value})

    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "observed_at"]
    assert session.inserts == []


async def test_the_citizens_hazard_is_stored_as_their_claim(api, session):
    r = await api.post("/api/reports/submit", json={**body(25.5941, 85.1376), "hazard": "HEATWAVE"})

    assert r.status_code == 202
    assert session.inserts[0]["citizen_hazard"] == "HEATWAVE"


@pytest.mark.parametrize("hazard", ["TORNADO", "heatwave", ""])
async def test_an_unknown_hazard_is_422(api, session, hazard):
    r = await api.post("/api/reports/submit", json={**body(25.5941, 85.1376), "hazard": hazard})

    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "hazard"]
    assert session.inserts == []


@pytest.fixture
def salt(monkeypatch):
    """Pinned: the suite reads the machine's .env (BUG-059)."""
    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "test-salt")
    return "test-salt"


async def test_the_same_reporter_id_gives_the_same_pseudonym(api, session, salt):
    for _ in range(2):
        r = await api.post(
            "/api/reports/submit", json=body(25.5941, 85.1376), headers={"X-Reporter-Id": "abc"}
        )
        assert r.status_code == 202

    first, second = (p["reporter_hash"] for p in session.inserts)
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == hmac.new(b"test-salt", b"abc", hashlib.sha256).hexdigest()


async def test_different_reporters_get_different_pseudonyms(api, session, salt):
    for rid in ("abc", "abd"):
        await api.post("/api/reports/submit", json=body(25.5941, 85.1376), headers={"X-Reporter-Id": rid})

    first, second = (p["reporter_hash"] for p in session.inserts)
    assert first != second


@pytest.mark.parametrize("headers", [{}, {"X-Reporter-Id": "   "}], ids=["absent", "blank"])
async def test_no_reporter_id_is_unknown_never_a_shared_identity(api, session, salt, headers):
    r = await api.post("/api/reports/submit", json=body(25.5941, 85.1376), headers=headers)

    assert r.status_code == 202
    assert session.inserts[0]["reporter_hash"] is None


async def test_an_overlong_reporter_id_is_422(api, session, salt):
    r = await api.post(
        "/api/reports/submit", json=body(25.5941, 85.1376), headers={"X-Reporter-Id": "x" * 201}
    )

    assert r.status_code == 422
    assert session.inserts == []


async def test_without_a_salt_no_pseudonym_is_stored_and_it_is_said_once(
    api, session, monkeypatch, caplog
):
    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "")
    monkeypatch.setattr(ingest, "_warned_no_salt", False)

    with caplog.at_level("WARNING", logger="indra.services.ingest"):
        for _ in range(2):
            await api.post(
                "/api/reports/submit", json=body(25.5941, 85.1376), headers={"X-Reporter-Id": "abc"}
            )

    assert [p["reporter_hash"] for p in session.inserts] == [None, None]
    assert sum("REPORTER_SALT is not set" in m for m in caplog.messages) == 1
