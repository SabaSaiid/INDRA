"""
INDRA Platform — ReportMedia ORM Model (Phase 5 T1, T2, T4; migration 0021)

One photo or video attached to a report: the upload session while it arrives,
then where its bytes are, what was read from it (EXIF, SHA-256, perceptual
hashes) and what the recycled-media rules said about it. The migration's
docstring describes every column.

Hashes and metadata are deduplication, not vision: nothing here says what an
image shows, and `vision_analysis` stays offline in every receipt.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base


class ReportMedia(Base):
    __tablename__ = "report_media"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("raw_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    # citizen | social
    origin = Column(String(16), nullable=False, default="citizen", server_default="citizen")
    # image | video
    kind = Column(String(8), nullable=False)
    # uploading | processing | ready | rejected | withdrawn
    status = Column(String(16), nullable=False)
    reason = Column(Text, nullable=True)

    declared_mime = Column(String(100), nullable=True)
    declared_size = Column(BigInteger, nullable=True)
    parts = Column(Integer, nullable=True)
    s3_upload_id = Column(Text, nullable=True)
    incoming_key = Column(Text, nullable=True)

    object_key = Column(Text, nullable=True)
    derivative_key = Column(Text, nullable=True)
    poster_key = Column(Text, nullable=True)
    thumb_key = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)

    mime = Column(String(100), nullable=True)
    bytes = Column(BigInteger, nullable=True)
    sha256 = Column(String(64), nullable=True)
    phash = Column(BigInteger, nullable=True)
    frame_phashes = Column(ARRAY(BigInteger), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_s = Column(Float, nullable=True)
    exif_taken_at = Column(DateTime(timezone=True), nullable=True)
    exif_offset = Column(String(8), nullable=True)
    exif_lat = Column(Float, nullable=True)
    exif_lng = Column(Float, nullable=True)
    exif_make = Column(Text, nullable=True)
    exif_model = Column(Text, nullable=True)
    exif_software = Column(Text, nullable=True)

    flags = Column(ARRAY(Text), nullable=False, default=list, server_default="{}")
    flag_basis = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    original_deleted_at = Column(DateTime(timezone=True), nullable=True)
    derivatives_deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('image', 'video')", name="ck_report_media_kind"),
        CheckConstraint(
            "status IN ('uploading', 'processing', 'ready', 'rejected', 'withdrawn')",
            name="ck_report_media_status",
        ),
        CheckConstraint("origin IN ('citizen', 'social')", name="ck_report_media_origin"),
        Index("ix_report_media_report_id", "report_id"),
        Index("ix_report_media_sha256", "sha256"),
        Index("ix_report_media_status", "status"),
        Index(
            "uq_report_media_source_url",
            "report_id",
            "source_url",
            unique=True,
            postgresql_where=text("source_url IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ReportMedia {self.id} {self.kind} {self.status}>"
