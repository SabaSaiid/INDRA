"""
INDRA Platform — UserProfile ORM Model
Operator profiles with duty tracking, RBAC, tactical callsigns, and team membership
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Enum, DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.enums import OperatorRole, DutyStatus


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=True)
    phone = Column(String(30), nullable=True)
    role = Column(
        Enum(OperatorRole, name="operator_role_enum"),
        nullable=False,
        default=OperatorRole.COMMANDER,
    )
    agency = Column(String(50), nullable=False, default="NDMA")
    operator_id = Column(String(30), unique=True, nullable=False, index=True)
    badge_number = Column(String(40), nullable=True)
    callsign = Column(String(40), nullable=True)
    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )
    team_role = Column(String(80), nullable=True)
    duty_status = Column(
        Enum(DutyStatus, name="duty_status_enum"),
        nullable=False,
        default=DutyStatus.ON_DUTY,
    )
    avatar_url = Column(String(512), nullable=True)
    bio = Column(Text, nullable=True)
    last_active_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_profiles_role_duty", "role", "duty_status"),
        Index("ix_profiles_agency", "agency"),
    )

    # Relationships
    team = relationship("Team", back_populates="members")

    def __repr__(self) -> str:
        return f"<UserProfile {self.username} [{self.role.value}] - {self.duty_status.value}>"
