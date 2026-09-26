"""
INDRA Alert Engine — Base Rule Definition
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
from alert_engine.models import IndraEvent, AlertRule


class BaseRuleEvaluator(ABC):
    """
    Abstract base class for rule evaluators.
    """

    def __init__(self, rule_config: AlertRule):
        self.config = rule_config

    def is_applicable(self, event: IndraEvent) -> bool:
        """
        Check if this rule applies to the given event.
        Checks event type, severity, confidence, and source count against thresholds.
        """
        if not self.config.enabled:
            return False

        if not event.is_actionable:
            return False

        if self.config.event_types and event.event_type not in self.config.event_types:
            return False

        from alert_engine.models import severity_gte
        if not severity_gte(event.severity, self.config.minimum_severity):
            return False

        if event.confidence_score < self.config.minimum_confidence:
            return False

        if event.source_count < self.config.minimum_source_count:
            return False

        return True

    @abstractmethod
    def evaluate(self, event: IndraEvent) -> Tuple[bool, Optional[str]]:
        """
        Evaluate the specific condition of this rule.
        Must be implemented by subclasses.
        Returns: (True/False, Trigger Reason)
        """
        pass
