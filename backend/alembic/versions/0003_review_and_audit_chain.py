"""Human review status, human audit actions, and a verifiable audit hash chain

Revision ID: 0003_review_and_audit_chain
Revises: 0002_teams_and_profiles
Create Date: 2026-09-18

* review_status_enum gains HUMAN_APPROVED. Approving to AUTO_PUBLISHED would
  record that a machine published the event, which would be false.
* audit_action_enum gains HUMAN_APPROVE and HUMAN_REJECT. MANUAL_OVERRIDE stays,
  for severity overrides.
* audit_logs gains:
    - seq        BIGSERIAL, unique: the chain order. logged_at alone can tie.
    - prev_hash  VARCHAR(64): the predecessor's sha256_hash, so every row can be
                 checked against the one before it.
    - details    JSONB: the structured record (from/to status, score, severity).
  ADD COLUMN is DDL, not a row UPDATE, so trg_audit_immutable does not fire.

Enum values are added with IF NOT EXISTS and are never *used* in this migration:
Postgres 16 allows ADD VALUE inside a transaction, but a new value cannot be
used in the same transaction that added it.

Downgrade: Postgres cannot drop enum values. The downgrade drops the three
columns and deliberately leaves HUMAN_APPROVED / HUMAN_APPROVE / HUMAN_REJECT in
place; re-running the upgrade is safe because of IF NOT EXISTS.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0003_review_and_audit_chain"
down_revision: Union[str, None] = "0002_teams_and_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE review_status_enum ADD VALUE IF NOT EXISTS 'HUMAN_APPROVED'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'HUMAN_APPROVE'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'HUMAN_REJECT'")

    op.execute("ALTER TABLE audit_logs ADD COLUMN seq BIGSERIAL NOT NULL")
    op.execute("ALTER TABLE audit_logs ADD CONSTRAINT uq_audit_logs_seq UNIQUE (seq)")
    op.execute("ALTER TABLE audit_logs ADD COLUMN prev_hash VARCHAR(64)")
    op.execute("ALTER TABLE audit_logs ADD COLUMN details JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS details")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS prev_hash")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS uq_audit_logs_seq")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS seq")
    # Enum values HUMAN_APPROVED, HUMAN_APPROVE, HUMAN_REJECT are intentionally
    # left in place — Postgres has no ALTER TYPE ... DROP VALUE.
