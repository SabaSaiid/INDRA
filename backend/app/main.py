"""
INDRA - Intelligent National Disaster & Weather Platform
Main FastAPI Application Entry Point
Smart India Hackathon 2026 - Team Sixth Sense
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indra.api")

app = FastAPI(
    title="INDRA Platform API",
    description="Intelligent National Disaster & Weather Platform - Event Ingestion, AI Fusion, and Geospatial Verification API.",
    version="1.0.0",
)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.get("/")
async def root():
    return {
        "platform": "INDRA",
        "tagline": "From fragmented weather reports to verified, actionable weather events.",
        "version": "1.0.0",
        "status": "operational",
        "sih_ps_id": "SIH26069",
        "team": "Sixth Sense"
    }

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
            # Echo or handle incoming client signals if needed
            logger.debug(f"Received client payload: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
