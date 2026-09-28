"""Reporter reputation: per-reporter counts and the human decisions behind them

Revision ID: 0022_reporter_stats
Revises: 0021_report_media
Create Date: 2026-09-28

**Phase 5 T6.** The plan calls this `0020_reporter_stats`; 0020 went to Phase 4.

`reporter_stats` — one row per reporter pseudonym (`reporter_hash`: the keyed
hash of a device's random id, or of a social account; never the id itself):
how many reports, how many of its events a commander approved or rejected,
how many of its reports carried a flag that lowered their credibility, and
when it was first and last seen. `source_type` and `platform` are those of its
first report.

`reporter_decisions` — the human decisions the counts are made from: one row
per (reporter, event), holding the event's latest decision. `approved` and
`rejected` are recounted from it on every decision, so an event approved and
later rejected counts once, as rejected, and deciding the same event twice
counts once. Only human decisions are recorded: machine credibility is not
ground truth, and an auto-published event changes nobody's record.

**Backfilled from what is already stored:** every reporter's reports, flags
and first/last time, and a decision for each reporter of every event that is
HUMAN_APPROVED or REJECTED today.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0022_reporter_stats"
down_revision = "0021_report_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reporter_stats",
        sa.Column("reporter_hash", sa.String(64), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("reports", sa.Integer, nullable=False, server_default="0"),
        sa.Column("approved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reporter_stats_reports", "reporter_stats", ["reports"])

    op.create_table(
        "reporter_decisions",
        sa.Column("reporter_hash", sa.String(64), primary_key=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verified_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_reporter_decision"),
    )

    # A report whose credibility a flag lowered. The media and account flags
    # (0021, Phase 5) are not in any stored row yet; the text flags are.
    penalising = (
        "ARRAY['promotional','past_event','implausible_value','exaggeration','shouting',"
        "'forward_marker','coordinated']"
    )
    op.execute(f"""
        INSERT INTO reporter_stats
            (reporter_hash, source_type, platform, reports, flagged, first_seen, last_seen)
        SELECT reporter_hash,
               (array_agg(CAST(source_type AS text) ORDER BY created_at))[1],
               (array_agg(platform ORDER BY created_at))[1],
               count(*),
               count(*) FILTER (WHERE COALESCE(flags, '{{}}'::text[]) && {penalising}),
               min(created_at),
               max(created_at)
        FROM raw_reports
        WHERE reporter_hash IS NOT NULL
        GROUP BY reporter_hash
    """)
    op.execute("""
        INSERT INTO reporter_decisions (reporter_hash, event_id, decision)
        SELECT DISTINCT r.reporter_hash, e.id,
               CASE WHEN CAST(e.review_status AS text) = 'HUMAN_APPROVED' THEN 'approved' ELSE 'rejected' END
        FROM verified_events e
        JOIN raw_reports r ON r.event_id = e.id
        WHERE CAST(e.review_status AS text) IN ('HUMAN_APPROVED', 'REJECTED')
          AND r.reporter_hash IS NOT NULL
          AND r.duplicate_of IS NULL
    """)
    op.execute("""
        UPDATE reporter_stats s SET
            approved = d.approved,
            rejected = d.rejected
        FROM (
            SELECT reporter_hash,
                   count(*) FILTER (WHERE decision = 'approved') AS approved,
                   count(*) FILTER (WHERE decision = 'rejected') AS rejected
            FROM reporter_decisions
            GROUP BY reporter_hash
        ) d
        WHERE d.reporter_hash = s.reporter_hash
    """)


def downgrade() -> None:
    op.drop_table("reporter_decisions")
    op.drop_index("ix_reporter_stats_reports", table_name="reporter_stats")
    op.drop_table("reporter_stats")
