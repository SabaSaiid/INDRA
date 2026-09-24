"""Airport weather observations in station_readings

Revision ID: 0016_station_observations
Revises: 0015_feed_status_placeless
Create Date: 2026-09-24

**Phase 2 T3.** `station_readings` held one kind of row: Open-Meteo's modelled
24 h rainfall at six city points. The METAR poller adds real observations from
Indian aerodromes, which measure different things, so the table gains:

* `feed` — which poller wrote the row (`open_meteo`, `metar`). Backfilled to
  `open_meteo` for every existing row, the only feed that ever wrote one.
* `temperature_c`, `dewpoint_c` — °C.
* `wind_kmh`, `gust_kmh` — METARs report knots; stored × 1.852.
* `visibility_m` — metres. Indian METARs report a 4-digit metric group
  (`3500`); `9999` and `CAVOK` are stored as 10,000 ("10 km or more").
* `weather_codes` — present weather, normalised: `+TSRA` → `{TS, RA+}`.
* `convective_cloud` — a CB or TCU group was reported.
* `raw_observation` — the METAR exactly as transmitted, so every parsed number
  can be checked against its source.

`rainfall_mm` stays NULL on METAR rows: a METAR carries no rainfall amount, and
the weather factor already skips a row whose rainfall is NULL.

**The unique index is partial, `WHERE feed = 'metar'`.** One observation is one
row, so a station re-sent in the next tick's file is stored once. The
Open-Meteo rows cannot take the same constraint: that poller stores each
observation hour several times by design (every 10 minutes against hourly
data, which `GET /api/geo/stations` already folds), so a table-wide
`UNIQUE(station_code, recorded_at)` would fail on existing data.

`agency_enum` gains `AERODROME_METAR`, not `IMD`: civil aerodrome observations
in India are made by IMD, but some Indian METAR stations are military airfields,
and INDRA receives all of them through the international exchange that NOAA's
Aviation Weather Center republishes. Added inside the transaction as 0011 did;
nothing in this run writes the new value.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0016_station_observations"
down_revision = "0015_feed_status_placeless"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE agency_enum ADD VALUE IF NOT EXISTS 'AERODROME_METAR'")

    op.add_column("station_readings", sa.Column("feed", sa.String(20), nullable=True))
    op.add_column("station_readings", sa.Column("temperature_c", sa.Float, nullable=True))
    op.add_column("station_readings", sa.Column("dewpoint_c", sa.Float, nullable=True))
    op.add_column("station_readings", sa.Column("wind_kmh", sa.Float, nullable=True))
    op.add_column("station_readings", sa.Column("gust_kmh", sa.Float, nullable=True))
    op.add_column("station_readings", sa.Column("visibility_m", sa.Integer, nullable=True))
    op.add_column("station_readings", sa.Column("weather_codes", ARRAY(sa.Text), nullable=True))
    op.add_column("station_readings", sa.Column("convective_cloud", sa.Boolean, nullable=True))
    op.add_column("station_readings", sa.Column("raw_observation", sa.Text, nullable=True))

    op.execute(
        "UPDATE station_readings SET feed = 'open_meteo' "
        "WHERE feed IS NULL AND CAST(agency AS text) = 'OPEN_METEO'"
    )

    op.execute(
        "CREATE UNIQUE INDEX uq_station_readings_metar_obs "
        "ON station_readings (station_code, recorded_at) WHERE feed = 'metar'"
    )
    # Every "latest reading per station of one feed" query, and rows_24h per feed.
    op.create_index(
        "ix_station_readings_feed_recorded_at", "station_readings", ["feed", "recorded_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_station_readings_feed_recorded_at", table_name="station_readings")
    op.execute("DROP INDEX IF EXISTS uq_station_readings_metar_obs")
    for column in (
        "raw_observation",
        "convective_cloud",
        "weather_codes",
        "visibility_m",
        "gust_kmh",
        "wind_kmh",
        "dewpoint_c",
        "temperature_c",
        "feed",
    ):
        op.drop_column("station_readings", column)
    # AERODROME_METAR stays in agency_enum: Postgres has no DROP VALUE.
