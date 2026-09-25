"""
INDRA Alert Engine — API Event Source Adapter

Polls the existing INDRA /api/events endpoint.
Used as the primary source in DEMO mode and as fallback when WebSocket is unavailable.

DOES NOT modify the backend. Consumes existing public endpoints only.
"""

import asyncio
import logging
from typing import AsyncIterator, List, Optional
from datetime import datetime, timezone

import httpx

from alert_engine.config import get_alert_settings
from alert_engine.models import IndraEvent

logger = logging.getLogger("alert_engine.adapters.api")
settings = get_alert_settings()


class ApiEventSource:
    """
    Polls GET /api/events at a configurable interval.
    Yields new or updated events based on their verified_at timestamp.
    """

    def __init__(self):
        self._seen_event_ids: set = set()
        self._event_versions: dict = {}  # event_id -> (severity, confidence, source_count)
        self._last_poll: Optional[datetime] = None

    async def poll_once(self) -> List[IndraEvent]:
        """
        Fetch all current events from /api/events.
        Returns list of IndraEvent objects.
        Empty list on any error.
        """
        url = f"{settings.INDRA_API_BASE}/api/events"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            if not isinstance(data, list):
                logger.warning("api_event_source: /api/events did not return a list")
                return []

            events = []
            for item in data:
                try:
                    ev = IndraEvent.from_api_response(item)
                    events.append(ev)
                except Exception as e:
                    logger.warning(f"api_event_source: could not parse event {item.get('id')}: {e}")

            logger.debug(f"api_event_source: fetched {len(events)} events from /api/events")
            self._last_poll = datetime.now(timezone.utc)
            return events

        except httpx.TimeoutException:
            logger.warning("api_event_source: timeout polling /api/events")
        except httpx.HTTPStatusError as e:
            logger.warning(f"api_event_source: HTTP {e.response.status_code} from /api/events")
        except Exception as e:
            logger.error(f"api_event_source: unexpected error polling /api/events: {e}")

        return []

    def classify_event(self, ev: IndraEvent) -> str:
        """
        Classify an event as 'new', 'updated', or 'seen'.
        Used to decide whether to re-evaluate rules.
        """
        if ev.id not in self._seen_event_ids:
            return "new"

        prev = self._event_versions.get(ev.id)
        if prev is None:
            return "new"

        prev_sev, prev_conf, prev_count = prev
        if (
            ev.severity != prev_sev
            or abs(ev.confidence_score - prev_conf) >= 0.05
            or ev.source_count > prev_count
        ):
            return "updated"

        return "seen"

    def mark_seen(self, ev: IndraEvent):
        """Record that we have processed this event version."""
        self._seen_event_ids.add(ev.id)
        self._event_versions[ev.id] = (ev.severity, ev.confidence_score, ev.source_count)

    async def stream(self) -> AsyncIterator[tuple[IndraEvent, str]]:
        """
        Continuously yield (IndraEvent, classification) tuples.
        classification is 'new' or 'updated'.
        Runs until cancelled.
        """
        while True:
            events = await self.poll_once()
            for ev in events:
                classification = self.classify_event(ev)
                if classification in ("new", "updated"):
                    self.mark_seen(ev)
                    yield ev, classification

            await asyncio.sleep(settings.ALERT_POLL_INTERVAL_SECONDS)

    @property
    def last_poll(self) -> Optional[datetime]:
        return self._last_poll
