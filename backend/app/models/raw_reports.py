"""
INDRA Platform — RawReport ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Text, Enum, DateTime, ForeignKey,
    Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import SourceType


class RawReport(Base):
    __tablename__ = "raw_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    source_type = Column(
        Enum(SourceType, name="source_type_enum"), nullable=False
    )
    raw_text = Column(Text, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geom_point = Column(Geometry("POINT", srid=4326), nullable=True)
    h3_res8 = Column(String(20), nullable=True)
    media_url = Column(String(512), nullable=True)
    credibility_score = Column(Float, nullable=False, default=0.5)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id", use_alter=True),
        nullable=True,
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "latitude >= -90.0 AND latitude <= 90.0",
            name="ck_latitude_range",
        ),
        CheckConstraint(
            "longitude >= -180.0 AND longitude <= 180.0",
            name="ck_longitude_range",
        ),
        CheckConstraint(
            "credibility_score >= 0.0 AND credibility_score <= 1.0",
            name="ck_credibility_range",
        ),
        Index(
            "ix_reports_geom_point_gist",
            "geom_point",
            postgresql_using="gist",
        ),
    )

    # Relationships
    event = relationship("VerifiedEvent", back_populates="raw_reports")

    def __repr__(self) -> str:
        return f"<RawReport {self.id} [{self.source_type.value}]>"
