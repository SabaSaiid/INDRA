"""
INDRA Alert Engine — Canonical Data Models

These models represent Alert Engine internal state.
They do NOT map to any existing backend ORM model.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Alert Status States ────────────────────────────────────────────────────────

class AlertStatus(str, Enum):
    """Lifecycle states for an alert."""
    NORMAL = "NORMAL"
    TRIGGERED = "TRIGGERED"
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    SUPPRESSED = "SUPPRESSED"


# Valid state transitions: from_state → set of valid to_states
VALID_TRANSITIONS: Dict[AlertStatus, set] = {
    AlertStatus.NORMAL: {AlertStatus.TRIGGERED},
    AlertStatus.TRIGGERED: {AlertStatus.ACTIVE, AlertStatus.SUPPRESSED},
    AlertStatus.ACTIVE: {
        AlertStatus.ESCALATED,
        AlertStatus.ACKNOWLEDGED,
        AlertStatus.RESOLVED,
        AlertStatus.EXPIRED,
        AlertStatus.SUPPRESSED,
    },
    AlertStatus.ESCALATED: {
        AlertStatus.ACKNOWLEDGED,
        AlertStatus.RESOLVED,
        AlertStatus.EXPIRED,
    },
    AlertStatus.ACKNOWLEDGED: {
        AlertStatus.RESOLVED,
        AlertStatus.EXPIRED,
        AlertStatus.ESCALATED,  # Can re-escalate even if acknowledged
    },
    AlertStatus.RESOLVED: set(),   # Terminal
    AlertStatus.EXPIRED: set(),    # Terminal
    AlertStatus.SUPPRESSED: set(), # Terminal
}


def is_valid_transition(from_status: AlertStatus, to_status: AlertStatus) -> bool:
    """Return True iff the transition from_status → to_status is valid."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())


class EscalationLevel(str, Enum):
    NONE = "NONE"
    LEVEL_1 = "LEVEL_1"  # Severity increased
    LEVEL_2 = "LEVEL_2"  # Confidence significantly increased
    LEVEL_3 = "LEVEL_3"  # Area expanded + high confidence


class NotificationStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


# ── Severity ordering for comparison ──────────────────────────────────────────

SEVERITY_ORDER = {
    "ADVISORY": 0,
    "MODERATE": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def severity_gt(a: str, b: str) -> bool:
    """Return True if severity a is greater than severity b."""
    return SEVERITY_ORDER.get(a, 0) > SEVERITY_ORDER.get(b, 0)


def severity_gte(a: str, b: str) -> bool:
    return SEVERITY_ORDER.get(a, 0) >= SEVERITY_ORDER.get(b, 0)


# ── Normalized event from INDRA backend ───────────────────────────────────────

@dataclass
class IndraEvent:
    """
    Normalized representation of an INDRA VerifiedEvent.

    Populated from the existing /api/events response or VERIFIED_EVENT
    WebSocket message. Only fields confirmed to exist in the actual API
    response are included here.
    """
    id: str
    event_code: str
    event_type: str                # URBAN_FLOOD, CLOUDBURST, etc.
    severity: str                  # ADVISORY, MODERATE, HIGH, CRITICAL
    confidence_score: float        # 0.0 – 1.0
    review_status: str             # AUTO_PUBLISHED, PENDING_HUMAN_REVIEW, etc.
    quadrant: Optional[str]
    impact_radius_km: Optional[float]
    lat: Optional[float]
    lng: Optional[float]
    city: Optional[str]
    state: Optional[str]
    verified_at: str               # ISO8601 string
    source_count: int = 0          # from verification_receipt.cluster.size
    verification_receipt: Dict[str, Any] = field(default_factory=dict)
    raw_source: Optional[str] = None  # "api" or "websocket"

    @property
    def has_geometry(self) -> bool:
        return self.lat is not None and self.lng is not None

    @property
    def is_actionable(self) -> bool:
        """Events that are verified and approved."""
        unactionable = {"REJECTED", "PENDING_HUMAN_REVIEW", "QUARANTINED"}
        return self.review_status not in unactionable and self.quadrant != "Noise"

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "IndraEvent":
        """Build from /api/events list response item."""
        receipt = data.get("verification_receipt") or {}
        cluster = receipt.get("cluster") or {}
        source_count = cluster.get("size", 0)

        # Also check report_count field from pipeline output
        if source_count == 0:
            source_count = data.get("report_count", 0)

        return cls(
            id=str(data.get("id", "")),
            event_code=str(data.get("event_code", "")),
            event_type=str(data.get("event_type", data.get("eventType", "UNKNOWN"))),
            severity=str(data.get("severity", "ADVISORY")).upper(),
            confidence_score=float(data.get("confidence_score", 0.0)),
            review_status=str(data.get("review_status", "PENDING_HUMAN_REVIEW")),
            quadrant=data.get("quadrant"),
            impact_radius_km=data.get("impact_radius_km"),
            lat=data.get("lat"),
            lng=data.get("lng"),
            city=data.get("city"),
            state=data.get("state"),
            verified_at=str(data.get("verified_at") or data.get("timestamp", "")),
            source_count=source_count,
            verification_receipt=receipt,
            raw_source="api",
        )

    @classmethod
    def from_ws_verified_event(cls, data: Dict[str, Any]) -> "IndraEvent":
        """Build from VERIFIED_EVENT WebSocket message payload."""
        receipt = data.get("verification_receipt") or {}
        cluster = receipt.get("cluster") or {}
        source_count = cluster.get("size", data.get("report_count", 0))

        return cls(
            id=str(data.get("id", "")),
            event_code=str(data.get("event_code", "")),
            event_type=str(data.get("event_type", "UNKNOWN")),
            severity=str(data.get("severity", "ADVISORY")).upper(),
            confidence_score=float(data.get("confidence_score", 0.0)),
            review_status=str(data.get("review_status", "PENDING_HUMAN_REVIEW")),
            quadrant=data.get("quadrant"),
            impact_radius_km=data.get("impact_radius_km"),
            lat=data.get("lat"),
            lng=data.get("lng"),
            city=data.get("city"),
            state=data.get("state"),
            verified_at=str(data.get("verified_at", "")),
            source_count=source_count,
            verification_receipt=receipt,
            raw_source="websocket",
        )


# ── Alert Rule Model ───────────────────────────────────────────────────────────

@dataclass
class AlertRule:
    """
    A configurable rule that is evaluated against IndraEvents.
    Rules are not hardcoded — they are loaded from rule definitions.
    """
    rule_id: str
    rule_name: str
    description: str
    event_types: List[str]          # [] means all types
    minimum_severity: str           # Minimum severity to consider
    minimum_confidence: float       # Minimum confidence to trigger
    minimum_source_count: int       # Minimum corroboration count
    cooldown_seconds: int           # Minimum seconds between repeated alerts
    alert_duration_seconds: int     # How long alert stays ACTIVE before expiring
    escalation_confidence_delta: float  # Confidence increase that triggers escalation
    escalation_severity_upgrade: bool   # Severity increase triggers escalation
    enabled: bool = True
    priority: int = 50              # Lower = higher priority
    version: str = "1.0"


# ── Alert Model ────────────────────────────────────────────────────────────────

@dataclass
class Alert:
    """
    The canonical Alert object.

    Fields are only populated from actual event data.
    No fields are invented or hardcoded.
    """
    alert_id: str
    event_id: str
    event_code: str
    rule_id: str
    rule_version: str

    # Classification
    alert_type: str        # derived from event_type
    event_type: str
    severity: str
    status: AlertStatus
    escalation_level: EscalationLevel

    # Human-readable rule name (for display)
    rule_name: str

    # Human-readable
    title: str
    message: str

    # Evidence
    confidence: float
    source_count: int
    evidence: Dict[str, Any]   # verification_receipt factors

    # Location (only set if event has geometry)
    affected_area: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    impact_radius_km: Optional[float]

    # Mode
    mode: str   # "live" or "demo"

    # Timestamps
    created_at: datetime
    updated_at: datetime
    triggered_at: Optional[datetime]
    resolved_at: Optional[datetime]
    expires_at: Optional[datetime]

    # Acknowledgement
    acknowledgement_status: str = "UNACKNOWLEDGED"
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None

    # Notification
    notification_status: str = NotificationStatus.PENDING
    delivery_attempts: int = 0

    # Fingerprint for deduplication
    fingerprint: str = ""

    # Extra metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for API response and storage."""
        return {
            # `id` is an alias for alert_id so the frontend can use alert.id consistently
            "id": self.alert_id,
            "alert_id": self.alert_id,
            "event_id": self.event_id,
            "event_code": self.event_code,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_version": self.rule_version,
            "alert_type": self.alert_type,
            "event_type": self.event_type,
            "severity": self.severity,
            "status": self.status.value,
            "escalation_level": self.escalation_level.value,
            "title": self.title,
            "message": self.message,
            "confidence": self.confidence,
            "source_count": self.source_count,
            "evidence": self.evidence,
            "affected_area": self.affected_area,
            "lat": self.lat,
            "lng": self.lng,
            "impact_radius_km": self.impact_radius_km,
            "mode": self.mode,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "acknowledgement_status": self.acknowledgement_status,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "notification_status": self.notification_status,
            "delivery_attempts": self.delivery_attempts,
            "fingerprint": self.fingerprint,
            "metadata": self.metadata,
        }


@dataclass
class AlertHistory:
    """
    Immutable record of every alert state transition.
    """
    history_id: str
    alert_id: str
    previous_status: str
    new_status: str
    reason: str
    timestamp: datetime
    triggering_event_id: Optional[str]
    rule_id: Optional[str]
    actor: str      # "system", "analyst", "auto-resolution", etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "history_id": self.history_id,
            "alert_id": self.alert_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "triggering_event_id": self.triggering_event_id,
            "rule_id": self.rule_id,
            "actor": self.actor,
            "metadata": self.metadata,
        }


@dataclass
class NotificationAttempt:
    """Record of a single notification delivery attempt."""
    attempt_id: str
    alert_id: str
    provider: str   # "webhook", "email", "in_app"
    status: str     # NotificationStatus value
    attempted_at: datetime
    delivered_at: Optional[datetime]
    attempt_number: int
    error_message: Optional[str]
    response_code: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "alert_id": self.alert_id,
            "provider": self.provider,
            "status": self.status,
            "attempted_at": self.attempted_at.isoformat(),
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "attempt_number": self.attempt_number,
            "error_message": self.error_message,
            "response_code": self.response_code,
        }
