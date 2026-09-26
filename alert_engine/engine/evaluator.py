"""
INDRA Alert Engine — Top-Level Evaluator
"""

import asyncio
import logging

from alert_engine.adapters.event_source import UnifiedEventSource
from alert_engine.rules.registry import evaluate_event_against_rules
from alert_engine.engine.decision import evaluate_decision, DecisionType
from alert_engine.engine.lifecycle import LifecycleManager
from alert_engine.state.persistent_store import PersistentStore

logger = logging.getLogger("alert_engine.engine.evaluator")


class AlertEvaluator:
    def __init__(self, store: PersistentStore):
        self.source = UnifiedEventSource()
        self.store = store
        self.lifecycle = LifecycleManager()
        self.queue: asyncio.Queue = asyncio.Queue()  # For outgoing alerts to notify

    async def run(self):
        """Runs the main evaluation loop indefinitely."""
        logger.info("evaluator: starting main event loop")
        
        expiry_task = asyncio.create_task(self._expiry_worker())
        
        try:
            async for event in self.source.stream():
                try:
                    await self.process_event(event)
                except Exception as e:
                    logger.error(f"evaluator: error processing event {event.id}: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("evaluator: main event loop cancelled")
        finally:
            expiry_task.cancel()

    async def _expiry_worker(self):
        """Periodically checks for and resolves expired alerts."""
        from datetime import datetime, timezone
        from alert_engine.models import AlertStatus
        
        while True:
            try:
                await asyncio.sleep(60) # Check every minute
                now = datetime.now(timezone.utc)
                active_alerts = await self.store.list_active_alerts()
                
                for alert in active_alerts:
                    if alert.expires_at and alert.expires_at <= now:
                        logger.info(f"evaluator: Alert {alert.alert_id} has expired.")
                        history = self.lifecycle.resolve_alert(alert, "Alert expired (TTL reached)", actor="system")
                        alert.status = AlertStatus.EXPIRED
                        await self.store.save_alert(alert)
                        await self.store.save_history(history)
                        await self.queue.put(alert)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"evaluator: error in expiry worker: {e}", exc_info=True)

    async def process_event(self, event):
        """Evaluate a single event and apply necessary state transitions."""
        
        # 1. Review Status Policy Check (Phase 5)
        # We NEVER trigger alerts for unreviewed, pending, quarantined, or rejected events.
        eligible_states = {"AUTO_PUBLISHED", "HUMAN_APPROVED"}
        if event.review_status not in eligible_states:
            logger.debug(f"evaluator: Event {event.event_code} skipped due to review status {event.review_status}")
            return
            
        # 2. Rule Evaluation
        matched_rule, trigger_reason = evaluate_event_against_rules(event)

        # 2. Get existing alert (if any)
        # We lookup by event_code since multiple rules might theoretically match over time,
        # but INDRA events are 1:1 with Alerts in our simplified model.
        existing_alert = await self.store.get_active_alert_for_event(event.event_code)
        
        # 3. Decision
        decision = evaluate_decision(event, matched_rule, trigger_reason, existing_alert)
        
        logger.debug(f"evaluator: Event {event.event_code} -> Decision: {decision.type.value}")
        
        # 4. Action
        if decision.type == DecisionType.NO_ACTION:
            return

        if decision.type == DecisionType.CREATE:
            alert, history = self.lifecycle.create_alert(event, decision.rule, decision.reason)
            
            # Check for strict deduplication (if identical fingerprint already exists)
            # This happens if polling overlaps or cooldown is active.
            # The decision engine handles cooldown, but double check DB constraint logic.
            dup = await self.store.get_alert_by_fingerprint(alert.fingerprint)
            if dup and dup.status in ("ACTIVE", "ESCALATED", "ACKNOWLEDGED"):
                logger.debug(f"evaluator: Suppressing exact duplicate for {alert.fingerprint}")
                return
                
            await self.store.save_alert(alert)
            await self.store.save_history(history)
            await self.queue.put(alert)

        elif decision.type == DecisionType.UPDATE:
            history = self.lifecycle.update_alert(decision.existing_alert, event, decision.reason)
            await self.store.save_alert(decision.existing_alert)
            if history:
                await self.store.save_history(history)
            # We broadcast routine updates too so UI is real-time
            await self.queue.put(decision.existing_alert)

        elif decision.type == DecisionType.ESCALATE:
            history = self.lifecycle.escalate_alert(
                decision.existing_alert, 
                event, 
                decision.escalation_level.value, 
                decision.reason
            )
            await self.store.save_alert(decision.existing_alert)
            await self.store.save_history(history)
            await self.queue.put(decision.existing_alert)
            
        elif decision.type == DecisionType.RESOLVE:
            history = self.lifecycle.resolve_alert(decision.existing_alert, decision.reason)
            await self.store.save_alert(decision.existing_alert)
            await self.store.save_history(history)
            await self.queue.put(decision.existing_alert)

