"""
INDRA Alert Engine — Configuration

All values loaded from environment variables.
No production thresholds hardcoded.
"""

import os
from functools import lru_cache
from typing import Optional


class AlertEngineSettings:
    """
    Alert Engine configuration loaded from environment variables.
    All settings have safe defaults for development/demo.
    """

    def __init__(self):
        # ── Core ───────────────────────────────────────────────────────────────
        self.ALERT_ENGINE_ENABLED: bool = self._bool("ALERT_ENGINE_ENABLED", True)
        self.ALERT_ENGINE_MODE: str = os.getenv("ALERT_ENGINE_MODE", "demo")
        # Port for the Alert Engine's own FastAPI service
        self.ALERT_ENGINE_PORT: int = int(os.getenv("ALERT_ENGINE_PORT", "8001"))
        self.ALERT_ENGINE_HOST: str = os.getenv("ALERT_ENGINE_HOST", "0.0.0.0")

        # ── Source — INDRA Backend ─────────────────────────────────────────────
        self.INDRA_API_BASE: str = os.getenv("INDRA_API_BASE", "http://localhost:8000")
        self.INDRA_WS_URL: str = os.getenv("INDRA_WS_URL", "ws://localhost:8000/ws/events")

        # ── Polling ────────────────────────────────────────────────────────────
        # How often to poll /api/events when WebSocket is unavailable
        self.ALERT_POLL_INTERVAL_SECONDS: int = int(
            os.getenv("ALERT_POLL_INTERVAL_SECONDS", "15")
        )

        # ── Alert Lifecycle ────────────────────────────────────────────────────
        # Cooldown: minimum seconds between repeated alerts for same event+rule
        self.ALERT_DEFAULT_COOLDOWN_SECONDS: int = int(
            os.getenv("ALERT_DEFAULT_COOLDOWN_SECONDS", "300")
        )
        # TTL: how long an active alert lives before auto-expiring
        self.ALERT_DEFAULT_TTL_SECONDS: int = int(
            os.getenv("ALERT_DEFAULT_TTL_SECONDS", "3600")
        )
        # Grace period before resolving/expiring a stale alert
        self.ALERT_STALE_GRACE_SECONDS: int = int(
            os.getenv("ALERT_STALE_GRACE_SECONDS", "120")
        )

        # ── Rule Thresholds ────────────────────────────────────────────────────
        self.ALERT_MIN_CONFIDENCE: float = float(
            os.getenv("ALERT_MIN_CONFIDENCE", "0.70")
        )
        self.ALERT_ESCALATION_CONFIDENCE_DELTA: float = float(
            os.getenv("ALERT_ESCALATION_CONFIDENCE_DELTA", "0.10")
        )
        self.ALERT_CRITICAL_CONFIDENCE: float = float(
            os.getenv("ALERT_CRITICAL_CONFIDENCE", "0.90")
        )

        # Minimum source_count (cluster size) to trigger an alert
        self.ALERT_MIN_SOURCE_COUNT: int = int(os.getenv("ALERT_MIN_SOURCE_COUNT", "2"))

        # ── Persistence ────────────────────────────────────────────────────────
        self.ALERT_DB_PATH: str = os.getenv("ALERT_DB_PATH", "alert_engine.db")

        # ── Notifications — Webhook ────────────────────────────────────────────
        self.ALERT_WEBHOOK_URL: Optional[str] = os.getenv("ALERT_WEBHOOK_URL") or None
        self.ALERT_WEBHOOK_SECRET: Optional[str] = (
            os.getenv("ALERT_WEBHOOK_SECRET") or None
        )
        self.ALERT_WEBHOOK_TIMEOUT: int = int(os.getenv("ALERT_WEBHOOK_TIMEOUT", "10"))
        self.ALERT_MAX_RETRIES: int = int(os.getenv("ALERT_MAX_RETRIES", "3"))

        # ── Notifications — Email (SMTP) ───────────────────────────────────────
        self.SMTP_HOST: Optional[str] = os.getenv("SMTP_HOST") or None
        self.SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME: Optional[str] = os.getenv("SMTP_USERNAME") or None
        self.SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD") or None
        self.ALERT_EMAIL_FROM: Optional[str] = os.getenv("ALERT_EMAIL_FROM") or None
        self.ALERT_EMAIL_RECIPIENTS: list[str] = [
            r.strip()
            for r in os.getenv("ALERT_EMAIL_RECIPIENTS", "").split(",")
            if r.strip()
        ]

        # ── Logging ────────────────────────────────────────────────────────────
        self.LOG_LEVEL: str = os.getenv("ALERT_LOG_LEVEL", "INFO")

    @staticmethod
    def _bool(key: str, default: bool) -> bool:
        val = os.getenv(key)
        if val is None:
            return default
        return val.lower() in ("1", "true", "yes", "on")

    @property
    def email_configured(self) -> bool:
        return bool(
            self.SMTP_HOST
            and self.SMTP_USERNAME
            and self.SMTP_PASSWORD
            and self.ALERT_EMAIL_FROM
            and self.ALERT_EMAIL_RECIPIENTS
        )

    @property
    def webhook_configured(self) -> bool:
        return bool(self.ALERT_WEBHOOK_URL)


@lru_cache()
def get_alert_settings() -> AlertEngineSettings:
    return AlertEngineSettings()
