"""Record which report a suppressed duplicate duplicates

Revision ID: 0004_report_duplicate_of
Revises: 0003_review_and_audit_chain
Create Date: 2026-09-17

Before this, a suppressed duplicate was only *not acted on*: it stayed in
raw_reports with event_id NULL, so the next DBSCAN run over unassigned reports
pulled it into a cluster and counted it as corroboration (Day 3 live run:
6 reports, report_count 7).

* raw_reports.duplicate_of  UUID NULL, FK to raw_reports(id). Set by the
  pipeline when it suppresses a report; always points at the original, never
  at another duplicate.
* ix_raw_reports_clusterable  partial index over the rows clustering reads:
  WHERE event_id IS NULL AND duplicate_of IS NULL.

No backfill: rows suppressed before this migration have no record of what they
duplicated. The demo starts from an empty database.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0004_report_duplicate_of"
down_revision: Union[str, None] = "0003_review_and_audit_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE raw_reports
        ADD COLUMN duplicate_of UUID NULL
            CONSTRAINT fk_raw_reports_duplicate_of REFERENCES raw_reports(id)
    """)
    op.execute("""
        CREATE INDEX ix_raw_reports_clusterable
        ON raw_reports USING gist (geom_point)
        WHERE event_id IS NULL AND duplicate_of IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_raw_reports_clusterable")
    op.execute("ALTER TABLE raw_reports DROP COLUMN IF EXISTS duplicate_of")
