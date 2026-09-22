"""
GET /api/audit/recent — the platform-wide ledger view the admin console reads.

It replaces an invented audit trail on the admin page, so these tests pin that
the rows are the ledger's, newest first, that the whole chain is verified, and
that reading it needs the same roles as provenance.
"""

import pytest
import pytest_asyncio

from app.core.database import async_session
from app.models.enums import AuditAction
from app.services import audit
from tests.conftest import wipe_event_tables
from tests.test_review_api import api, tokens  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def three_rows():
    async with async_session() as db:
        await wipe_event_tables(db)
        actions = [AuditAction.QUARANTINE, AuditAction.ESCALATE, AuditAction.HUMAN_APPROVE]
        for i, action in enumerate(actions):
            await audit.record(
                db, event_id=None, operator_id=f"OP-TEST-{i}", action=action,
                reason=f"row {i}", details=None,
            )
        await db.commit()
    yield
    async with async_session() as db:
        await wipe_event_tables(db)


@pytest.mark.parametrize("who, expected", [("citizen", 403), ("analyst", 200), ("commander", 200), ("admin", 200)])
async def test_reading_the_ledger_needs_an_analyst_or_above(api, tokens, three_rows, who, expected):  # noqa: F811
    r = await api.get("/api/audit/recent", headers=tokens[who])

    assert r.status_code == expected


async def test_anonymous_is_401(api, three_rows):  # noqa: F811
    assert (await api.get("/api/audit/recent")).status_code == 401


async def test_rows_are_the_ledger_newest_first_with_the_chain_verified(api, tokens, three_rows):  # noqa: F811
    body = (await api.get("/api/audit/recent", headers=tokens["analyst"])).json()

    assert body["total"] == 3
    assert body["chain"] == {"valid": True, "checked": 3, "broken_at_seq": None}
    assert [r["action_taken"] for r in body["rows"]] == ["HUMAN_APPROVE", "ESCALATE", "QUARANTINE"]
    assert [r["reason"] for r in body["rows"]] == ["row 2", "row 1", "row 0"]
    assert all(len(r["sha256_hash"]) == 64 for r in body["rows"])


async def test_limit_returns_the_newest_rows_but_verifies_the_whole_chain(api, tokens, three_rows):  # noqa: F811
    body = (await api.get("/api/audit/recent?limit=1", headers=tokens["analyst"])).json()

    assert [r["action_taken"] for r in body["rows"]] == ["HUMAN_APPROVE"]
    assert body["chain"]["checked"] == 3
