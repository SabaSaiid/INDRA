"""
Phase 1 T2 — what a report can now say about itself: when it happened, who sent
it (pseudonymously), and what the citizen thinks it is.

Integration level: these run against `indra_test`, because the guarantees are
the database's — a unique docket, one row per fed post, the raw client id never
stored anywhere.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import wipe_event_tables

from app.core.database import async_session

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db():
    async with async_session() as session:
        await wipe_event_tables(session)
        try:
            yield session
        finally:
            await session.rollback()
            await wipe_event_tables(session)


async def _insert(db, **cols):
    base = {
        "id": str(uuid.uuid4()),
        "source_type": "CITIZEN_APP",
        "raw_text": "Water on the road near the station",
        "lat": 25.5941,
        "lng": 85.1376,
    }
    base.update(cols)
    extra = [k for k in cols if k in ("docket", "platform", "external_id")]
    columns = ", ".join(["id", "source_type", "raw_text", "latitude", "longitude"] + extra)
    values = ", ".join(
        ["CAST(:id AS uuid)", "CAST(:source_type AS source_type_enum)", ":raw_text", ":lat", ":lng"]
        + [f":{k}" for k in extra]
    )
    await db.execute(text(f"INSERT INTO raw_reports ({columns}) VALUES ({values})"), base)


# ── Migration 0012: constraints ────────────────────────────────────────────────

async def test_a_docket_is_unique(db):
    await _insert(db, docket="R-7K3M9QX2")
    await db.commit()
    with pytest.raises(IntegrityError, match="uq_raw_reports_docket"):
        await _insert(db, docket="R-7K3M9QX2")
        await db.commit()


async def test_a_fed_post_is_stored_once_per_platform(db):
    await _insert(db, source_type="SOCIAL_MEDIA", platform="mastodon", external_id="https://x.social/1")
    await _insert(db, source_type="NEWS_MEDIA", platform="google_news", external_id="https://x.social/1")
    await db.commit()
    with pytest.raises(IntegrityError, match="uq_raw_reports_platform_external_id"):
        await _insert(db, source_type="SOCIAL_MEDIA", platform="mastodon", external_id="https://x.social/1")
        await db.commit()


async def test_reports_without_an_external_id_never_collide(db):
    for _ in range(3):
        await _insert(db)
        await _insert(db, platform="mastodon")
    await db.commit()
    count = (await db.execute(text("SELECT count(*) FROM raw_reports"))).scalar()
    assert count == 6
