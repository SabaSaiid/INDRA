"""
INDRA Alert Engine — WebSocket Event Source Adapter

Connects to the existing /ws/events WebSocket and receives VERIFIED_EVENT
messages in real time.

DOES NOT modify the backend. Connects to existing public WebSocket endpoint only.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

from alert_engine.config import get_alert_settings
from alert_engine.models import IndraEvent

logger = logging.getLogger("alert_engine.adapters.websocket")
settings = get_alert_settings()

# Exponential backoff settings
MIN_BACKOFF = 2
MAX_BACKOFF = 60


class WebSocketEventSource:
    """
    Connects to ws://localhost:8000/ws/events and processes VERIFIED_EVENT messages.

    Automatically reconnects with exponential backoff.
    Falls back to None yield to signal the consumer to switch to polling.
    """

    def __init__(self):
        self._connected = False
        self._backoff = MIN_BACKOFF

    @property
    def connected(self) -> bool:
        return self._connected

    async def stream(self) -> AsyncIterator[Optional[IndraEvent]]:
        """
        Yield IndraEvent objects from VERIFIED_EVENT WebSocket messages.
        Yields None on connection failure (signal to caller to use fallback).
        """
        try:
            import websockets
        except ImportError:
            logger.warning(
                "websockets library not installed; WebSocket source unavailable. "
                "Install with: pip install websockets"
            )
            yield None
            return

        while True:
            try:
                logger.info(f"ws_event_source: connecting to {settings.INDRA_WS_URL}")
                async with websockets.connect(
                    settings.INDRA_WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._connected = True
                    self._backoff = MIN_BACKOFF
                    logger.info("ws_event_source: connected to INDRA backend WebSocket")

                    async for raw_message in ws:
                        try:
                            msg = json.loads(raw_message)
                            msg_type = msg.get("type")

                            if msg_type == "VERIFIED_EVENT":
                                event_data = msg.get("event")
                                if event_data:
                                    ev = IndraEvent.from_ws_verified_event(event_data)
                                    if ev.id:
                                        logger.info(
                                            f"ws_event_source: received VERIFIED_EVENT "
                                            f"{ev.event_code} severity={ev.severity} "
                                            f"confidence={ev.confidence_score}"
                                        )
                                        yield ev

                            elif msg_type == "DEMO_PULSE":
                                # Demo pulse carries scenario metadata; no event to process
                                logger.debug("ws_event_source: received DEMO_PULSE (no event)")

                            # NEW_REPORT messages carry raw report data, not VerifiedEvents
                            # We skip them here; the pipeline processes them into events

                        except json.JSONDecodeError as e:
                            logger.warning(f"ws_event_source: malformed message: {e}")
                        except Exception as e:
                            logger.error(f"ws_event_source: error processing message: {e}")

            except (OSError, ConnectionRefusedError, Exception) as e:
                self._connected = False
                if "1006" in str(e) or "Connection" in str(e) or "refused" in str(e).lower():
                    logger.info(
                        f"ws_event_source: backend WebSocket unavailable "
                        f"(retry in {self._backoff}s)"
                    )
                else:
                    logger.warning(f"ws_event_source: disconnected ({type(e).__name__}: {e}), "
                                   f"retry in {self._backoff}s")

                yield None  # Signal caller to use polling fallback
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, MAX_BACKOFF)
