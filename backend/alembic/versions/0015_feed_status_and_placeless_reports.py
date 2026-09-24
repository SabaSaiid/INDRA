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

**Part 2 (T4, T6): reports without a place.** The PS asks for every weather
post to be collected, and most posts name no point: "#IMD orange alert for
Kerala" is a state, "Rain again" is nowhere. `raw_reports.latitude` and
`longitude` were NOT NULL, so such a post could not be stored at all. They are
nullable now; the range checks still pass on NULL, because a CHECK is only
violated by a false result and a comparison with NULL is unknown.

`place_precision` says how much a report's position is worth:

* `gps` — the device's own coordinates: citizen reports, official dispatches.
  Every existing row is backfilled to `gps`, the only kind there has been.
* `district` — a post naming one district (or several close together),
  placed at its centroid by `geocoding.place_from_text`.
* `state` — a post naming only a state. Coordinates are the state's centroid,
  kept for filtering; no `geom_point`, so it is never clustered or deduplicated
  on distance.
* `none` — nothing recognisable. NULL coordinates.

**Part 3 (T10): `DATA_EXPORT`.** `audit_action_enum` gains the action every
CSV or GeoJSON export writes to the ledger, with its filters in `details`, so
the hash chain proves who exported what as well as who decided what. Added
inside the transaction as 0011 added its values; nothing in this run writes it.
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

    # ── Part 2 (T4, T6): reports without a place ─────────────────────────────
    op.alter_column("raw_reports", "latitude", existing_type=sa.Float, nullable=True)
    op.alter_column("raw_reports", "longitude", existing_type=sa.Float, nullable=True)
    op.add_column("raw_reports", sa.Column("place_precision", sa.String(10), nullable=True))
    op.execute("UPDATE raw_reports SET place_precision = 'gps' WHERE place_precision IS NULL")
    op.create_check_constraint(
        "ck_raw_reports_place_precision",
        "raw_reports",
        "place_precision IN ('gps', 'district', 'state', 'none')",
    )
    # A report has coordinates exactly when it has a place to put them.
    op.create_check_constraint(
        "ck_raw_reports_coordinates_pair",
        "raw_reports",
        "(latitude IS NULL) = (longitude IS NULL)",
    )

    # ── Part 3 (T10): the export audit action ────────────────────────────────
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'DATA_EXPORT'")


def downgrade() -> None:
    # Part 3: DATA_EXPORT stays in audit_action_enum (Postgres has no DROP
    # VALUE), and the ledger rows that use it must stay too: the chain is
    # append-only.

    # Part 2. Rows without coordinates cannot survive NOT NULL; they are the
    # posts this migration made storable, so they go with it.
    op.drop_constraint("ck_raw_reports_coordinates_pair", "raw_reports", type_="check")
    op.drop_constraint("ck_raw_reports_place_precision", "raw_reports", type_="check")
    op.drop_column("raw_reports", "place_precision")
    op.execute(
        "UPDATE raw_reports SET duplicate_of = NULL WHERE duplicate_of IN "
        "(SELECT id FROM raw_reports WHERE latitude IS NULL)"
    )
    op.execute(
        "DELETE FROM outbox WHERE key IN "
        "(SELECT CAST(id AS text) FROM raw_reports WHERE latitude IS NULL)"
    )
    op.execute("DELETE FROM raw_reports WHERE latitude IS NULL OR longitude IS NULL")
    op.alter_column("raw_reports", "longitude", existing_type=sa.Float, nullable=False)
    op.alter_column("raw_reports", "latitude", existing_type=sa.Float, nullable=False)

    # Part 1.
    op.drop_table("feed_status")
