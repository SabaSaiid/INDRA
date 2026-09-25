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

    # One Kafka producer for the whole process, instead of one per report.
    # If the broker is down this returns False at once (a TCP probe, not a
    # 40 s client timeout) and the platform starts anyway: reports wait in the
    # outbox until the producer can be started.
    try:
        from app.services.kafka import get_publisher
        await get_publisher().ensure_started()
    except Exception as e:
        logger.warning(f"Kafka producer startup skipped (non-fatal): {e}")

    # Publishes every report the request could not (BUG-060): stored while
    # Kafka was down, or whose immediate publish failed. It also restarts the
    # producer after an outage.
    relay_task = None
    try:
        from app.workers.outbox_relay import start_outbox_relay
        relay_task = asyncio.create_task(start_outbox_relay())
    except Exception as e:
        logger.warning(f"Outbox relay startup skipped (non-fatal): {e}")

    # Authorize and load the frozen local duplicate artifact off the event loop.
    # Startup remains responsive; a load error is logged and duplicate inference
    # itself fails closed if a report later needs the unavailable artifact.
    async def _warm_local_duplicate_matcher():
        try:
            from app.services.dedup import _get_local_matcher

            await asyncio.to_thread(_get_local_matcher)
            logger.info("Frozen local duplicate matcher ready")
        except Exception as e:
            logger.error("Frozen local duplicate matcher unavailable: %s", e)

    warmup_task = asyncio.create_task(_warm_local_duplicate_matcher())

    # The object store's two buckets, created if missing (Phase 2 T1). On a task
    # nobody awaits and wrapped, because the store is non-critical: an absent or
    # unconfigured store logs one line and the platform starts anyway. Writers
    # create a missing bucket themselves, so a store that comes up later is fine.
    async def _ensure_buckets():
        try:
            from app.services import objectstore

            if not objectstore.configured():
                logger.info("Object store not configured (S3_ACCESS_KEY/S3_SECRET_KEY) — lake off")
                return
            created = await objectstore.ensure_buckets()
            logger.info(
                f"✓ Object store ready — buckets {', '.join(objectstore.buckets())}"
                + (f" (created {', '.join(created)})" if created else "")
            )
        except Exception as e:
            logger.warning(f"Object store bucket check skipped (non-fatal): {e}")

    buckets_task = asyncio.create_task(_ensure_buckets())

    # Layer 1's one scheduled external feed: Open-Meteo current precipitation
    # into station_readings, which was empty for the whole project until Day 6.
    poller_task = None
    try:
        from app.workers.station_poller import start_station_poller
        poller_task = asyncio.create_task(start_station_poller())
    except Exception as e:
        logger.warning(f"Station poller startup skipped (non-fatal): {e}")

    # Layer 1's second scheduled feed: NDMA's national CAP feed into
    # agency_alerts. The first evidence in the platform that INDRA did not
    # produce itself — IMD, CWC and state SDMA warnings.
    sachet_task = None
    try:
        from app.workers.sachet_poller import start_sachet_poller
        sachet_task = asyncio.create_task(start_sachet_poller())
    except Exception as e:
        logger.warning(f"SACHET poller startup skipped (non-fatal): {e}")

    # Phase 2 T3: observations from India's aerodromes (METAR) into
    # station_readings. Off unless METAR_POLLER_ENABLED.
    metar_task = None
    try:
        from app.workers.metar_poller import start_metar_poller
        metar_task = asyncio.create_task(start_metar_poller())
    except Exception as e:
        logger.warning(f"METAR poller startup skipped (non-fatal): {e}")

    # Phase 2 T4: posts tagged #IMD and other weather hashtags, from Mastodon.
    mastodon_task = None
    try:
        from app.workers.mastodon_poller import start_mastodon_poller
        mastodon_task = asyncio.create_task(start_mastodon_poller())
    except Exception as e:
        logger.warning(f"Mastodon poller startup skipped (non-fatal): {e}")

    # Phase 2 T5: weather headlines from Google News, English and Hindi.
    news_task = None
    try:
        from app.workers.news_poller import start_news_poller
        news_task = asyncio.create_task(start_news_poller())
    except Exception as e:
        logger.warning(f"Google News poller startup skipped (non-fatal): {e}")

    # Phase 2 T9: every message on the report stream, archived raw to the lake
    # by a second consumer group. Off unless the object store is configured.
    archiver_task = None
    try:
        from app.workers.lake_archiver import start_lake_archiver
        archiver_task = asyncio.create_task(start_lake_archiver())
    except Exception as e:
        logger.warning(f"Lake archiver startup skipped (non-fatal): {e}")

    yield

    # Shutdown
    if not buckets_task.done():
        buckets_task.cancel()
        try:
            await buckets_task
        except (asyncio.CancelledError, Exception):
            pass
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

    # Awaited, not fired and forgotten: an un-awaited cancelled task is what
    # produces "Task was destroyed but it is pending!" on shutdown.
    if poller_task:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass

    if sachet_task:
        sachet_task.cancel()
        try:
            await sachet_task
        except asyncio.CancelledError:
            pass

    for task in (metar_task, mastodon_task, news_task, archiver_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # The relay first, then the producer it publishes through.
    if relay_task:
        relay_task.cancel()
        try:
            await relay_task
        except asyncio.CancelledError:
            pass

    try:
        from app.services.kafka import get_publisher
        await get_publisher().stop()
    except Exception as e:
        logger.warning(f"Kafka producer shutdown skipped (non-fatal): {e}")

    try:
        from app.services import cache
        await cache.close()
    except Exception as e:
        logger.warning(f"Cache shutdown skipped (non-fatal): {e}")
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
    # A browser hides every non-standard response header from the page unless
    # the server names it here. GET /api/events puts its total in X-Total-Count
    # so the body can stay the list the dashboard already parses; the exports
    # (Phase 2 T10) name their file in Content-Disposition.
    expose_headers=["X-Total-Count", "Content-Disposition"],
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
# Deliberately not wrapped in try/except (BUG-063). It used to be, and a router
# that failed to import then unmounted every route while the process ran on:
# /healthz, defined in this file, still answered "healthy" and systemd saw a
# running service, but every dashboard call was a 404. An import error must
# stop the app where the traceback can be read.
from app.api import (
    dashboard_router,
    events_router,
    reports_router,
    feed_router,
    geo_router,
    auth_router,
    teams_router,
    profile_router,
    alerts_router,
    audit_router,
    meta_router,
    stations_router,
    report_search_router,
)
app.include_router(dashboard_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(feed_router)
app.include_router(geo_router)
app.include_router(auth_router)
app.include_router(teams_router)
app.include_router(profile_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(meta_router)
app.include_router(stations_router)
app.include_router(report_search_router)
logger.info("✓ All API routers mounted successfully")



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
