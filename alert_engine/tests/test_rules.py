"""
Alert Engine — Unit Tests: Rules & Deduplication
"""

import pytest
from alert_engine.rules.registry import get_active_rules, evaluate_event_against_rules
from alert_engine.engine.deduplication import generate_fingerprint


class TestRuleRegistry:
    def test_active_rules_are_returned(self):
        rules = get_active_rules()
        assert len(rules) >= 1

    def test_all_active_rules_are_enabled(self):
        for rule in get_active_rules():
            assert rule.enabled is True

    def test_rules_have_required_fields(self):
        for rule in get_active_rules():
            assert rule.rule_id
            assert rule.rule_name
            assert rule.minimum_severity in ("ADVISORY", "MODERATE", "HIGH", "CRITICAL")
            assert 0.0 <= rule.minimum_confidence <= 1.0
            assert rule.minimum_source_count >= 0
            assert rule.cooldown_seconds > 0
            assert rule.priority > 0

    def test_rules_sorted_by_priority_ascending(self):
        rules = get_active_rules()
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities)


class TestRuleEvaluation:
    def test_critical_high_confidence_event_matches(self, patna_event):
        rule, reason = evaluate_event_against_rules(patna_event)
        assert rule is not None
        assert reason is not None
        assert "CRITICAL" in rule.rule_name or rule.minimum_severity == "CRITICAL"

    def test_low_confidence_advisory_does_not_match(self, advisory_event):
        rule, reason = evaluate_event_against_rules(advisory_event)
        assert rule is None
        assert reason is None

    def test_noise_quadrant_does_not_match(self, advisory_event):
        # advisory_event already has quadrant=Noise — confirm is_actionable blocks it
        assert not advisory_event.is_actionable
        rule, _ = evaluate_event_against_rules(advisory_event)
        assert rule is None

    def test_rejected_event_does_not_match(self, patna_event):
        patna_event.review_status = "REJECTED"
        rule, _ = evaluate_event_against_rules(patna_event)
        assert rule is None

    def test_event_below_source_threshold_does_not_match(self, patna_event):
        # Override source_count to 0 — below every rule's minimum
        patna_event.source_count = 0
        # The general threshold rule requires at least 3 sources
        # Critical rule requires ALERT_MIN_SOURCE_COUNT (default 2)
        # With source_count=0, none should match
        patna_event.source_count = 0
        # Even with source_count=0 default threshold is 2, so it should fail
        rule, _ = evaluate_event_against_rules(patna_event)
        # With 0 sources and min=2, it must fail
        assert rule is None

    def test_high_confidence_flood_matches_flood_rule(self, patna_event):
        # patna_event is URBAN_FLOOD, CRITICAL, 0.94 confidence — should match
        rule, reason = evaluate_event_against_rules(patna_event)
        assert rule is not None
        # Should be the highest-priority rule first
        assert rule.priority == min(r.priority for r in get_active_rules())


class TestDeduplication:
    def test_same_event_and_rule_produce_same_fingerprint(self, patna_event):
        rules = get_active_rules()
        rule = rules[0]
        fp1 = generate_fingerprint(patna_event, rule)
        fp2 = generate_fingerprint(patna_event, rule)
        assert fp1 == fp2

    def test_different_rules_produce_different_fingerprints(self, patna_event):
        rules = get_active_rules()
        if len(rules) < 2:
            pytest.skip("Need at least 2 rules")
        fp1 = generate_fingerprint(patna_event, rules[0])
        fp2 = generate_fingerprint(patna_event, rules[1])
        assert fp1 != fp2

    def test_different_events_produce_different_fingerprints(self, patna_event, advisory_event):
        rules = get_active_rules()
        rule = rules[0]
        fp1 = generate_fingerprint(patna_event, rule)
        fp2 = generate_fingerprint(advisory_event, rule)
        assert fp1 != fp2

    def test_fingerprint_is_hex_string(self, patna_event):
        rules = get_active_rules()
        fp = generate_fingerprint(patna_event, rules[0])
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest
        int(fp, 16)           # must be a valid hex string
