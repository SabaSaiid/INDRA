"""
INDRA Alert Engine — Main Entry Point

A fully self-contained FastAPI service.
Does NOT modify any existing backend file.
"""

import asyncio
import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alert_engine.config import get_alert_settings
from alert_engine.state.persistent_store import PersistentStore
from alert_engine.engine.evaluator import AlertEvaluator
from alert_engine.notifications.dispatcher import NotificationDispatcher
from alert_engine.api.routes import router, set_globals

settings = get_alert_settings()

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger("alert_engine.main")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="INDRA Alert Engine",
    description=(
        "Additive, real-time alert evaluation engine for INDRA. "
        "Consumes verified events from the INDRA backend and produces "
        "lifecycle-managed alerts with persistence and WebSocket delivery."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Lifecycle ──────────────────────────────────────────────────────────────────

store = PersistentStore(settings.ALERT_DB_PATH)
dispatcher = NotificationDispatcher(store)
evaluator = AlertEvaluator(store)

_background_tasks: list[asyncio.Task] = []


@app.on_event("startup")
async def startup():
    logger.info(f"Alert Engine starting — mode={settings.ALERT_ENGINE_MODE}")

    # Initialize SQLite schema
    await store.init_db()

    # Wire up global dependencies for API routes
    set_globals(store, dispatcher)

    # Start evaluator and dispatcher as background tasks
    eval_task = asyncio.create_task(evaluator.run(), name="evaluator")
    notif_task = asyncio.create_task(dispatcher.run(evaluator.queue), name="dispatcher")
    _background_tasks.extend([eval_task, notif_task])

    logger.info("Alert Engine ready.")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Alert Engine shutting down...")
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    logger.info("Alert Engine shut down cleanly.")


# ── Include router ────────────────────────────────────────────────────────────

app.include_router(router, prefix="/api")


# ── CLI Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "alert_engine.main:app",
        host=settings.ALERT_ENGINE_HOST,
        port=settings.ALERT_ENGINE_PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )
