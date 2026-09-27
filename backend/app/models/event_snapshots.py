"""
INDRA Platform — EventSnapshot ORM Model (Phase 4 T7, migration 0020)

One row every time an event's score is written: at creation, at every merge,
at every late re-score. `GET /api/events/{id}/history` merges these with the
event's audit rows into one timeline, which is how the dashboard can draw
confidence over time and the full status history.

`verdict` and `review_status` are stored as text, so a history row never fails
on a value a later migration adds to the enums.
"""

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class EventSnapshot(Base):
    __tablename__ = "event_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    at = Column(DateTime(timezone=True), nullable=False)
    confidence = Column(Float, nullable=False)
    factor_coverage = Column(Float, nullable=True)
    report_count = Column(Integer, nullable=True)
    verdict = Column(String(16), nullable=True)
    review_status = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=True)
    # created | merge | late:sachet:<identifier> | late:metar:<station>@<time> | rescore
    trigger = Column(String(160), nullable=False)
    receipt_version = Column(Integer, nullable=True)
    details = Column(JSONB, nullable=True)

    __table_args__ = (Index("ix_event_snapshots_event_at", "event_id", "at"),)

    def __repr__(self) -> str:
        return f"<EventSnapshot {self.event_id} {self.trigger} {self.confidence}>"
