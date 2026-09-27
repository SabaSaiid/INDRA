"""
Alert Engine — Unit Tests: Models & Config
"""

import pytest
from alert_engine.models import (
    IndraEvent,
    Alert,
    AlertStatus,
    EscalationLevel,
    VALID_TRANSITIONS,
    is_valid_transition,
    severity_gt,
    severity_gte,
    SEVERITY_ORDER,
)
from alert_engine.config import AlertEngineSettings


class TestSeverityHelpers:
    def test_severity_order_is_ascending(self):
        assert SEVERITY_ORDER["ADVISORY"] < SEVERITY_ORDER["MODERATE"]
        assert SEVERITY_ORDER["MODERATE"] < SEVERITY_ORDER["HIGH"]
        assert SEVERITY_ORDER["HIGH"] < SEVERITY_ORDER["CRITICAL"]

    def test_severity_gt_true(self):
        assert severity_gt("HIGH", "ADVISORY") is True
        assert severity_gt("CRITICAL", "HIGH") is True

    def test_severity_gt_false(self):
        assert severity_gt("ADVISORY", "HIGH") is False
        assert severity_gt("HIGH", "HIGH") is False

    def test_severity_gte(self):
        assert severity_gte("HIGH", "HIGH") is True
        assert severity_gte("CRITICAL", "HIGH") is True
        assert severity_gte("ADVISORY", "HIGH") is False


class TestAlertStatusTransitions:
    def test_normal_can_only_go_to_triggered(self):
        assert is_valid_transition(AlertStatus.NORMAL, AlertStatus.TRIGGERED)
        assert not is_valid_transition(AlertStatus.NORMAL, AlertStatus.ACTIVE)
        assert not is_valid_transition(AlertStatus.NORMAL, AlertStatus.RESOLVED)

    def test_triggered_can_go_active_or_suppressed(self):
        assert is_valid_transition(AlertStatus.TRIGGERED, AlertStatus.ACTIVE)
        assert is_valid_transition(AlertStatus.TRIGGERED, AlertStatus.SUPPRESSED)
        assert not is_valid_transition(AlertStatus.TRIGGERED, AlertStatus.ESCALATED)

    def test_active_can_escalate_acknowledge_resolve_expire(self):
        for target in [AlertStatus.ESCALATED, AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED, AlertStatus.EXPIRED]:
            assert is_valid_transition(AlertStatus.ACTIVE, target), f"ACTIVE -> {target} should be valid"

    def test_resolved_is_terminal(self):
        for target in AlertStatus:
            assert not is_valid_transition(AlertStatus.RESOLVED, target)

    def test_expired_is_terminal(self):
        for target in AlertStatus:
            assert not is_valid_transition(AlertStatus.EXPIRED, target)

    def test_suppressed_is_terminal(self):
        for target in AlertStatus:
            assert not is_valid_transition(AlertStatus.SUPPRESSED, target)


class TestIndraEventFromApiResponse:
    def test_basic_fields_parsed(self):
        data = {
            "id": "abc123",
            "event_code": "INDRA-001",
            "event_type": "URBAN_FLOOD",
            "severity": "critical",  # lowercase — should be uppercased
            "confidence_score": 0.94,
            "review_status": "AUTO_PUBLISHED",
            "quadrant": "Critical Verified Event",
            "impact_radius_km": 6.8,
            "lat": 25.61,
            "lng": 85.14,
            "city": "Patna",
            "state": "Bihar",
            "verified_at": "2026-09-16T10:00:00Z",
            "verification_receipt": {"confidence_score": 0.94, "cluster": {"size": 103}},
        }
        ev = IndraEvent.from_api_response(data)
        assert ev.id == "abc123"
        assert ev.severity == "CRITICAL"   # must be uppercased
        assert ev.confidence_score == 0.94
        assert ev.source_count == 103
        assert ev.raw_source == "api"

    def test_missing_optional_fields_have_safe_defaults(self):
        ev = IndraEvent.from_api_response({"id": "x", "event_code": "y"})
        assert ev.severity == "ADVISORY"
        assert ev.confidence_score == 0.0
        assert ev.source_count == 0
        assert ev.has_geometry is False

    def test_has_geometry_false_when_no_coordinates(self):
        ev = IndraEvent.from_api_response({"id": "x", "event_code": "y"})
        assert not ev.has_geometry

    def test_has_geometry_true_when_coordinates_present(self):
        ev = IndraEvent.from_api_response({"id": "x", "event_code": "y", "lat": 25.0, "lng": 85.0})
        assert ev.has_geometry

    def test_is_actionable_false_for_rejected(self):
        ev = IndraEvent.from_api_response({"id": "x", "event_code": "y", "review_status": "REJECTED"})
        assert not ev.is_actionable

    def test_is_actionable_false_for_noise(self):
        ev = IndraEvent.from_api_response({"id": "x", "event_code": "y", "quadrant": "Noise"})
        assert not ev.is_actionable

    def test_from_ws_verified_event(self):
        data = {
            "id": "ws-001",
            "event_code": "INDRA-WS-001",
            "event_type": "CLOUDBURST",
            "severity": "HIGH",
            "confidence_score": 0.85,
            "review_status": "AUTO_PUBLISHED",
            "verified_at": "2026-09-16T10:00:00Z",
            "verification_receipt": {"cluster": {"size": 12}},
        }
        ev = IndraEvent.from_ws_verified_event(data)
        assert ev.source_count == 12
        assert ev.raw_source == "websocket"


class TestAlertConfig:
    def test_default_settings(self):
        s = AlertEngineSettings()
        assert s.ALERT_ENGINE_PORT == 8001
        assert s.ALERT_MIN_CONFIDENCE == 0.70
        assert s.ALERT_MIN_SOURCE_COUNT == 2
        assert s.ALERT_ENGINE_MODE == "demo"

    def test_email_not_configured_by_default(self):
        s = AlertEngineSettings()
        assert not s.email_configured

    def test_webhook_not_configured_by_default(self):
        s = AlertEngineSettings()
        assert not s.webhook_configured
