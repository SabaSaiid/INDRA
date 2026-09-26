"""
INDRA Alert Engine — Notifications Dispatcher

Handles three delivery channels:
  1. In-app WebSocket broadcast (always active)
  2. Webhook — actual HTTP delivery to ALERT_WEBHOOK_URL (when configured)
  3. SMTP email — real delivery when SMTP_HOST + credentials are set;
     skipped (not reported as SENT) when unconfigured.

notification_status is only set to SENT when at least one channel
actually delivered the payload successfully.
"""

import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Optional

import httpx

from alert_engine.models import Alert, NotificationStatus
from alert_engine.state.persistent_store import PersistentStore
from alert_engine.config import get_alert_settings

logger = logging.getLogger("alert_engine.notifications")
settings = get_alert_settings()


class NotificationDispatcher:
    def __init__(self, store: PersistentStore):
        self.store = store
        self.clients: set = set()  # Connected WebSocket clients

    async def run(self, queue: asyncio.Queue):
        """Runs in background, taking alerts off the queue and dispatching."""
        logger.info("dispatcher: starting notification loop")
        try:
            while True:
                alert: Alert = await queue.get()
                await self.dispatch(alert)
                queue.task_done()
        except asyncio.CancelledError:
            logger.info("dispatcher: loop cancelled")

    async def dispatch(self, alert: Alert):
        """
        Dispatch the alert to all configured channels.

        The notification_status on the alert is updated truthfully:
          - SENT   — at least one external channel (webhook or email) delivered
          - FAILED — all external channels failed (or none were configured)
          - PENDING — not yet attempted

        WebSocket broadcast is always attempted but does not count toward
        notification_status since it is an in-app channel.
        """
        logger.info(f"dispatcher: dispatching alert {alert.alert_id}")

        # 1. In-app via WebSocket (always)
        await self._broadcast_ws(alert)

        # 2. External channels
        any_external_configured = settings.webhook_configured or settings.email_configured
        delivered = False

        if settings.webhook_configured:
            delivered = await self._send_webhook(alert) or delivered

        if settings.email_configured:
            delivered = await self._send_email(alert) or delivered

        if not any_external_configured:
            # No external channels configured — leave status as PENDING,
            # do NOT report SENT for something we never sent.
            logger.debug(
                "dispatcher: no external channels configured; "
                "notification_status remains PENDING"
            )
        else:
            current_alert = await self.store.get_alert_by_id(alert.alert_id)
            if current_alert:
                current_alert.delivery_attempts += 1
                current_alert.notification_status = (
                    NotificationStatus.SENT if delivered else NotificationStatus.FAILED
                )
                current_alert.updated_at = datetime.now(timezone.utc)
                await self.store.save_alert(current_alert)

    # ── Webhook ────────────────────────────────────────────────────────────────

    async def _send_webhook(self, alert: Alert) -> bool:
        """POST the alert payload to ALERT_WEBHOOK_URL. Returns True on success."""
        url = settings.ALERT_WEBHOOK_URL
        if not url:
            return False

        headers: dict = {"Content-Type": "application/json"}
        if settings.ALERT_WEBHOOK_SECRET:
            import hmac
            import hashlib
            import json
            payload_bytes = json.dumps(alert.to_dict()).encode()
            sig = hmac.new(
                settings.ALERT_WEBHOOK_SECRET.encode(), payload_bytes, hashlib.sha256
            ).hexdigest()
            headers["X-INDRA-Signature"] = f"sha256={sig}"

        retries = settings.ALERT_MAX_RETRIES
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=settings.ALERT_WEBHOOK_TIMEOUT) as client:
                    resp = await client.post(url, json=alert.to_dict(), headers=headers)
                    resp.raise_for_status()
                logger.info(
                    f"dispatcher: webhook delivered to {url} "
                    f"(attempt {attempt}, status={resp.status_code})"
                )
                return True
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    f"dispatcher: webhook HTTP error {exc.response.status_code} "
                    f"(attempt {attempt}/{retries})"
                )
            except Exception as exc:
                logger.warning(
                    f"dispatcher: webhook delivery failed (attempt {attempt}/{retries}): {exc}"
                )
        logger.error(f"dispatcher: webhook exhausted {retries} attempts — giving up")
        return False

    # ── SMTP Email ─────────────────────────────────────────────────────────────

    async def _send_email(self, alert: Alert) -> bool:
        """
        Send an alert email via SMTP. Only called when settings.email_configured is True.
        Runs the blocking SMTP call in a thread-pool executor to avoid blocking the loop.
        Returns True on successful delivery.
        """
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._send_email_sync, alert)
        except Exception as exc:
            logger.error(f"dispatcher: email delivery failed: {exc}")
            return False

    def _send_email_sync(self, alert: Alert) -> bool:
        subject = f"[INDRA Alert] [{alert.severity}] {alert.title}"
        body = (
            f"Alert ID: {alert.alert_id}\n"
            f"Event Code: {alert.event_code}\n"
            f"Severity: {alert.severity}\n"
            f"Status: {alert.status.value}\n"
            f"Area: {alert.affected_area or 'Unknown'}\n"
            f"Confidence: {alert.confidence:.0%}\n"
            f"Message: {alert.message}\n"
            f"Triggered at: {alert.triggered_at.isoformat() if alert.triggered_at else 'N/A'}\n"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.ALERT_EMAIL_FROM
        msg["To"] = ", ".join(settings.ALERT_EMAIL_RECIPIENTS)
        msg.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.sendmail(
                    settings.ALERT_EMAIL_FROM,
                    settings.ALERT_EMAIL_RECIPIENTS,
                    msg.as_string(),
                )
            logger.info(
                f"dispatcher: email sent to {settings.ALERT_EMAIL_RECIPIENTS} "
                f"for alert {alert.alert_id}"
            )
            return True
        except Exception as exc:
            logger.error(f"dispatcher: SMTP error: {exc}")
            return False

    # ── WebSocket broadcast ────────────────────────────────────────────────────

    async def _broadcast_ws(self, alert: Alert):
        if not self.clients:
            return

        data = alert.to_dict()
        disconnected = set()
        for ws in list(self.clients):
            try:
                await ws.send_json({"type": "ALERT_UPDATE", "alert": data})
            except Exception as exc:
                logger.debug(f"dispatcher: ws client error: {exc}")
                disconnected.add(ws)

        self.clients -= disconnected

    def register_client(self, websocket):
        self.clients.add(websocket)
        logger.info(f"dispatcher: client connected, total: {len(self.clients)}")

    def unregister_client(self, websocket):
        self.clients.discard(websocket)
        logger.info(f"dispatcher: client disconnected, total: {len(self.clients)}")
