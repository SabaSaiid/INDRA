"""
INDRA Alert Engine — Lifecycle Manager
"""

import uuid
from datetime import datetime, timezone
import logging
from typing import Optional

from alert_engine.models import Alert, IndraEvent, AlertRule, AlertStatus, AlertHistory, EscalationLevel, NotificationStatus
from alert_engine.engine.deduplication import generate_fingerprint

logger = logging.getLogger("alert_engine.engine.lifecycle")


class LifecycleManager:
    """Handles state transitions for Alerts and generates AlertHistory records."""

    @staticmethod
    def create_alert(event: IndraEvent, rule: AlertRule, reason: str) -> tuple[Alert, AlertHistory]:
        now = datetime.now(timezone.utc)
        alert_id = f"ALT-{now.year}-{uuid.uuid4().hex[:6].upper()}"
        
        fingerprint = generate_fingerprint(event, rule)

        alert = Alert(
            alert_id=alert_id,
            event_id=event.id,
            event_code=event.event_code,
            rule_id=rule.rule_id,
            rule_version=rule.version,
            alert_type=event.event_type,
            event_type=event.event_type,
            severity=event.severity,
            status=AlertStatus.ACTIVE,
            escalation_level=EscalationLevel.NONE,
            title=f"{event.severity} WARNING: {event.event_type} in {event.quadrant}",
            message=reason,
            confidence=event.confidence_score,
            source_count=event.source_count,
            evidence=event.verification_receipt,
            affected_area=event.quadrant,
            lat=event.lat,
            lng=event.lng,
            impact_radius_km=event.impact_radius_km,
            mode=event.raw_source or "demo",
            created_at=now,
            updated_at=now,
            triggered_at=now,
            resolved_at=None,
            expires_at=None,
            fingerprint=fingerprint,
        )

        history = AlertHistory(
            history_id=uuid.uuid4().hex,
            alert_id=alert_id,
            previous_status="NONE",
            new_status=AlertStatus.ACTIVE.value,
            reason=reason,
            timestamp=now,
            triggering_event_id=event.id,
            rule_id=rule.rule_id,
            actor="system"
        )
        
        logger.info(f"Created new alert {alert_id} for event {event.event_code}")
        return alert, history

    @staticmethod
    def escalate_alert(alert: Alert, event: IndraEvent, level: str, reason: str) -> AlertHistory:
        now = datetime.now(timezone.utc)
        prev_status = alert.status.value
        
        alert.status = AlertStatus.ESCALATED
        alert.escalation_level = EscalationLevel(level) if isinstance(level, str) else level
        alert.severity = event.severity
        alert.confidence = event.confidence_score
        alert.source_count = event.source_count
        alert.evidence = event.verification_receipt
        alert.updated_at = now
        alert.notification_status = NotificationStatus.PENDING # Re-notify on escalation
        alert.delivery_attempts = 0

        history = AlertHistory(
            history_id=uuid.uuid4().hex,
            alert_id=alert.alert_id,
            previous_status=prev_status,
            new_status=AlertStatus.ESCALATED.value,
            reason=reason,
            timestamp=now,
            triggering_event_id=event.id,
            rule_id=alert.rule_id,
            actor="system"
        )
        
        logger.info(f"Escalated alert {alert.alert_id} for event {event.event_code}")
        return history

    @staticmethod
    def update_alert(alert: Alert, event: IndraEvent, reason: str) -> Optional[AlertHistory]:
        now = datetime.now(timezone.utc)
        
        # We don't change status, just update data
        alert.confidence = event.confidence_score
        alert.source_count = event.source_count
        alert.evidence = event.verification_receipt
        alert.updated_at = now
        
        logger.debug(f"Updated alert {alert.alert_id} for event {event.event_code}")
        return None  # Routine updates don't necessarily need a history record unless we want high verbosity

    @staticmethod
    def resolve_alert(alert: Alert, reason: str, actor: str = "system") -> AlertHistory:
        now = datetime.now(timezone.utc)
        prev_status = alert.status.value
        
        alert.status = AlertStatus.RESOLVED
        alert.updated_at = now
        alert.resolved_at = now

        history = AlertHistory(
            history_id=uuid.uuid4().hex,
            alert_id=alert.alert_id,
            previous_status=prev_status,
            new_status=AlertStatus.RESOLVED.value,
            reason=reason,
            timestamp=now,
            triggering_event_id=alert.event_id,
            rule_id=alert.rule_id,
            actor=actor
        )
        
        logger.info(f"Resolved alert {alert.alert_id} (Reason: {reason})")
        return history

    @staticmethod
    def acknowledge_alert(alert: Alert, actor: str) -> AlertHistory:
        now = datetime.now(timezone.utc)
        prev_status = alert.status.value
        
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledgement_status = "ACKNOWLEDGED"
        alert.acknowledged_by = actor
        alert.acknowledged_at = now
        alert.updated_at = now

        history = AlertHistory(
            history_id=uuid.uuid4().hex,
            alert_id=alert.alert_id,
            previous_status=prev_status,
            new_status=AlertStatus.ACKNOWLEDGED.value,
            reason="User acknowledged alert",
            timestamp=now,
            triggering_event_id=alert.event_id,
            rule_id=alert.rule_id,
            actor=actor
        )
        
        logger.info(f"Alert {alert.alert_id} acknowledged by {actor}")
        return history
