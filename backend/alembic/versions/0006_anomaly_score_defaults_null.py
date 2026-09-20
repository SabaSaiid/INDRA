"""An uncomputed anomaly score is NULL, not 0.0

Revision ID: 0006_anomaly_score_defaults_null
Revises: 0005_report_analysis
Create Date: 2026-09-21

`station_readings.anomaly_score` has carried `server_default '0.0'` since 0001,
from a design in which layer 4 would fill it. Layer 4 left the scope on 20 Sep
and anomaly detection is now permanently offline, so every row the Day 6 station
poller writes would claim a computed, perfectly normal anomaly score for a model
that does not run.

That is the same class of defect as a fabricated telemetry number: the column is
nullable and NULL is the honest value, but a default meant nobody could ever
write one. Dropping the default is the whole change — no data is touched, because
the table has never held a row outside a test.

The receipt is unaffected: `anomaly_detection` is scored from
`fusion_engine.compute_receipt(anomaly_score=None)` and has always been reported
`offline` there. This only stops the *table* from disagreeing with the receipt.

Downgrade restores the default. It does not rewrite existing NULLs to 0.0 — a
downgrade should undo a schema decision, not invent measurements.
"""

from alembic import op

revision = "0006_anomaly_score_defaults_null"
down_revision = "0005_report_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE station_readings ALTER COLUMN anomaly_score DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE station_readings ALTER COLUMN anomaly_score SET DEFAULT 0.0")
