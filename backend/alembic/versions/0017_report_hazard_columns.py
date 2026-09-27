"""Hazard and flag columns on reports; hazard family on events

Revision ID: 0017_report_hazard_columns
Revises: 0016_station_observations
Create Date: 2026-09-25

**Phase 3 T4.** The hazard tagger (`services/hazard_tagger.py`) says which
hazards a report describes; clustering (T5) and typing (T6) need that as a
column they can filter on, not a key inside a JSON blob.

`raw_reports` gains:

* `hazard_primary` — the hazard the report is about, by the taxonomy's
  precedence (`services/hazards.py`); NULL when its text names none.
* `hazard_family` — `water`, `convective`, `thermal` or `visibility`: which
  reports it may cluster with (T5). NULL when untagged; an untagged report
  joins any family's candidates.
* `flags` — the misleading-text flags (T8): `promotional`, `past_event`,
  `not_an_observation`, `implausible_value`, `exaggeration`, `shouting`,
  `forward_marker`, `coordinated`. Empty, never NULL, for a clean report.

`analysis.hazards` keeps the full detail: every hazard, what matched, and the
basis. `place_precision` already exists (0015).

`verified_events` gains `hazard_family`, backfilled from `event_type` below.

Indexes: `(hazard_family, COALESCE(observed_at, created_at))` for T5's
candidate query, which filters on exactly that, and a GIN index on `flags` for
the search's `?flag=`.

**Not backfilled here:** the report columns need the tagger, which is
application code a migration should not import. `scripts/backfill_hazards.py`
fills them over every stored row, idempotently.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0017_report_hazard_columns"
down_revision = "0016_station_observations"
branch_labels = None
depends_on = None

# The families of services/hazards.py, copied rather than imported: a
# migration must mean the same thing whatever the code later says.
_FAMILY_OF = {
    "water": ("URBAN_FLOOD", "CLOUDBURST", "CYCLONE_INUNDATION", "RIVER_BREACH", "LANDSLIDE", "RAINFALL"),
    "convective": ("CYCLONE", "DUST_STORM", "THUNDERSTORM", "LIGHTNING", "HAILSTORM", "STRONG_WIND"),
    "thermal": ("HEATWAVE", "COLD_WAVE"),
    "visibility": ("FOG",),
}


def upgrade() -> None:
    op.add_column("raw_reports", sa.Column("hazard_primary", sa.String(32), nullable=True))
    op.add_column("raw_reports", sa.Column("hazard_family", sa.String(16), nullable=True))
    op.add_column(
        "raw_reports",
        sa.Column("flags", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
    )
    op.add_column("verified_events", sa.Column("hazard_family", sa.String(16), nullable=True))

    cases = " ".join(
        f"WHEN CAST(event_type AS text) IN ({', '.join(repr(t) for t in types)}) THEN '{family}'"
        for family, types in _FAMILY_OF.items()
    )
    op.execute(f"UPDATE verified_events SET hazard_family = CASE {cases} ELSE NULL END")

    op.execute(
        "CREATE INDEX ix_raw_reports_family_observed "
        "ON raw_reports (hazard_family, (COALESCE(observed_at, created_at)))"
    )
    op.create_index("ix_raw_reports_flags", "raw_reports", ["flags"], postgresql_using="gin")
    op.create_index("ix_events_hazard_family", "verified_events", ["hazard_family"])


def downgrade() -> None:
    op.drop_index("ix_events_hazard_family", table_name="verified_events")
    op.drop_index("ix_raw_reports_flags", table_name="raw_reports")
    op.execute("DROP INDEX IF EXISTS ix_raw_reports_family_observed")
    op.drop_column("verified_events", "hazard_family")
    op.drop_column("raw_reports", "flags")
    op.drop_column("raw_reports", "hazard_family")
    op.drop_column("raw_reports", "hazard_primary")
