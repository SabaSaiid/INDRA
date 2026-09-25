"""Indexes for the event filters, and the report-to-event link

Revision ID: 0014_event_filter_indexes
Revises: 0013_outbox
Create Date: 2026-09-23

**Phase 1 T5.** `GET /api/events` gains the PS's date, event, location and
status filters. The existing `(review_status, severity)` index covers the
status filter; these cover the rest:

* `verified_at` — every date filter, and the default newest-first order.
* `(lower(state), lower(district))` — the location filter matches regardless of
  case (`?state=bihar`), so the index is on the lowered values; a plain
  `(state, district)` index could not serve `lower(state) = lower(:state)`.
* `event_type` — the event and family filters.
* `raw_reports.event_id` — never indexed since 0001, although it is the only
  link from a report to its event. The `source_type` filter's EXISTS, the
  docket lookup's join and the pipeline's own `COUNT(*) … WHERE event_id = …`
  all scanned the table without it.
"""

from alembic import op

revision = "0014_event_filter_indexes"
down_revision = "0013_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_events_verified_at", "verified_events", ["verified_at"])
    op.execute(
        "CREATE INDEX ix_events_state_district_lower "
        "ON verified_events (lower(state), lower(district))"
    )
    op.create_index("ix_events_event_type", "verified_events", ["event_type"])
    op.create_index("ix_raw_reports_event_id", "raw_reports", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_reports_event_id", table_name="raw_reports")
    op.drop_index("ix_events_event_type", table_name="verified_events")
    op.execute("DROP INDEX IF EXISTS ix_events_state_district_lower")
    op.drop_index("ix_events_verified_at", table_name="verified_events")
