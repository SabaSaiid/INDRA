"""Add teams and user_profiles tables with foreign keys and indexes

Revision ID: 0002_teams_and_profiles
Revises: 0001_initial
Create Date: 2026-09-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_teams_and_profiles"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── teams ──────────────────────────────────────────────────────────────
    op.create_table(
        "teams",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_code", sa.String(30), unique=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "agency",
            sa.Enum("NDRF", "SDRF", "IMD", "CWC", "NDMA", "MUNICIPAL", name="team_agency_enum"),
            nullable=False,
            server_default="NDRF",
        ),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(80), nullable=False),
        sa.Column("lead_name", sa.String(100), nullable=False),
        sa.Column("lead_phone", sa.String(30), nullable=True),
        sa.Column("radio_callsign", sa.String(40), nullable=True),
        sa.Column("specialization", sa.String(200), nullable=True),
        sa.Column(
            "status",
            sa.Enum("AVAILABLE", "DEPLOYED", "STANDBY", "OFF_DUTY", name="team_status_enum"),
            nullable=False,
            server_default="AVAILABLE",
        ),
        sa.Column("members_count", sa.Integer, nullable=False, server_default="12"),
        sa.Column(
            "assigned_event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verified_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_teams_team_code", "teams", ["team_code"])
    op.create_index("ix_teams_status_agency", "teams", ["status", "agency"])
    op.create_index("ix_teams_city", "teams", ["city"])

    # ── user_profiles ──────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(120), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column(
            "role",
            sa.Enum("COMMANDER", "ANALYST", "ADMIN", "CITIZEN", "FIELD_RESPONDER", name="operator_role_enum"),
            nullable=False,
            server_default="COMMANDER",
        ),
        sa.Column("agency", sa.String(50), nullable=False, server_default="NDMA"),
        sa.Column("operator_id", sa.String(30), unique=True, nullable=False),
        sa.Column("badge_number", sa.String(40), nullable=True),
        sa.Column("callsign", sa.String(40), nullable=True),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("team_role", sa.String(80), nullable=True, server_default="Operational Specialist"),
        sa.Column(
            "duty_status",
            sa.Enum("ON_DUTY", "STANDBY", "DEPLOYED", "OFF_DUTY", name="duty_status_enum"),
            nullable=False,
            server_default="ON_DUTY",
        ),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_profiles_username", "user_profiles", ["username"])
    op.create_index("ix_profiles_operator_id", "user_profiles", ["operator_id"])
    op.create_index("ix_profiles_role_duty", "user_profiles", ["role", "duty_status"])
    op.create_index("ix_profiles_agency", "user_profiles", ["agency"])


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_table("teams")
    op.execute("DROP TYPE IF EXISTS operator_role_enum")
    op.execute("DROP TYPE IF EXISTS duty_status_enum")
    op.execute("DROP TYPE IF EXISTS team_status_enum")
    op.execute("DROP TYPE IF EXISTS team_agency_enum")
