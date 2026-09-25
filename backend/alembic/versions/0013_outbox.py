"""The outbox: a report and its Kafka message are committed together

Revision ID: 0013_outbox
Revises: 0012_report_intake_fields
Create Date: 2026-09-23

**BUG-060.** Ingest committed the report, then tried once to publish it to
Kafka. With Redpanda down the citizen got 202 `queued: false`, the row sat in
`raw_reports`, and nothing ever published it again: never deduplicated,
clustered or scored. A report accepted is a report that must be processed.

The fix is the transactional-outbox pattern. The message is written to this
table **in the same transaction** as the report, so either both exist or
neither does. The request then tries to publish it straight away, and a relay
(`app/workers/outbox_relay.py`) publishes whatever is still unpublished, as
often as it takes. Nothing is ever lost between "stored" and "published".

* `published_at` is NULL until a publish succeeds. The partial index covers
  exactly the rows the relay scans, so it stays small however long the table
  gets.
* `attempts` and `last_error` record why a row is still waiting, for the
  operator reading `/healthz` during an outage.
* Rows are never deleted by the relay. Published rows older than 7 days are
  pruned by the relay's daily cleanup.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013_outbox"
down_revision = "0012_report_intake_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.execute("CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_outbox_unpublished")
    op.drop_table("outbox")
