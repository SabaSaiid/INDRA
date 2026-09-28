"""
INDRA Platform — Reporter reputation ORM Models (Phase 5 T6, migration 0022)

`ReporterStats` counts, per reporter pseudonym, what services/reputation.py
turns into a trust figure: (approved + 1) / (approved + rejected + 2).
`ReporterDecision` holds the human decisions those counts are recounted from,
one per (reporter, event), so a changed decision is never counted twice.
"""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ReporterStats(Base):
    __tablename__ = "reporter_stats"

    reporter_hash = Column(String(64), primary_key=True)
    source_type = Column(String(32), nullable=True)
    platform = Column(String(32), nullable=True)
    reports = Column(Integer, nullable=False, default=0, server_default="0")
    approved = Column(Integer, nullable=False, default=0, server_default="0")
    rejected = Column(Integer, nullable=False, default=0, server_default="0")
    flagged = Column(Integer, nullable=False, default=0, server_default="0")
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_reporter_stats_reports", "reports"),)

    def __repr__(self) -> str:
        return f"<ReporterStats {self.reporter_hash[:12]}… {self.approved}/{self.rejected}>"


class ReporterDecision(Base):
    __tablename__ = "reporter_decisions"

    reporter_hash = Column(String(64), primary_key=True)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # approved | rejected
    decision = Column(String(8), nullable=False)
    decided_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_reporter_decision"),
    )
