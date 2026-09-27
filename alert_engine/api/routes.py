"""
INDRA Alert Engine — FastAPI Routes

Exposes the Alert Engine's own REST + WebSocket API on port 8001.
No existing backend routes are modified.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from alert_engine.state.persistent_store import PersistentStore
from alert_engine.engine.lifecycle import LifecycleManager

logger = logging.getLogger("alert_engine.api")

router = APIRouter()


# ── Dependency injection ───────────────────────────────────────────────────────

_store: Optional[PersistentStore] = None
_dispatcher = None


def set_globals(store: PersistentStore, dispatcher):
    global _store, _dispatcher
    _store = store
    _dispatcher = dispatcher


async def get_store() -> PersistentStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Alert Engine store not initialized")
    return _store


# ── Response schemas ───────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    alert_id: str
    event_id: str
    event_code: str
    rule_id: str
    alert_type: str
    event_type: str
    severity: str
    status: str
    escalation_level: str
    title: str
    message: str
    confidence: float
    source_count: int
    evidence: dict
    affected_area: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    impact_radius_km: Optional[float]
    mode: str
    created_at: str
    updated_at: str
    triggered_at: Optional[str]
    resolved_at: Optional[str]
    acknowledgement_status: str
    acknowledged_by: Optional[str]
    notification_status: str

    model_config = {"from_attributes": True}


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str


class ResolveRequest(BaseModel):
    reason: str
    resolved_by: str = "operator"


# ── REST Endpoints ─────────────────────────────────────────────────────────────

@router.get("/health", tags=["health"])
async def health():
    """Health check for the Alert Engine service."""
    return {
        "status": "ok",
        "service": "indra-alert-engine",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/alerts", response_model=List[dict], tags=["alerts"])
async def list_alerts(
    mode: Optional[str] = Query(None, description="Filter by mode: 'live' or 'demo'"),
    store: PersistentStore = Depends(get_store),
):
    """List all active alerts. Optionally filter by mode (live/demo)."""
    alerts = await store.list_active_alerts(mode=mode)
    return [a.to_dict() for a in alerts]


@router.get("/alerts/{alert_id}", response_model=dict, tags=["alerts"])
async def get_alert(
    alert_id: str,
    store: PersistentStore = Depends(get_store),
):
    """Get a single alert by its ID."""
    alert = await store.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return alert.to_dict()


@router.post("/alerts/{alert_id}/acknowledge", tags=["alerts"])
async def acknowledge_alert(
    alert_id: str,
    body: AcknowledgeRequest,
    store: PersistentStore = Depends(get_store),
):
    """Acknowledge an active alert."""
    alert = await store.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    if alert.status.value not in ("ACTIVE", "ESCALATED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot acknowledge alert in status {alert.status.value}"
        )

    lifecycle = LifecycleManager()
    history = lifecycle.acknowledge_alert(alert, body.acknowledged_by)
    await store.save_alert(alert)
    await store.save_history(history)

    if _dispatcher:
        await _dispatcher.dispatch(alert)

    return {"status": "acknowledged", "alert": alert.to_dict()}


@router.post("/alerts/{alert_id}/resolve", tags=["alerts"])
async def resolve_alert(
    alert_id: str,
    body: ResolveRequest,
    store: PersistentStore = Depends(get_store),
):
    """Manually resolve an alert."""
    alert = await store.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    if alert.status.value in ("RESOLVED", "EXPIRED"):
        raise HTTPException(
            status_code=409,
            detail=f"Alert {alert_id} is already {alert.status.value}"
        )

    lifecycle = LifecycleManager()
    history = lifecycle.resolve_alert(alert, body.reason, actor=body.resolved_by)
    await store.save_alert(alert)
    await store.save_history(history)

    if _dispatcher:
        await _dispatcher.dispatch(alert)

    return {"status": "resolved", "alert": alert.to_dict()}


@router.get("/alerts/{alert_id}/history", tags=["alerts"])
async def get_alert_history(
    alert_id: str,
    store: PersistentStore = Depends(get_store),
):
    """Get the state-transition history for an alert."""
    history = await store.get_alert_history(alert_id)
    return history


@router.get("/stats", tags=["alerts"])
async def alert_stats(store: PersistentStore = Depends(get_store)):
    """Return aggregate alert statistics."""
    stats = await store.get_alert_stats()
    return stats


@router.get("/rules", tags=["rules"])
async def list_rules():
    """Return all active alert rules."""
    from alert_engine.rules.registry import get_active_rules
    rules = get_active_rules()
    return [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "description": r.description,
            "event_types": r.event_types,
            "minimum_severity": r.minimum_severity,
            "minimum_confidence": r.minimum_confidence,
            "minimum_source_count": r.minimum_source_count,
            "cooldown_seconds": r.cooldown_seconds,
            "escalation_confidence_delta": r.escalation_confidence_delta,
            "priority": r.priority,
            "enabled": r.enabled,
        }
        for r in rules
    ]


# ── WebSocket Endpoint ─────────────────────────────────────────────────────────

@router.websocket("/ws/alerts")
async def alert_websocket(websocket: WebSocket):
    """
    Real-time alert WebSocket.
    Pushes ALERT_UPDATE messages whenever an alert is created, escalated, or resolved.
    """
    await websocket.accept()
    logger.info("ws_alerts: client connected")

    if _dispatcher:
        _dispatcher.register_client(websocket)

    try:
        # Send all currently active alerts on connect
        if _store:
            active = await _store.list_active_alerts()
            if active:
                await websocket.send_json({
                    "type": "INITIAL_ALERTS",
                    "alerts": [a.to_dict() for a in active],
                })

        # Keep connection alive — actual messages pushed by dispatcher
        while True:
            await websocket.receive_text()  # Wait for client pings / disconnect

    except WebSocketDisconnect:
        logger.info("ws_alerts: client disconnected")
    finally:
        if _dispatcher:
            _dispatcher.unregister_client(websocket)
