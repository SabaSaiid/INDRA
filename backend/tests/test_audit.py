"""
T2 (Day 3) — the audit ledger's hash chain.

The trigger forbids tampering with real rows, so every tamper case works on
in-memory copies of rows read back from Postgres and runs them through the pure
`verify_rows`. The round trip through Postgres matters: it proves the hash still
recomputes after `logged_at` and the JSONB `details` have been stored and read
back, which is where a canonicalisation bug would show up.
"""

import asyncio
import copy
import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import async_session
from app.models.enums import AuditAction
from app.services import audit
from tests.conftest import wipe_event_tables

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


async def write(db, n, reason="decision {i}"):
    rows = []
    for i in range(n):
        rows.append(
            await audit.record(
                db,
                event_id=None,
                operator_id="OP-TEST",
                action=AuditAction.ESCALATE,
                reason=reason.format(i=i),
                details={"confidence_score": 0.4314 + i / 100, "report_count": i + 2,
                         "to_status": "QUARANTINED"},
            )
        )
        await db.commit()
    return rows


# ── Writing ────────────────────────────────────────────────────────────────────

async def test_first_row_links_to_genesis(db):
    [row] = await write(db, 1)

    assert row["prev_hash"] == "0" * 64
    assert len(row["sha256_hash"]) == 64


async def test_sequential_rows_link_and_verify(db):
    await write(db, 3)
    rows = await audit.fetch_rows(db)

    assert [r["prev_hash"] for r in rows[1:]] == [r["sha256_hash"] for r in rows[:-1]]
    assert await audit.verify_chain(db) == {"valid": True, "checked": 3, "broken_at_seq": None}


async def test_stored_hash_recomputes_after_round_trip(db):
    await write(db, 3)

    for r in await audit.fetch_rows(db):
        payload = {
            "prev_hash": r["prev_hash"],
            "event_id": r["event_id"],
            "operator_id": r["operator_id"],
            "action": r["action_taken"],
            "reason": r["reason"],
            "details": r["details"],
            "logged_at": r["logged_at"].isoformat(timespec="microseconds"),
        }
        assert hashlib.sha256(audit.canonical_json(payload).encode()).hexdigest() == r["sha256_hash"]


# ── Tampering (on copies) ──────────────────────────────────────────────────────

async def test_edited_reason_breaks_at_that_row(db):
    await write(db, 3)
    rows = copy.deepcopy(await audit.fetch_rows(db))
    rows[1]["reason"] = "nothing to see here"

    assert audit.verify_rows(rows) == {"valid": False, "checked": 2, "broken_at_seq": rows[1]["seq"]}


async def test_deleted_row_breaks_at_its_successor(db):
    await write(db, 3)
    rows = copy.deepcopy(await audit.fetch_rows(db))
    third_seq = rows[2]["seq"]
    del rows[1]

    result = audit.verify_rows(rows)
    assert result["valid"] is False
    assert result["broken_at_seq"] == third_seq


async def test_swapped_rows_break_the_chain(db):
    await write(db, 3)
    rows = copy.deepcopy(await audit.fetch_rows(db))
    rows[1], rows[2] = rows[2], rows[1]

    assert audit.verify_rows(rows)["valid"] is False


async def test_empty_chain_is_valid():
    assert audit.verify_rows([]) == {"valid": True, "checked": 0, "broken_at_seq": None}


async def test_hindi_reason_hashes_stably_and_unescaped(db):
    [row] = await write(db, 1, reason="पटना में बाढ़")
    [stored] = await audit.fetch_rows(db)

    kwargs = dict(
        prev_hash=stored["prev_hash"], event_id=None, operator_id="OP-TEST",
        action="ESCALATE", reason=stored["reason"], details=stored["details"],
        logged_at=stored["logged_at"],
    )
    assert audit.compute_hash(**kwargs) == audit.compute_hash(**kwargs) == row["sha256_hash"]
    assert "पटना में बाढ़" in audit.canonical_json({"reason": stored["reason"]})
    assert audit.verify_rows([stored])["valid"] is True


# ── Concurrency ────────────────────────────────────────────────────────────────

async def _concurrent_writes(n):
    async def one(i):
        async with async_session() as s:
            await audit.record(
                s, event_id=None, operator_id=f"OP-{i}", action=AuditAction.ESCALATE,
                reason=f"concurrent {i}", details=None,
            )
            await s.commit()

    await asyncio.gather(*(one(i) for i in range(n)))


async def test_twenty_concurrent_writers_do_not_fork_the_chain(db):
    await _concurrent_writes(20)
    rows = await audit.fetch_rows(db)

    assert len(rows) == 20
    assert len({r["prev_hash"] for r in rows}) == 20
    assert audit.verify_rows(rows)["valid"] is True


async def test_without_the_advisory_lock_the_chain_forks(db, monkeypatch):
    """Proves the lock is load-bearing, not decoration."""
    monkeypatch.setattr(audit, "_ADVISORY_LOCK_ENABLED", False)

    forked = False
    for _ in range(5):
        await wipe_event_tables(db)
        await _concurrent_writes(20)
        rows = await audit.fetch_rows(db)
        if len({r["prev_hash"] for r in rows}) < len(rows):
            forked = True
            break

    assert forked, "20 unlocked concurrent writers never forked in 5 tries"


# ── The trigger still guards real rows ─────────────────────────────────────────

@pytest.mark.parametrize("statement", [
    "UPDATE audit_logs SET reason = 'rewritten'",
    "DELETE FROM audit_logs",
])
async def test_written_rows_cannot_be_updated_or_deleted(db, statement):
    await write(db, 1)

    with pytest.raises(DBAPIError, match="immutable ledger"):
        await db.execute(text(statement))
    await db.rollback()

    assert len(await audit.fetch_rows(db)) == 1
