"""
INDRA Alert Engine — Unified Event Source

Coordinates between WebSocket (live) and API (polling) adapters.
"""

import asyncio
import logging
from typing import AsyncIterator

from alert_engine.adapters.api_event_source import ApiEventSource
from alert_engine.adapters.websocket_event_source import WebSocketEventSource
from alert_engine.models import IndraEvent
from alert_engine.config import get_alert_settings

logger = logging.getLogger("alert_engine.adapters.unified")
settings = get_alert_settings()


class UnifiedEventSource:
    """
    Provides a continuous stream of IndraEvents.
    Uses WebSocket when available; falls back to API polling when disconnected.
    """

    def __init__(self):
        self.api_source = ApiEventSource()
        self.ws_source = WebSocketEventSource()
        self.mode = settings.ALERT_ENGINE_MODE
        self.queue: asyncio.Queue[IndraEvent] = asyncio.Queue()

    async def _run_ws(self):
        """Consume WS and push to queue."""
        async for ev in self.ws_source.stream():
            if ev is not None:
                await self.queue.put(ev)

    async def _run_api(self):
        """Consume API polling and push to queue."""
        async for ev, _ in self.api_source.stream():
            await self.queue.put(ev)

    async def stream(self) -> AsyncIterator[IndraEvent]:
        """
        Yields IndraEvent objects indefinitely.
        Handles seamless switching between WebSocket and polling.
        """
        logger.info(f"event_source: starting in {self.mode.upper()} mode")

        if self.mode == "demo":
            # In demo mode, only run polling
            api_task = asyncio.create_task(self._run_api())
            try:
                while True:
                    ev = await self.queue.get()
                    yield ev
            finally:
                api_task.cancel()
        else:
            # Live mode: run both tasks. The WS source handles its own reconnects.
            # When WS is connected, we might still receive poll events (if polling task runs).
            # We can run both, but to prevent duplicates we could just rely on deduplication
            # in the engine, or we could pause API polling. Running both is robust because
            # deduplication handles duplicates anyway.
            ws_task = asyncio.create_task(self._run_ws())
            api_task = asyncio.create_task(self._run_api())
            try:
                while True:
                    ev = await self.queue.get()
                    yield ev
            finally:
                ws_task.cancel()
                api_task.cancel()
