"""
INDRA Platform — VerifiedEvent ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Enum, DateTime, Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.core.database import Base
from app.models.enums import EventType, Severity, ReviewStatus, Quadrant


class VerifiedEvent(Base):
    __tablename__ = "verified_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_code = Column(String(20), unique=True, nullable=False)
    event_type = Column(Enum(EventType, name="event_type_enum"), nullable=False)
    severity = Column(Enum(Severity, name="severity_enum"), nullable=False)
    confidence_score = Column(Float, nullable=False, default=0.0)
    review_status = Column(
        Enum(ReviewStatus, name="review_status_enum"),
        nullable=False,
        default=ReviewStatus.PENDING_HUMAN_REVIEW,
    )
    quadrant = Column(Enum(Quadrant, name="quadrant_enum"), nullable=False)
    impact_radius_km = Column(Float, nullable=True)
    center_point = Column(Geometry("POINT", srid=4326), nullable=True)
    boundary_polygon = Column(Geometry("POLYGON", srid=4326), nullable=True)
    verification_receipt = Column(JSONB, nullable=True)

    # Where the event is, in words. NULL when the resolver declined to name the
    # point rather than guess at it — see services/geocoding.reverse_geocode.
    # `place_precision` says whether the centroid was inside this district or
    # merely near it, so a caller can hedge a label when the resolver hedged.
    district = Column(String(120), nullable=True)
    state = Column(String(120), nullable=True)
    place_precision = Column(String(16), nullable=True)

    verified_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    # When the event last changed, which is not when it was created: merging a
    # report into an existing event rewrites its score and receipt. The merge
    # window is keyed on this column because keying it on `verified_at` closed
    # the window two hours after creation however recently the event had
    # absorbed a report (BUG-035).
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_confidence_range",
        ),
        Index(
            "ix_events_status_severity",
            "review_status",
            "severity",
        ),
        Index(
            "ix_events_center_point_gist",
            "center_point",
            postgresql_using="gist",
        ),
        Index(
            "ix_events_boundary_polygon_gist",
            "boundary_polygon",
            postgresql_using="gist",
        ),
    )

    # Relationships
    raw_reports = relationship("RawReport", back_populates="event", lazy="selectin")
    audit_logs = relationship("AuditLog", back_populates="event", lazy="selectin")
    assigned_teams = relationship("Team", back_populates="assigned_event", lazy="selectin")

    def __repr__(self) -> str:
        return f"<VerifiedEvent {self.event_code} [{self.severity.value}]>"

