"""
INDRA Alert Engine — Notifications Dispatcher
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from alert_engine.models import Alert, NotificationStatus, NotificationAttempt
from alert_engine.state.persistent_store import PersistentStore

logger = logging.getLogger("alert_engine.notifications")


class NotificationDispatcher:
    def __init__(self, store: PersistentStore):
        self.store = store
        self.clients = set() # Connected WebSocket clients

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
        """Dispatches the alert to all configured channels (WS, Webhook)."""
        logger.info(f"dispatcher: dispatching alert {alert.alert_id}")
        
        # 1. In-App via WebSocket (Always active)
        await self._broadcast_ws(alert)
        
        # We could implement Webhook / Email here, 
        # but for the core requirement we just need it available in the UI.
        
        # Update alert notification status
        alert.notification_status = NotificationStatus.SENT
        alert.updated_at = datetime.now(timezone.utc)
        await self.store.save_alert(alert)

    async def _broadcast_ws(self, alert: Alert):
        if not self.clients:
            return
            
        data = alert.to_dict()
        # Clean up clients that drop
        disconnected = set()
        for ws in self.clients:
            try:
                await ws.send_json({"type": "ALERT_UPDATE", "alert": data})
            except Exception as e:
                logger.debug(f"dispatcher: error sending to client: {e}")
                disconnected.add(ws)
                
        self.clients -= disconnected

    def register_client(self, websocket):
        self.clients.add(websocket)
        logger.info(f"dispatcher: Client connected, total: {len(self.clients)}")

    def unregister_client(self, websocket):
        if websocket in self.clients:
            self.clients.remove(websocket)
            logger.info(f"dispatcher: Client disconnected, total: {len(self.clients)}")
