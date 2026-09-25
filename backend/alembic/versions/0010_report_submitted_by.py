"""Who submitted a report through an authenticated route

Revision ID: 0010_report_submitted_by
Revises: 0009_event_location
Create Date: 2026-09-22

**BUG-025.** Source reliability is the highest-weighted input a report can
bring — an `OFFICIAL_DISPATCH` scores 1.00 against a citizen's 0.60 — and until
now nothing could set it: `POST /api/reports/submit` stamps every report
`CITIZEN_APP`, correctly, because letting an anonymous client name its own
source would make the factor measure what a reporter claims to be.

The fix is an authenticated route for trusted sources, and a trusted input is
only worth as much as the record of who supplied it. `submitted_by` holds the
token subject of the operator who filed the report through that route. It is
NULL for citizen reports, which stay anonymous by design, so "nobody vouched
for this" and "this operator vouched for it" are distinguishable in the data
rather than in a log line.

Nullable, no backfill: every existing row came through the anonymous route or
the synthetic seeder, and NULL is the true value for both.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_report_submitted_by"
down_revision = "0009_event_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_reports", sa.Column("submitted_by", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_reports", "submitted_by")
