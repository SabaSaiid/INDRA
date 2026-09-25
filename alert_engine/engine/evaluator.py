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
        
        try:
            async for event in self.source.stream():
                try:
                    await self.process_event(event)
                except Exception as e:
                    logger.error(f"evaluator: error processing event {event.id}: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("evaluator: main event loop cancelled")

    async def process_event(self, event):
        """Evaluate a single event and apply necessary state transitions."""
        
        # 1. Rule Evaluation
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

