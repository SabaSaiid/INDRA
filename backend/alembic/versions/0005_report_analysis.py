"""Store what layer 3 extracted from each report

Revision ID: 0005_report_analysis
Revises: 0004_report_duplicate_of
Create Date: 2026-09-20

`services/text_processing.py` shipped on 19 Sep and nothing imported it: its
intended consumer was the NLP task cancelled when layer 4 left the scope. The
extraction itself is useful on its own — it is regex and dictionaries, not a
model — so this column gives it somewhere to live.

* raw_reports.analysis  JSONB NULL, written once at ingest by api/reports.py:
  {cleaned_text, language, depth_cm, depth_basis, keywords, places, url_count,
   phone_count, extracted_at}.

NULL is a meaningful value here, not just an absence. Analysis is best-effort and
must never fail an ingest: if the extractor raises, the report is still stored
with analysis NULL and a WARNING is logged. A disaster report is not worth losing
to a regex.

Deliberately **not** the input to content severity. `pipeline.py` re-extracts
depth from raw_text at scoring time instead of reading this column, so that a
NULL here — a failed extraction, or a row written before this migration — cannot
silently downgrade an event's severity to corroboration-count-only. This column
is for the API, the dashboard and auditability.

No backfill: rows ingested before this migration keep analysis NULL, and the demo
starts from an empty database. A backfill would also have to pick an extractor
version to attribute the values to, which is a question worth answering properly
rather than in a migration.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_report_analysis"
down_revision: Union[str, None] = "0004_report_duplicate_of"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw_reports ADD COLUMN analysis JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE raw_reports DROP COLUMN IF EXISTS analysis")
