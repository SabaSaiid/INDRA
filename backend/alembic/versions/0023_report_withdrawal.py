"""A citizen can take their report back: raw_reports.withdrawn_at

Revision ID: 0023_report_withdrawal
Revises: 0022_reporter_stats
Create Date: 2026-09-28

**Phase 5 T5 step 4.** `DELETE /api/reports/{docket}`, from the device that
filed the report, redacts its text and exact position, deletes its media,
takes it out of its event and re-scores the event. The row stays as a
tombstone — docket, time received, district and state — so the docket still
answers "withdrawn" and the ledger rows that name it still resolve.

* `raw_reports.withdrawn_at` — when; NULL for every report not withdrawn.
* `audit_action_enum` gains `REPORT_WITHDRAWN`: the withdrawal, with the
  report, the event it left and how many files were deleted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_report_withdrawal"
down_revision = "0022_reporter_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_reports", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'REPORT_WITHDRAWN'")


def downgrade() -> None:
    op.drop_column("raw_reports", "withdrawn_at")
    # REPORT_WITHDRAWN stays in audit_action_enum: Postgres has no DROP VALUE.
