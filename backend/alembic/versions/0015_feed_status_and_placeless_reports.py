"""Feed heartbeats, reports without a place, and the export audit action

Revision ID: 0015_feed_status_and_placeless_reports
Revises: 0014_event_filter_indexes
Create Date: 2026-09-24

**Phase 2, in three parts.**

**Part 1 (T2): `feed_status`.** One row per feed INDRA polls, written by the
poller at the end of every tick through `services/feed_status.record_tick()`.
Until now `GET /api/meta/sources` could only guess whether a poller was alive
from the newest row it had written, so a poller that ran and found nothing new
looked exactly like one that had died, and no error was ever recorded. The row
holds:

* `last_attempt_at`, `last_success_at`, `last_error_at`, `last_error` — the
  tick's outcome, so "failing" and "quiet" are finally different answers;
* `consecutive_failures` — reset by a success; three in a row is `failing`;
* `items_last_tick`, `rows_total` — what the last tick wrote, and the running
  total the poller has written;
* `cursor` — the poller's resume point (Mastodon's `since_id` per tag, a
  feed's `Last-Modified`), so a restart does not refetch everything;
* `kind`, `enabled` — as last reported by the poller.

Push feeds (citizen and official reports) have no row: they have no tick.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_feed_status_and_placeless_reports"
down_revision = "0014_event_filter_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Part 1 (T2): feed heartbeats ─────────────────────────────────────────
    op.create_table(
        "feed_status",
        sa.Column("feed", sa.String(40), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_last_tick", sa.Integer, nullable=True),
        sa.Column("rows_total", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("cursor", JSONB, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("feed_status")
