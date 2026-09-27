"""
INDRA Alert Engine — Rule Registry

Defines the default rules and the evaluator factory.
"""

from typing import Dict, Type
from alert_engine.models import AlertRule, IndraEvent
from alert_engine.rules.base import BaseRuleEvaluator
from alert_engine.config import get_alert_settings

settings = get_alert_settings()


class BasicThresholdRule(BaseRuleEvaluator):
    """
    A simple rule that triggers if the base thresholds are met.
    The base class `is_applicable` handles the threshold checks.
    """
    def evaluate(self, event: IndraEvent) -> tuple[bool, str | None]:
        if not self.is_applicable(event):
            return False, None
        return True, f"Event {event.event_type} met basic thresholds (sev={event.severity}, conf={event.confidence_score:.2f})"


# ── Default Rule Configurations ─────────────────────────────────────────────

DEFAULT_RULES = [
    AlertRule(
        rule_id="RULE_CRITICAL_EVENT",
        rule_name="Critical Event Alert",
        description="Triggers on any event with CRITICAL severity and high confidence.",
        event_types=[],
        minimum_severity="CRITICAL",
        minimum_confidence=settings.ALERT_CRITICAL_CONFIDENCE,
        minimum_source_count=settings.ALERT_MIN_SOURCE_COUNT,
        cooldown_seconds=settings.ALERT_DEFAULT_COOLDOWN_SECONDS,
        alert_duration_seconds=settings.ALERT_DEFAULT_TTL_SECONDS,
        escalation_confidence_delta=settings.ALERT_ESCALATION_CONFIDENCE_DELTA,
        escalation_severity_upgrade=True,
        priority=10,
    ),
    AlertRule(
        rule_id="RULE_HIGH_CONFIDENCE_FLOOD",
        rule_name="High Confidence Flood Alert",
        description="Triggers on URBAN_FLOOD or RIVER_BREACH with HIGH severity.",
        event_types=["URBAN_FLOOD", "RIVER_BREACH"],
        minimum_severity="HIGH",
        minimum_confidence=settings.ALERT_MIN_CONFIDENCE,
        minimum_source_count=settings.ALERT_MIN_SOURCE_COUNT,
        cooldown_seconds=settings.ALERT_DEFAULT_COOLDOWN_SECONDS,
        alert_duration_seconds=settings.ALERT_DEFAULT_TTL_SECONDS,
        escalation_confidence_delta=settings.ALERT_ESCALATION_CONFIDENCE_DELTA,
        escalation_severity_upgrade=True,
        priority=20,
    ),
    AlertRule(
        rule_id="RULE_GENERAL_THREAT",
        rule_name="General Threat Advisory",
        description="Fallback rule for any confirmed event with sufficient confidence.",
        event_types=[],
        minimum_severity="MODERATE",
        minimum_confidence=settings.ALERT_MIN_CONFIDENCE + 0.10,
        minimum_source_count=settings.ALERT_MIN_SOURCE_COUNT + 1,
        cooldown_seconds=settings.ALERT_DEFAULT_COOLDOWN_SECONDS,
        alert_duration_seconds=settings.ALERT_DEFAULT_TTL_SECONDS,
        escalation_confidence_delta=settings.ALERT_ESCALATION_CONFIDENCE_DELTA,
        escalation_severity_upgrade=True,
        priority=50,
    )
]

def get_active_rules() -> list[AlertRule]:
    """Returns the list of enabled rules."""
    return [r for r in DEFAULT_RULES if r.enabled]

def evaluate_event_against_rules(event: IndraEvent) -> tuple[AlertRule, str] | tuple[None, None]:
    """
    Evaluates an event against all active rules in priority order.
    Returns the first matching rule and the trigger reason.
    """
    rules = sorted(get_active_rules(), key=lambda r: r.priority)
    for rule in rules:
        evaluator = BasicThresholdRule(rule)
        triggered, reason = evaluator.evaluate(event)
        if triggered:
            return rule, reason
    return None, None
