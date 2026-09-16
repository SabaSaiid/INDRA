"""
INDRA Platform — Audit Service (append-only SHA-256 hash chain)

The audit trail records *decisions* about events — the pipeline creating or
re-classifying one, a commander approving, rejecting or re-grading one. It does
not record traffic; the raw_reports rows are already their own record.

Two independent protections
---------------------------
* `trg_audit_immutable` (migration 0001) stops a row being UPDATEd or DELETEd
  in place.
* This module's hash chain makes a history that was rewritten some other way —
  restored from an edited backup, or edited while a superuser had the trigger
  disabled — *detectable*: any row changed, removed or reordered breaks the
  links after it. The trigger prevents; the chain proves.

What the chain cannot prove on its own: that nothing was cut off the **end**.
An emptied table (TRUNCATE bypasses the row trigger) or a ledger missing its
newest rows is still a valid chain. Catching that needs the head hash anchored
outside this database (a log line, the events topic, a signed receipt); that is
not built.

Design
------
* ``hash = sha256(canonical_json({prev_hash, event_id, operator_id, action,
  reason, details, logged_at}))`` where canonical JSON is ``sort_keys=True``,
  ``separators=(",", ":")``, ``ensure_ascii=False``, UTF-8 encoded, and
  ``logged_at`` is ISO-8601 UTC with microseconds.
* ``logged_at`` is set here, by the app, not by the column's ``NOW()`` default:
  a server-side timestamp could not be fed into the hash before the insert.
* The genesis row has ``prev_hash = "0" * 64``.
* **One global chain**, ordered by ``seq``, not one chain per event. Each row
  stores its own ``prev_hash``, so any row can still be checked against its
  immediate predecessor. ``seq`` may have gaps (a rolled-back transaction still
  consumes a sequence value); the links, not the numbers, define the chain.
* Appends take ``pg_advisory_xact_lock(AUDIT_CHAIN_LOCK_KEY)``, then read the
  latest hash, then insert — all inside the caller's transaction, and the lock
  is released at the caller's commit or rollback. Without the lock two
  concurrent writers read the same predecessor and the chain forks;
  tests/test_audit.py reproduces that fork with the lock switched off.
* ``record()`` never commits. The caller owns the transaction, so an event
  change and its audit row are committed — or rolled back — together.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditAction

GENESIS_HASH = "0" * 64

# Arbitrary fixed 64-bit key identifying "the audit chain" to pg_advisory_xact_lock.
AUDIT_CHAIN_LOCK_KEY = 0x1D7A_A0D1

# Only tests switch this off, to prove the lock is what prevents forks.
_ADVISORY_LOCK_ENABLED = True

SYSTEM_PIPELINE_OPERATOR = "SYSTEM-PIPELINE"


def _iso_utc(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(
    *,
    prev_hash: str,
    event_id: Optional[Any],
    operator_id: str,
    action: Any,
    reason: Optional[str],
    details: Optional[Mapping[str, Any]],
    logged_at: datetime,
) -> str:
    payload = {
        "prev_hash": prev_hash,
        "event_id": str(event_id) if event_id is not None else None,
        "operator_id": operator_id,
        "action": str(getattr(action, "value", action)),
        "reason": reason,
        "details": details,
        "logged_at": _iso_utc(logged_at),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


async def record(
    db: AsyncSession,
    *,
    event_id: Optional[Any],
    operator_id: str,
    action: AuditAction,
    reason: Optional[str],
    details: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """
    Append one row to the chain inside the caller's transaction. Does not commit.
    """
    if _ADVISORY_LOCK_ENABLED:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_CHAIN_LOCK_KEY}
        )

    prev_hash = (
        await db.execute(
            text("SELECT sha256_hash FROM audit_logs ORDER BY seq DESC LIMIT 1")
        )
    ).scalar() or GENESIS_HASH

    logged_at = datetime.now(timezone.utc)
    details = dict(details) if details is not None else None
    row_id = uuid4()
    sha = compute_hash(
        prev_hash=prev_hash,
        event_id=event_id,
        operator_id=operator_id,
        action=action,
        reason=reason,
        details=details,
        logged_at=logged_at,
    )

    seq = (
        await db.execute(
            text("""
                INSERT INTO audit_logs
                    (id, event_id, operator_id, action_taken, reason,
                     sha256_hash, prev_hash, details, logged_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:event_id AS uuid), :operator_id,
                     CAST(:action AS audit_action_enum), :reason,
                     :sha, :prev, CAST(:details AS jsonb), :logged_at)
                RETURNING seq
            """),
            {
                "id": str(row_id),
                "event_id": str(event_id) if event_id is not None else None,
                "operator_id": operator_id,
                "action": action.value,
                "reason": reason,
                "sha": sha,
                "prev": prev_hash,
                "details": json.dumps(details) if details is not None else None,
                "logged_at": logged_at,
            },
        )
    ).scalar()

    return {
        "id": str(row_id),
        "seq": seq,
        "event_id": str(event_id) if event_id is not None else None,
        "operator_id": operator_id,
        "action_taken": action.value,
        "reason": reason,
        "details": details,
        "logged_at": logged_at,
        "prev_hash": prev_hash,
        "sha256_hash": sha,
    }


def verify_rows(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Pure check of a chain, starting from genesis, in the order given (by seq).

    A row breaks the chain if its prev_hash is not the previous row's hash, or
    if its stored hash does not match a recomputation of its own contents.
    Returns ``{"valid", "checked", "broken_at_seq"}``; ``checked`` counts the
    rows examined up to and including the first break.
    """
    expected_prev = GENESIS_HASH
    checked = 0
    for row in rows:
        checked += 1
        recomputed = compute_hash(
            prev_hash=row["prev_hash"],
            event_id=row["event_id"],
            operator_id=row["operator_id"],
            action=row["action_taken"],
            reason=row["reason"],
            details=row["details"],
            logged_at=row["logged_at"],
        )
        if row["prev_hash"] != expected_prev or row["sha256_hash"] != recomputed:
            return {"valid": False, "checked": checked, "broken_at_seq": row["seq"]}
        expected_prev = row["sha256_hash"]
    return {"valid": True, "checked": checked, "broken_at_seq": None}


AUDIT_ROW_COLUMNS = """
    seq, id, event_id, operator_id, action_taken, reason, details,
    logged_at, prev_hash, sha256_hash
"""


def row_to_dict(row: Any) -> Dict[str, Any]:
    m = row._mapping
    return {
        "seq": m["seq"],
        "id": str(m["id"]),
        "event_id": str(m["event_id"]) if m["event_id"] is not None else None,
        "operator_id": m["operator_id"],
        "action_taken": str(getattr(m["action_taken"], "value", m["action_taken"])),
        "reason": m["reason"],
        "details": m["details"],
        "logged_at": m["logged_at"],
        "prev_hash": m["prev_hash"],
        "sha256_hash": m["sha256_hash"],
    }


async def fetch_rows(db: AsyncSession, event_id: Optional[Any] = None):
    """Audit rows in chain order — all of them, or one event's."""
    if event_id is None:
        result = await db.execute(
            text(f"SELECT {AUDIT_ROW_COLUMNS} FROM audit_logs ORDER BY seq")
        )
    else:
        result = await db.execute(
            text(f"""
                SELECT {AUDIT_ROW_COLUMNS} FROM audit_logs
                WHERE event_id = CAST(:e AS uuid) ORDER BY seq
            """),
            {"e": str(event_id)},
        )
    return [row_to_dict(r) for r in result.fetchall()]


async def verify_chain(db: AsyncSession) -> Dict[str, Any]:
    """Verify the whole ledger from genesis."""
    return verify_rows(await fetch_rows(db))
