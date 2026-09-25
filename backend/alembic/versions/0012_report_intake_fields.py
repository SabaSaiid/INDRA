"""When it happened, who sent it, what they think it is, and whether it was processed

Revision ID: 0012_report_intake_fields
Revises: 0011_hazard_and_source_enums
Create Date: 2026-09-23

**Phase 1 T2 (and T4's `processed_at`).** Eight nullable columns on
`raw_reports`:

* `observed_at` — when the thing happened, as opposed to `created_at`, when
  INDRA received it. A citizen can report a flood an hour after wading through
  it; a news item describes the morning. Indexed, because Phase 3 clusters on it.
* `reporter_hash` — HMAC-SHA256 of the client's random id, keyed with
  `REPORTER_SALT`. The raw id is never stored. NULL means "unknown", never a
  shared identity.
* `docket` — the citizen's tracking number, `R-` and 8 Crockford base32
  characters. Random, so nobody can walk through other people's reports.
* `platform`, `external_id` — where a fed item came from (`mastodon`,
  `google_news`, …) and its id there: the post's URI or the item's GUID. Unique
  together, so a poller that sees the same post twice stores it once (Phase 2).
* `source_meta` — publisher, author hash, hashtags, URL (Phase 2).
* `citizen_hazard` — the category the citizen picked, if any: what they *think*
  it is, kept apart from the event type the platform assigns.
* `processed_at` — when the pipeline finished with the report. Without it, a
  report that was processed and found alone cannot be told apart from one that
  was never processed at all, and the docket could not say which.

`observed_at` is backfilled from `created_at`: for every existing row the time
it was received is the best record there is of when it happened. `processed_at`
is not backfilled — whether an old report was ever processed is exactly what
nothing recorded (BUG-060), and a guess would make the docket lie.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_report_intake_fields"
down_revision = "0011_hazard_and_source_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_reports", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("raw_reports", sa.Column("reporter_hash", sa.String(64), nullable=True))
    op.add_column("raw_reports", sa.Column("docket", sa.String(16), nullable=True))
    op.add_column("raw_reports", sa.Column("platform", sa.String(32), nullable=True))
    op.add_column("raw_reports", sa.Column("external_id", sa.String(512), nullable=True))
    op.add_column("raw_reports", sa.Column("source_meta", JSONB, nullable=True))
    op.add_column("raw_reports", sa.Column("citizen_hazard", sa.String(32), nullable=True))
    op.add_column("raw_reports", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_raw_reports_observed_at", "raw_reports", ["observed_at"])
    op.create_unique_constraint("uq_raw_reports_docket", "raw_reports", ["docket"])
    # Partial: only fed items carry an external id, and many rows share NULL.
    op.execute(
        "CREATE UNIQUE INDEX uq_raw_reports_platform_external_id "
        "ON raw_reports (platform, external_id) WHERE external_id IS NOT NULL"
    )

    op.execute("UPDATE raw_reports SET observed_at = created_at WHERE observed_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_raw_reports_platform_external_id")
    op.drop_constraint("uq_raw_reports_docket", "raw_reports", type_="unique")
    op.drop_index("ix_raw_reports_observed_at", table_name="raw_reports")
    for column in (
        "processed_at",
        "citizen_hazard",
        "source_meta",
        "external_id",
        "platform",
        "docket",
        "reporter_hash",
        "observed_at",
    ):
        op.drop_column("raw_reports", column)
