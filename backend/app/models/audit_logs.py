"""
INDRA Platform — AuditLog ORM Model (Immutable Ledger)
The BEFORE UPDATE OR DELETE trigger is created via Alembic migration.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Enum, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.enums import AuditAction


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verified_events.id"),
        nullable=True,
    )
    operator_id = Column(String(50), nullable=False)
    action_taken = Column(
        Enum(AuditAction, name="audit_action_enum"), nullable=False
    )
    reason = Column(Text, nullable=True)
    sha256_hash = Column(String(64), nullable=False)
    logged_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_event_id", "event_id"),
    )

    # Relationships
    event = relationship("VerifiedEvent", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} [{self.action_taken.value}]>"
