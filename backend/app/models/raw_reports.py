"""
INDRA Platform — RawReport ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Text, Enum, DateTime, ForeignKey,
    Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Resolved from the report's own coordinates at ingest. NULL when the
    # resolver declined to name the point — see services/geocoding.
    district = Column(String(120), nullable=True)
    state = Column(String(120), nullable=True)
    media_url = Column(String(512), nullable=True)
    credibility_score = Column(Float, nullable=False, default=0.5)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id", use_alter=True),
        nullable=True,
    )
    # Set when the pipeline suppresses this report as a duplicate; points at
    # the original. Such a report is never clustered or counted (migration 0004).
    duplicate_of = Column(
        UUID(as_uuid=True),
        ForeignKey("raw_reports.id"),
        nullable=True,
    )

    # What layer 3 extracted from raw_text at ingest: cleaned_text, language,
    # depth_cm, depth_basis, keywords, places, url_count, phone_count,
    # extracted_at (migration 0005). Rules and dictionaries, never a model.
    #
    # NULL means the extraction failed and the report was stored anyway — a
    # disaster report is not worth losing to a regex. Content severity therefore
    # re-extracts from raw_text rather than trusting this column; see
    # services/pipeline.py::_report_texts.
    analysis = Column(JSONB, nullable=True)

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
