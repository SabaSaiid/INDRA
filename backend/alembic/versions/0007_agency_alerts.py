"""Official agency warnings from the SACHET (NDMA) national alert feed

Revision ID: 0007_agency_alerts
Revises: 0006_anomaly_score_defaults_null
Create Date: 2026-09-21

Layer 1 has had exactly one scheduled feed since Day 6 — Open-Meteo rainfall, a
raw measurement INDRA scores itself. `agency_alerts` is the first table holding a
judgement made by somebody else: IMD, CWC or a state SDMA issued a warning, gave
it a severity, and NDMA published it.

That matters for the confidence receipt. Until now every factor was computed from
the reports INDRA received, so a cluster of citizen reports could only ever
corroborate itself. An IMD warning covering the same place and time is genuinely
independent evidence.

Design notes worth keeping:

* `identifier` is unique. The feed republishes an alert as a CAP "Update" under
  the same identifier, so a re-poll must update in place; without the constraint
  each poll would append 99 more rows and every corroboration count would climb
  on its own.
* `severity` is nullable because CAP allows `Unknown`, and `raw_severity` keeps
  the agency's own word. Mapping `Unknown` onto ADVISORY would manufacture a
  judgement the issuer declined to make.
* `feed_published_at` is the RSS `pubDate`, stored beside the CAP `sent`. The
  two disagree — one real alert said 02:24 UTC in its CAP document and 02:28 in
  the feed — so comparing them to decide "has this been republished?" marks every
  alert stale on every tick and refetches the whole feed forever.
* `sender` is free text, not the `Agency` enum — the live feed distinguishes
  `IMD Ahmedabad` from `IMD Mumbai` from `Gujarat-SDMA`, and the enum has three
  values. Recording the issuing office verbatim is the point.
* `area_polygon` is nullable. Some alerts carry only LGD district codes, and an
  invented bounding box would be a footprint no agency drew.

Downgrade drops the table. No other table references it: corroboration is
computed by spatial join at scoring time, deliberately not stored as a foreign
key, so an event's receipt never depends on this table still existing.
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_agency_alerts"
down_revision = "0006_anomaly_score_defaults_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agency_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("identifier", sa.String(length=128), nullable=False),
        sa.Column("source_feed", sa.String(length=32), nullable=False, server_default="SACHET"),
        sa.Column("sender", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("msg_type", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("event", sa.String(length=160), nullable=True),
        sa.Column("urgency", sa.String(length=32), nullable=True),
        # The severity_enum type already exists from 0001 (verified_events).
        # create_type=False stops Alembic trying to CREATE TYPE a second time,
        # which fails the whole migration.
        sa.Column(
            "severity",
            postgresql.ENUM(
                "ADVISORY", "MODERATE", "HIGH", "CRITICAL",
                name="severity_enum",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("raw_severity", sa.String(length=32), nullable=True),
        sa.Column("certainty", sa.String(length=32), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feed_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("area_desc", sa.Text(), nullable=True),
        sa.Column("district_codes", postgresql.ARRAY(sa.String(length=16)), nullable=True),
        sa.Column(
            "area_polygon",
            geoalchemy2.types.Geometry(geometry_type="POLYGON", srid=4326),
            nullable=True,
        ),
        sa.Column("polygon_thinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("polygon_points", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("identifier", name="uq_agency_alerts_identifier"),
    )
    op.create_index("ix_agency_alerts_identifier", "agency_alerts", ["identifier"])
    op.create_index("ix_agency_alerts_expires_at", "agency_alerts", ["expires_at"])
    # GiST on the footprint: corroboration is an ST_Contains/ST_DWithin lookup
    # per event, so this index is the difference between a scan of every live
    # warning in India and a bounded probe.
    op.create_index(
        "ix_agency_alerts_area_gist",
        "agency_alerts",
        ["area_polygon"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_agency_alerts_area_gist", table_name="agency_alerts")
    op.drop_index("ix_agency_alerts_expires_at", table_name="agency_alerts")
    op.drop_index("ix_agency_alerts_identifier", table_name="agency_alerts")
    op.drop_table("agency_alerts")
    # severity_enum is left alone: it belongs to verified_events, which 0001
    # created and this migration only borrowed.
