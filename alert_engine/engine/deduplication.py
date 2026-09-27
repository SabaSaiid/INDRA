"""
INDRA Alert Engine — Deduplication
"""

import hashlib
from typing import Optional
from alert_engine.models import IndraEvent, AlertRule


def generate_fingerprint(event: IndraEvent, rule: AlertRule) -> str:
    """
    Generates a deterministic fingerprint for an event-rule combination.
    This ensures that multiple polls of the same event don't create multiple alerts.
    """
    # Event code is globally unique for an INDRA event.
    base = f"{event.event_code}|{rule.rule_id}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
