"""
INDRA Alert Engine — Decision Engine
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone
import logging

from alert_engine.models import IndraEvent, AlertRule, Alert, AlertStatus, EscalationLevel, severity_gt

logger = logging.getLogger("alert_engine.engine.decision")


class DecisionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ESCALATE = "ESCALATE"
    RESOLVE = "RESOLVE"


@dataclass
class AlertDecision:
    type: DecisionType
    reason: str
    rule: Optional[AlertRule] = None
    existing_alert: Optional[Alert] = None
    escalation_level: EscalationLevel = EscalationLevel.NONE


def evaluate_decision(
    event: IndraEvent,
    matched_rule: Optional[AlertRule],
    trigger_reason: Optional[str],
    existing_alert: Optional[Alert]
) -> AlertDecision:
    """
    Given an event, the rule it matched (if any), and its existing alert (if any),
    determine what action to take.
    """
    now = datetime.now(timezone.utc)

    # 1. No rule matched
    if not matched_rule:
        if existing_alert and existing_alert.status in (AlertStatus.ACTIVE, AlertStatus.ESCALATED, AlertStatus.ACKNOWLEDGED):
            # The event no longer meets criteria. Should it be resolved?
            # Handled by lifecycle/stale logic, but we can explicitly resolve here if needed.
            # For simplicity, we let the stale/resolution lifecycle handle it or resolve directly.
            return AlertDecision(
                type=DecisionType.RESOLVE,
                reason="Event no longer meets any rule criteria.",
                existing_alert=existing_alert
            )
        return AlertDecision(type=DecisionType.NO_ACTION, reason="No rules matched.")

    # 2. Rule matched, but no existing alert -> CREATE
    if not existing_alert:
        return AlertDecision(
            type=DecisionType.CREATE,
            reason=trigger_reason or "Rule matched.",
            rule=matched_rule
        )

    # 3. Rule matched, existing alert exists
    # Check for resolution first if status is terminal, but if terminal, we might want a new alert?
    # Cooldown prevents immediate re-triggering. If it's expired/resolved, let deduplication / cooldown handle it,
    # or just CREATE if cooldown has passed. We assume existing_alert is the most recent.
    
    if existing_alert.status in (AlertStatus.RESOLVED, AlertStatus.EXPIRED, AlertStatus.SUPPRESSED):
        # Has cooldown passed?
        if (now - existing_alert.updated_at).total_seconds() > matched_rule.cooldown_seconds:
            return AlertDecision(
                type=DecisionType.CREATE,
                reason=f"Previous alert {existing_alert.status.value}, cooldown passed. Re-triggering.",
                rule=matched_rule
            )
        else:
            return AlertDecision(
                type=DecisionType.NO_ACTION,
                reason="Within cooldown period of a resolved/expired alert.",
                existing_alert=existing_alert
            )

    # It's ACTIVE, ESCALATED, or ACKNOWLEDGED. Check for escalation.
    escalation = EscalationLevel.NONE
    esc_reasons = []

    if matched_rule.escalation_severity_upgrade and severity_gt(event.severity, existing_alert.severity):
        escalation = EscalationLevel.LEVEL_1
        esc_reasons.append(f"Severity increased: {existing_alert.severity} -> {event.severity}")

    conf_delta = event.confidence_score - existing_alert.confidence
    if conf_delta >= matched_rule.escalation_confidence_delta:
        escalation = EscalationLevel.LEVEL_2
        esc_reasons.append(f"Confidence increased by {conf_delta:.2f}")

    if escalation != EscalationLevel.NONE:
        return AlertDecision(
            type=DecisionType.ESCALATE,
            reason="; ".join(esc_reasons),
            rule=matched_rule,
            existing_alert=existing_alert,
            escalation_level=escalation
        )

    # Otherwise, it's just a routine update (e.g. source count increased, location shifted slightly)
    # Update if there are meaningful changes.
    if event.source_count > existing_alert.source_count or event.confidence_score != existing_alert.confidence:
         return AlertDecision(
             type=DecisionType.UPDATE,
             reason="Routine update (confidence or source count changed).",
             rule=matched_rule,
             existing_alert=existing_alert
         )

    return AlertDecision(
        type=DecisionType.NO_ACTION,
        reason="No meaningful changes.",
        existing_alert=existing_alert
    )
