"""Verification v2: verdicts, review claims, event snapshots, late corroboration

Revision ID: 0020_verification_v2
Revises: 0019_operator_password_hash
Create Date: 2026-09-27

**Phase 4 T4, T5, T7.** The plan calls this `0018_verification_v2`; 0018 and
0019 went to the operator-password work (PR #46) first, so it is 0020.

`verified_events` gains:

* `verdict` — `verdict_enum`: CORROBORATED, CONTRADICTED or UNCONFIRMED
  (T4). NULL for an event scored before receipt v2, until
  `scripts/rescore_events.py` re-scores it; never NULL for one scored since.
* `claimed_by`, `claimed_at` — the review claim (T7): who is reviewing the
  event, since when. A claim expires 15 minutes after `claimed_at`; nothing
  clears it on expiry, the readers compare the time.

`event_snapshots` (T7) — one row every time an event's score is written: at
creation, at every merge, at every late re-score. The dashboard's "confidence
over time" and the status history come from it. `verdict` and `review_status`
are text, not the enums, so a history row never fails on a value a later
migration adds. `trigger` says what caused the write (`created`, `merge`,
`late:sachet:…`, `late:metar:…`, `rescore`).

`audit_action_enum` gains `LATE_CORROBORATION` (T5): an event re-scored because
evidence arrived after it, with `{trigger, before, after}` in its details.
Added inside the transaction as 0011 and 0016 did; nothing in this run writes
the new value.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020_verification_v2"
down_revision = "0019_operator_password_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE verdict_enum AS ENUM ('CORROBORATED', 'CONTRADICTED', 'UNCONFIRMED')"
    )
    op.add_column(
        "verified_events",
        sa.Column(
            "verdict",
            sa.Enum("CORROBORATED", "CONTRADICTED", "UNCONFIRMED", name="verdict_enum",
                    create_type=False),
            nullable=True,
        ),
    )
    op.add_column("verified_events", sa.Column("claimed_by", sa.String(50), nullable=True))
    op.add_column(
        "verified_events", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_events_verdict", "verified_events", ["verdict"])
    op.create_index("ix_events_claimed_at", "verified_events", ["claimed_at"])

    op.create_table(
        "event_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verified_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("factor_coverage", sa.Float, nullable=True),
        sa.Column("report_count", sa.Integer, nullable=True),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("trigger", sa.String(160), nullable=False),
        sa.Column("receipt_version", sa.Integer, nullable=True),
        sa.Column("details", JSONB, nullable=True),
    )
    op.create_index("ix_event_snapshots_event_at", "event_snapshots", ["event_id", "at"])

    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'LATE_CORROBORATION'")


def downgrade() -> None:
    op.drop_index("ix_event_snapshots_event_at", table_name="event_snapshots")
    op.drop_table("event_snapshots")
    op.drop_index("ix_events_claimed_at", table_name="verified_events")
    op.drop_index("ix_events_verdict", table_name="verified_events")
    op.drop_column("verified_events", "claimed_at")
    op.drop_column("verified_events", "claimed_by")
    op.drop_column("verified_events", "verdict")
    op.execute("DROP TYPE IF EXISTS verdict_enum")
    # LATE_CORROBORATION stays in audit_action_enum: Postgres has no DROP VALUE,
    # and the ledger's rows that carry it can never be deleted anyway.
