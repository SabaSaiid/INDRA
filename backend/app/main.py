"""
INDRA - Intelligent National Disaster & Weather Platform
Main FastAPI Application Entry Point
Smart India Hackathon 2026 - Team Sixth Sense
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from typing import List
from pathlib import Path
import json
import logging

from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indra.api")


# ── Lifespan: DB init + background consumer ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup
    logger.info("INDRA Platform starting up...")
    consumer_task = None
    warmup_task = None
    try:
        from app.core.database import init_db
        await init_db()
    except Exception as e:
        logger.warning(f"Database init skipped (non-fatal): {e}")

    # Start Kafka consumer in background (non-blocking)
    try:
        from app.workers.report_consumer import start_report_consumer, set_ws_manager
        set_ws_manager(ws_manager)
        consumer_task = asyncio.create_task(start_report_consumer())
    except Exception as e:
        logger.warning(f"Report consumer startup skipped (non-fatal): {e}")

    # Warm the embedding model, off the event loop, without delaying readiness.
    #
    # MiniLM takes ~13 s to load and encode()'s first call is blocking CPU work.
    # Paid on the first real report it froze the entire API — the T14 cold-start
    # rehearsal saw GET /api/events time out completely, then answer in 0.03 s once
    # the model was resident. Doing it here, in a thread, on a task nobody awaits,
    # means /healthz answers immediately and the first citizen report pays nothing.
    #
    # Failure is deliberately non-fatal: with no model cache and no network, dedup
    # falls back to Levenshtein and the platform still runs.
    async def _warm_embeddings():
        try:
            from app.services.dedup import _get_embedding_model

            model = await asyncio.to_thread(_get_embedding_model)
            if model is None:
                logger.warning(
                    "Embedding model unavailable — dedup will use the Levenshtein "
                    "fallback. Cosine similarity is off for this run."
                )
                return
            # Keyword, not positional: encode()'s second positional argument is
            # prompt_name in sentence-transformers 6.x, so passing True there
            # raised "Prompt name 'True' not found". The warm-up then silently
            # skipped, which the non-fatal WARNING is what caught.
            await asyncio.to_thread(model.encode, "warmup", convert_to_numpy=True)
            logger.info("✓ Embedding model warm — first report will not block")
        except Exception as e:
            logger.warning(f"Embedding warm-up skipped (non-fatal): {e}")

    warmup_task = asyncio.create_task(_warm_embeddings())

    yield

    # Shutdown
    if warmup_task and not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except (asyncio.CancelledError, Exception):
            pass
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    logger.info("INDRA Platform shut down.")


app = FastAPI(
    title="INDRA Platform API",
    description="Intelligent National Disaster & Weather Platform - Event Ingestion, AI Fusion, and Geospatial Verification API.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: an explicit allow-list, not "*".
#
# allow_origins=["*"] with allow_credentials=True is forbidden by the CORS spec,
# and Starlette handles the combination by echoing back whatever Origin it is
# sent -- so every page on the internet could read this API with the viewer's
# credentials attached. The list defaults to the dashboard's dev origins; set
# CORS_ORIGINS in .env to change it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    """Manages real-time WebSocket connections to the Command Center dashboard."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

ws_manager = ConnectionManager()


# ── Mount API Routers ──────────────────────────────────────────────────────────
try:
    from app.api import (
        dashboard_router,
        events_router,
        reports_router,
        feed_router,
        geo_router,
        auth_router,
        teams_router,
        profile_router,
    )
    app.include_router(dashboard_router)
    app.include_router(events_router)
    app.include_router(reports_router)
    app.include_router(feed_router)
    app.include_router(geo_router)
    app.include_router(auth_router)
    app.include_router(teams_router)
    app.include_router(profile_router)
    logger.info("✓ All API routers mounted successfully")
except Exception as e:
    logger.warning(f"⚠ Could not mount API routers (non-fatal): {e}")



# ── Existing Demo Endpoints (preserved) ───────────────────────────────────────

@app.get("/")
async def serve_dashboard():
    """Redirects to the modern INDRA Next.js frontend dashboard on port 3000."""
    return RedirectResponse(url="http://localhost:3000", status_code=307)

# GET /legacy and app/templates/index.html were removed on 20 Sep, for the same
# reason as /api/scenario above: the page claimed telemetry this system does not
# have. "IMD AWS Station 42410 registered 92.4mm rain pulse", "CWC Gauge: Ganga
# level rising 4.2cm/hr at Digha Ghat", "PyTorch Vision detected waist-deep
# floodwater (Prob: 0.91)", "Photo flood_412.jpg verified by PyTorch CV (0.94
# water prob)", "127 Signals". There is no IMD or CWC feed, and vision analysis is
# permanently offline since layer 4 left the scope.
#
# It was a static mockup built before the pipeline existed; it exercised no code
# path and nothing referenced it. The real command center is the Next.js app on
# port 3000, which reads this API.

@app.get("/api/info")
async def platform_info():
    """Returns platform metadata and SIH problem statement details."""
    return {
        "platform": "INDRA",
        "tagline": "From fragmented weather reports to verified, actionable weather events.",
        "version": "1.0.0",
        "status": "operational",
        "sih_ps_id": "SIH26069",
        "team": "Sixth Sense"
    }

# GET /api/scenario and POST /api/demo/trigger were removed on 20 Sep.
#
# They served data/samples/patna_flood_scenario.json as if it were a real
# verified event: 127 signals, confidence 0.94, AUTO_PUBLISHED, CRITICAL, "IMD AWS
# recorded 92mm rainfall", two "CWC river level sensors", ten "verified multimedia
# evidence". Every one of those was fabricated. There is no IMD or CWC feed (no
# API keys, decided 16 Sep), vision analysis is permanently offline since layer 4
# left the scope, and the real pipeline cannot reach 0.94. /api/demo/trigger
# broadcast it to the dashboard over the live WebSocket as a DEMO_PULSE, beside
# genuine VERIFIED_EVENT messages.
#
# Nothing in frontend/ referenced either route, so removing them changed no
# behaviour the dashboard depends on. The demo now runs on the real pipeline --
# see scripts/run_patna_demo.py, which posts reports and reads every number back
# from the API.

@app.get("/healthz")
async def health_check():
    """Real dependency checks — see app/services/health.py. 503 if a critical one is down."""
    from fastapi.responses import JSONResponse
    from app.services.health import run_health_checks

    status_code, body = await run_health_checks()
    return JSONResponse(status_code=status_code, content=body)

@app.websocket("/ws/events")
async def websocket_events_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received client payload: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
