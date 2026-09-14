"""
INDRA Platform — Team ORM Model
Operational Disaster Response & Analytics Units (NDRF, SDRF, IMD, CWC, Municipal)
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Enum, DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.enums import TeamStatus, TeamAgency


class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    agency = Column(
        Enum(TeamAgency, name="team_agency_enum"),
        nullable=False,
        default=TeamAgency.NDRF,
    )
    city = Column(String(80), nullable=False)
    state = Column(String(80), nullable=False)
    lead_name = Column(String(100), nullable=False)
    lead_phone = Column(String(30), nullable=True)
    radio_callsign = Column(String(40), nullable=True)
    specialization = Column(String(200), nullable=True)
    status = Column(
        Enum(TeamStatus, name="team_status_enum"),
        nullable=False,
        default=TeamStatus.AVAILABLE,
    )
    members_count = Column(Integer, nullable=False, default=12)
    assigned_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_teams_status_agency", "status", "agency"),
        Index("ix_teams_city", "city"),
    )

    # Relationships
    assigned_event = relationship("VerifiedEvent", back_populates="assigned_teams", lazy="joined")
    members = relationship("UserProfile", back_populates="team", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Team {self.team_code} [{self.name}] - {self.status.value}>"
