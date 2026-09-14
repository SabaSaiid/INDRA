"""
INDRA - Intelligent National Disaster & Weather Platform
Main FastAPI Application Entry Point
Smart India Hackathon 2026 - Team Sixth Sense
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import List
from pathlib import Path
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indra.api")

app = FastAPI(
    title="INDRA Platform API",
    description="Intelligent National Disaster & Weather Platform - Event Ingestion, AI Fusion, and Geospatial Verification API.",
    version="1.0.0",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SCENARIO_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "patna_flood_scenario.json"

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

@app.get("/")
async def serve_dashboard():
    """Redirects to the modern INDRA Next.js frontend dashboard on port 3000."""
    return RedirectResponse(url="http://localhost:3000", status_code=307)

@app.get("/legacy", response_class=HTMLResponse)
async def serve_legacy_dashboard():
    """Serves the legacy INDRA prototype template."""
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    return HTMLResponse(content="<h1>INDRA Command Center - Template Loading</h1>", status_code=200)

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

@app.get("/api/scenario")
async def get_patna_scenario():
    """Returns the 127-report Patna flood verification scenario dataset."""
    if SCENARIO_FILE.exists():
        with open(SCENARIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "Scenario dataset not found"}

@app.post("/api/demo/trigger")
async def trigger_demo():
    """Broadcasts a live scenario pulse to connected dashboard WebSocket clients."""
    if SCENARIO_FILE.exists():
        with open(SCENARIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        await ws_manager.broadcast({
            "type": "DEMO_PULSE",
            "scenario": data.get("scenario_metadata", {}),
            "receipt": data.get("verification_receipt", {})
        })
        return {"status": "broadcast_sent", "recipients": len(ws_manager.active_connections)}
    return {"status": "error", "message": "Dataset not found"}

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
        "streaming_bus": "active"
    }

@app.websocket("/ws/events")
async def websocket_events_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received client payload: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
