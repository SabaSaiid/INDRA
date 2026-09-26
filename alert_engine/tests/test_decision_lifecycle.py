"""
Alert Engine — Unit Tests: Decision Engine & Lifecycle
"""

import pytest
from datetime import datetime, timezone, timedelta

from alert_engine.engine.decision import evaluate_decision, DecisionType, AlertDecision
from alert_engine.engine.lifecycle import LifecycleManager
from alert_engine.models import AlertStatus, EscalationLevel
from alert_engine.rules.registry import get_active_rules


def _make_active_alert(patna_event, rule=None):
    """Helper: create a real ACTIVE alert from the Patna event."""
    rule = rule or get_active_rules()[0]
    lifecycle = LifecycleManager()
    alert, history = lifecycle.create_alert(patna_event, rule, "Test trigger")
    return alert, history, rule


class TestDecisionEngine:
    def test_no_rule_match_no_existing_alert_gives_no_action(self, advisory_event):
        decision = evaluate_decision(advisory_event, None, None, None)
        assert decision.type == DecisionType.NO_ACTION

    def test_no_rule_match_with_active_alert_gives_resolve(self, patna_event, advisory_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        # Now advisory_event comes in, no rule matches — existing alert should be resolved
        decision = evaluate_decision(advisory_event, None, None, alert)
        assert decision.type == DecisionType.RESOLVE

    def test_rule_match_no_existing_alert_gives_create(self, patna_event):
        rule = get_active_rules()[0]
        decision = evaluate_decision(patna_event, rule, "Test", None)
        assert decision.type == DecisionType.CREATE
        assert decision.rule == rule

    def test_rule_match_with_active_alert_same_severity_gives_update_or_no_action(self, patna_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        # Same severity, same confidence — no meaningful change
        decision = evaluate_decision(patna_event, rule, "Test", alert)
        assert decision.type in (DecisionType.NO_ACTION, DecisionType.UPDATE)

    def test_severity_increase_triggers_escalation(self, patna_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        alert.severity = "HIGH"   # manually lower severity to simulate previous state
        alert.status = AlertStatus.ACTIVE

        # Now come in with CRITICAL — should escalate
        decision = evaluate_decision(patna_event, rule, "Test", alert)
        assert decision.type == DecisionType.ESCALATE
        assert decision.escalation_level == EscalationLevel.LEVEL_1

    def test_confidence_increase_triggers_escalation(self, patna_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        alert.confidence = 0.70   # force a lower confidence in the existing alert
        alert.status = AlertStatus.ACTIVE

        patna_event.confidence_score = 0.94  # delta = 0.24 > escalation threshold (0.10)
        decision = evaluate_decision(patna_event, rule, "Test", alert)
        assert decision.type == DecisionType.ESCALATE
        assert decision.escalation_level == EscalationLevel.LEVEL_2

    def test_resolved_alert_within_cooldown_gives_no_action(self, patna_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        alert.status = AlertStatus.RESOLVED
        alert.updated_at = datetime.now(timezone.utc)  # just resolved

        decision = evaluate_decision(patna_event, rule, "Test", alert)
        assert decision.type == DecisionType.NO_ACTION

    def test_resolved_alert_past_cooldown_gives_create(self, patna_event):
        rule = get_active_rules()[0]
        alert, _, _ = _make_active_alert(patna_event, rule)
        alert.status = AlertStatus.RESOLVED
        # Set updated_at to well past the cooldown period
        alert.updated_at = datetime.now(timezone.utc) - timedelta(seconds=rule.cooldown_seconds + 60)

        decision = evaluate_decision(patna_event, rule, "Test", alert)
        assert decision.type == DecisionType.CREATE


class TestLifecycleManager:
    def test_create_alert_returns_alert_and_history(self, patna_event):
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, history = lifecycle.create_alert(patna_event, rule, "Rule matched")

        assert alert.alert_id.startswith("ALT-")
        assert alert.status == AlertStatus.ACTIVE
        assert alert.event_code == patna_event.event_code
        assert alert.rule_id == rule.rule_id
        assert alert.confidence == patna_event.confidence_score
        assert alert.source_count == patna_event.source_count
        assert alert.fingerprint != ""
        assert len(alert.fingerprint) == 64

        assert history.previous_status == "NONE"
        assert history.new_status == AlertStatus.ACTIVE.value
        assert history.actor == "system"

    def test_escalate_alert_updates_status(self, patna_event):
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, _ = lifecycle.create_alert(patna_event, rule, "Initial")
        alert.severity = "HIGH"

        history = lifecycle.escalate_alert(alert, patna_event, "LEVEL_1", "Severity increased")
        assert alert.status == AlertStatus.ESCALATED
        assert alert.escalation_level == EscalationLevel.LEVEL_1
        assert history.previous_status == AlertStatus.ACTIVE.value
        assert history.new_status == AlertStatus.ESCALATED.value

    def test_resolve_alert_sets_terminal_state(self, patna_event):
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, _ = lifecycle.create_alert(patna_event, rule, "Initial")

        history = lifecycle.resolve_alert(alert, "Manual resolution", actor="operator")
        assert alert.status == AlertStatus.RESOLVED
        assert alert.resolved_at is not None
        assert history.actor == "operator"
        assert history.new_status == AlertStatus.RESOLVED.value

    def test_acknowledge_alert_sets_acknowledged_state(self, patna_event):
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, _ = lifecycle.create_alert(patna_event, rule, "Initial")

        history = lifecycle.acknowledge_alert(alert, "analyst@indra.gov")
        assert alert.status == AlertStatus.ACKNOWLEDGED
        assert alert.acknowledged_by == "analyst@indra.gov"
        assert alert.acknowledged_at is not None
        assert history.new_status == AlertStatus.ACKNOWLEDGED.value

    def test_alert_title_derived_from_event(self, patna_event):
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, _ = lifecycle.create_alert(patna_event, rule, "Test")
        # Title must contain actual event data, not a hardcoded string
        assert patna_event.severity in alert.title
        assert patna_event.event_type in alert.title

    def test_alert_to_dict_is_serializable(self, patna_event):
        import json
        rule = get_active_rules()[0]
        lifecycle = LifecycleManager()
        alert, _ = lifecycle.create_alert(patna_event, rule, "Test")
        d = alert.to_dict()
        # Must be JSON-serializable
        serialized = json.dumps(d)
        assert "alert_id" in serialized
        assert alert.alert_id in serialized
