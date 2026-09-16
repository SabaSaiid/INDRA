"""
Shared pytest fixtures for the INDRA backend suite.

Nothing here needs a database. Tests that do need Postgres/Redpanda must carry
the `@pytest.mark.integration` marker so `pytest -m "not integration"` stays
runnable on a machine with no Docker.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.services.dedup import DedupService, _get_embedding_model
from app.services.fusion_engine import FusionEngine


# ── Service fixtures (no DB) ───────────────────────────────────────────────────

@pytest.fixture
def fusion() -> FusionEngine:
    """A bare FusionEngine — it holds no state and needs no database."""
    return FusionEngine()


@pytest.fixture
def dedup() -> DedupService:
    """A bare DedupService — the embedding model is loaded lazily and cached."""
    return DedupService()


# ── Embedding-model availability ───────────────────────────────────────────────

def embeddings_available() -> bool:
    """
    True when sentence-transformers loaded successfully.

    Dedup has two text-similarity paths with different thresholds (cosine 0.88
    vs Levenshtein 0.75), so a handful of tests have to know which one is live
    rather than hardcoding an expectation.
    """
    return _get_embedding_model() is not None


requires_embeddings = pytest.mark.skipif(
    not embeddings_available(),
    reason="sentence-transformers model unavailable — dedup is on the Levenshtein fallback",
)


# ── Shared geo/time constants ──────────────────────────────────────────────────

PATNA_LAT = 25.5941
PATNA_LNG = 85.1376
T0 = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)


# ── HTTP client ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """
    An httpx.AsyncClient bound directly to the ASGI app.

    Note this does NOT run the lifespan, so the Kafka consumer task and the
    PostGIS check in init_db() never fire — which is what makes it usable
    without Docker. Endpoints that hit the DB go through app.core.demo:
    demo data if DEMO_MODE is true, HTTP 503 if it is false.
    """
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
