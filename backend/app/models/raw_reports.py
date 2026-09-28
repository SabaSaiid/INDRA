"""
INDRA Platform — RawReport ORM Model
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Text, Enum, DateTime, ForeignKey,
    Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    # Nullable since migration 0015: a post that names no place is stored
    # anyway, with no coordinates. place_precision says what they are worth.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
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

    # Token subject of the operator who filed this report through the
    # authenticated route (POST /api/reports/official, migration 0010). NULL
    # for citizen reports, which are anonymous by design.
    submitted_by = Column(String(50), nullable=True)

    # Migration 0012 (Phase 1). See its docstring for each column's meaning.
    # When it happened; created_at is when INDRA received it.
    observed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # HMAC of the client's random id; the raw id is never stored.
    reporter_hash = Column(String(64), nullable=True)
    # The citizen's tracking number, R-XXXXXXXX. Random, never sequential.
    docket = Column(String(16), nullable=True, unique=True)
    # Where a fed item came from, and its id there (Phase 2's pollers).
    platform = Column(String(32), nullable=True)
    external_id = Column(String(512), nullable=True)
    source_meta = Column(JSONB, nullable=True)
    # The category the citizen picked — their claim, not the event's type.
    citizen_hazard = Column(String(32), nullable=True)
    # When the pipeline finished with this report, whatever it decided.
    processed_at = Column(DateTime(timezone=True), nullable=True)
    # gps | district | state | none (migration 0015). Only gps and district
    # positions are ever clustered.
    place_precision = Column(String(10), nullable=True)
    # Migration 0017 (Phase 3). The hazard the text is about and its family,
    # from services/hazard_tagger.py (NULL when the text names none), and the
    # misleading-text flags (services/report_flags.py; empty when clean).
    # analysis.hazards keeps the full detail.
    hazard_primary = Column(String(32), nullable=True)
    hazard_family = Column(String(16), nullable=True)
    flags = Column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    # Migration 0023 (Phase 5 T5): when the citizen withdrew the report. The
    # text and exact position are redacted and its media deleted; the row stays
    # so the docket still answers "withdrawn".
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)

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
