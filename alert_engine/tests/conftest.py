"""
Alert Engine — Test Suite
Pytest configuration and shared fixtures.

Usage:
  # All tests (no Docker needed)
  pytest alert_engine/tests/ -v

  # Integration tests only (requires INDRA backend running on localhost:8000)
  pytest alert_engine/tests/ -m integration -v
"""

import asyncio
import os
import sys
import tempfile
import pytest
import pytest_asyncio

# Ensure the INDRA root is on the path so `alert_engine` is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── markers ────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests that require a running INDRA backend (localhost:8000)",
    )
    config.addinivalue_line(
        "markers",
        "e2e: full golden-scenario end-to-end tests",
    )


# ── shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    """Yields a temporary SQLite path; the file is removed after the test."""
    db_path = str(tmp_path / "test_alert_engine.db")
    yield db_path


@pytest_asyncio.fixture
async def store(temp_db):
    """An initialised PersistentStore backed by a fresh temp database."""
    from alert_engine.state.persistent_store import PersistentStore
    s = PersistentStore(temp_db)
    await s.init_db()
    return s


@pytest.fixture
def patna_event():
    """A realistic IndraEvent that mirrors the Patna flood golden scenario."""
    from alert_engine.models import IndraEvent
    return IndraEvent(
        id="WX-EV-28231827-A",
        event_code="INDRA-20260916-001",
        event_type="URBAN_FLOOD",
        severity="CRITICAL",
        confidence_score=0.94,
        review_status="AUTO_PUBLISHED",
        quadrant="Critical Verified Event",
        impact_radius_km=6.8,
        lat=25.6093,
        lng=85.1376,
        city="Patna",
        state="Bihar",
        verified_at="2026-09-16T10:00:00+00:00",
        source_count=103,
        verification_receipt={
            "confidence_score": 0.94,
            "factors": [
                {"factor": "Weather Station Corroboration", "weight_pct": 25, "score": 0.96, "weighted_points": 24.0, "evidence": "Open-Meteo 92mm/3hr"},
                {"factor": "Report Density Analysis",      "weight_pct": 20, "score": 0.95, "weighted_points": 19.0, "evidence": "103 verified reports"},
                {"factor": "Spatial Coherence Score",      "weight_pct": 20, "score": 0.95, "weighted_points": 19.0, "evidence": "PostGIS clustering"},
                {"factor": "Computer Vision Analysis",     "weight_pct": 15, "score": 0.91, "weighted_points": 13.65, "evidence": "Flood depth 0.91"},
                {"factor": "Source Reliability Index",     "weight_pct": 15, "score": 0.89, "weighted_points": 13.35, "evidence": "High trust"},
                {"factor": "Anomaly Detection Signal",     "weight_pct": 5,  "score": 1.0,  "weighted_points": 5.0,  "evidence": "140mm vs 35mm baseline"},
            ],
        },
        raw_source="api",
    )


@pytest.fixture
def advisory_event():
    """A low-severity event that should NOT trigger any alert rule."""
    from alert_engine.models import IndraEvent
    return IndraEvent(
        id="TEST-EVENT-LOW-001",
        event_code="INDRA-20260916-LOW",
        event_type="URBAN_FLOOD",
        severity="ADVISORY",
        confidence_score=0.45,
        review_status="QUARANTINED",
        quadrant="Noise",
        impact_radius_km=1.0,
        lat=25.0,
        lng=85.0,
        city="TestCity",
        state="Bihar",
        verified_at="2026-09-16T10:00:00+00:00",
        source_count=1,
        verification_receipt={},
        raw_source="api",
    )
