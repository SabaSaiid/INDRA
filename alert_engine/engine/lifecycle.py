"""
INDRA Alert Engine — Lifecycle Manager
"""

import uuid
from datetime import datetime, timezone
import logging
from typing import Optional

from alert_engine.models import Alert, IndraEvent, AlertRule, AlertStatus, AlertHistory, EscalationLevel, NotificationStatus
from alert_engine.engine.deduplication import generate_fingerprint
from alert_engine.config import get_alert_settings

logger = logging.getLogger("alert_engine.engine.lifecycle")
settings = get_alert_settings()


class LifecycleManager:
    """Handles state transitions for Alerts and generates AlertHistory records."""

    @staticmethod
    def create_alert(event: IndraEvent, rule: AlertRule, reason: str) -> tuple[Alert, AlertHistory]:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        alert_id = f"ALT-{now.year}-{uuid.uuid4().hex[:6].upper()}"
        
        fingerprint = generate_fingerprint(event, rule)

        alert = Alert(
            alert_id=alert_id,
            event_id=event.id,
            event_code=event.event_code,
            rule_id=rule.rule_id,
            rule_name=rule.rule_name,
            rule_version=rule.version,
            alert_type=event.event_type,
            event_type=event.event_type,
            severity=event.severity,
            status=AlertStatus.ACTIVE,
            escalation_level=EscalationLevel.NONE,
            title=f"{event.event_type} — {event.severity.upper()} severity",
            message=reason,
            confidence=event.confidence_score,
            source_count=event.source_count,
            evidence=event.verification_receipt,
            affected_area=f"{event.city}, {event.state}" if event.city and event.state else (event.city or event.state or event.quadrant),
            lat=event.lat,
            lng=event.lng,
            impact_radius_km=event.impact_radius_km,
            mode="DEMO" if settings.ALERT_ENGINE_MODE.lower() == "demo" else "LIVE",
            created_at=now,
            updated_at=now,
            triggered_at=now,
            resolved_at=None,
            expires_at=now + timedelta(seconds=rule.alert_duration_seconds),
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
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        
        # We don't change status, just update data
        alert.confidence = event.confidence_score
        alert.source_count = event.source_count
        alert.evidence = event.verification_receipt
        alert.updated_at = now
        
        # Extend the expiry
        from alert_engine.rules.registry import get_active_rules
        rule = next((r for r in get_active_rules() if r.rule_id == alert.rule_id), None)
        if rule:
            alert.expires_at = now + timedelta(seconds=rule.alert_duration_seconds)

        
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
