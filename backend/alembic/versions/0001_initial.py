"""Initial INDRA schema — all four tables, spatial indexes, immutability trigger

Revision ID: 0001_initial
Revises: None
Create Date: 2026-09-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
import geoalchemy2

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure PostGIS
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ── verified_events ────────────────────────────────────────────────────
    op.create_table(
        "verified_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_code", sa.String(20), unique=True, nullable=False),
        sa.Column("event_type", sa.Enum("URBAN_FLOOD", "CLOUDBURST", "CYCLONE_INUNDATION", "RIVER_BREACH", name="event_type_enum"), nullable=False),
        sa.Column("severity", sa.Enum("ADVISORY", "MODERATE", "HIGH", "CRITICAL", name="severity_enum"), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("review_status", sa.Enum("AUTO_PUBLISHED", "PENDING_HUMAN_REVIEW", "QUARANTINED", "REJECTED", name="review_status_enum"), nullable=False, server_default="PENDING_HUMAN_REVIEW"),
        sa.Column("quadrant", sa.Enum("Critical Verified Event", "Unverified Threat", "Confirmed Minor Event", "Noise", name="quadrant_enum"), nullable=False),
        sa.Column("impact_radius_km", sa.Float, nullable=True),
        sa.Column("center_point", geoalchemy2.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("boundary_polygon", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=True),
        sa.Column("verification_receipt", JSONB, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("confidence_score >= 0.0 AND confidence_score <= 1.0", name="ck_confidence_range"),
    )
    op.create_index("ix_events_status_severity", "verified_events", ["review_status", "severity"])
    op.create_index("ix_events_center_point_gist", "verified_events", ["center_point"], postgresql_using="gist")
    op.create_index("ix_events_boundary_polygon_gist", "verified_events", ["boundary_polygon"], postgresql_using="gist")

    # ── raw_reports ────────────────────────────────────────────────────────
    op.create_table(
        "raw_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("source_type", sa.Enum("CITIZEN_APP", "TWITTER_IMD", "AWS_SENSOR", "CWC_GAUGE", "OFFICIAL_DISPATCH", name="source_type_enum"), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("geom_point", geoalchemy2.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("h3_res8", sa.String(20), nullable=True),
        sa.Column("media_url", sa.String(512), nullable=True),
        sa.Column("credibility_score", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("verified_events.id"), nullable=True),
        sa.CheckConstraint("latitude >= -90.0 AND latitude <= 90.0", name="ck_latitude_range"),
        sa.CheckConstraint("longitude >= -180.0 AND longitude <= 180.0", name="ck_longitude_range"),
        sa.CheckConstraint("credibility_score >= 0.0 AND credibility_score <= 1.0", name="ck_credibility_range"),
    )
    op.create_index("ix_reports_geom_point_gist", "raw_reports", ["geom_point"], postgresql_using="gist")

    # ── station_readings ───────────────────────────────────────────────────
    op.create_table(
        "station_readings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("station_code", sa.String(30), nullable=False),
        sa.Column("station_name", sa.String(120), nullable=False),
        sa.Column("agency", sa.Enum("IMD", "CWC", "OPEN_METEO", name="agency_enum"), nullable=False),
        sa.Column("station_location", geoalchemy2.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("rainfall_mm", sa.Float, nullable=True),
        sa.Column("river_level_m", sa.Float, nullable=True),
        sa.Column("anomaly_score", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_stations_location_gist", "station_readings", ["station_location"], postgresql_using="gist")

    # ── audit_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("verified_events.id"), nullable=True),
        sa.Column("operator_id", sa.String(50), nullable=False),
        sa.Column("action_taken", sa.Enum("AUTO_VERIFY", "MANUAL_OVERRIDE", "QUARANTINE", "ESCALATE", name="audit_action_enum"), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_audit_event_id", "audit_logs", ["event_id"])

    # ── Immutable ledger trigger on audit_logs ─────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is an immutable ledger — UPDATE and DELETE are forbidden';
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_mutation()")
    op.drop_table("audit_logs")
    op.drop_table("station_readings")
    op.drop_table("raw_reports")
    op.drop_table("verified_events")
    op.execute("DROP TYPE IF EXISTS audit_action_enum")
    op.execute("DROP TYPE IF EXISTS agency_enum")
    op.execute("DROP TYPE IF EXISTS source_type_enum")
    op.execute("DROP TYPE IF EXISTS quadrant_enum")
    op.execute("DROP TYPE IF EXISTS review_status_enum")
    op.execute("DROP TYPE IF EXISTS severity_enum")
    op.execute("DROP TYPE IF EXISTS event_type_enum")
