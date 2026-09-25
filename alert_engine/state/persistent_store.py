"""
INDRA Alert Engine — Persistent Store
Uses a standalone SQLite database to ensure the Alert Engine is entirely
separate from the backend PostgreSQL database.
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite

from alert_engine.config import get_alert_settings
from alert_engine.models import Alert, AlertHistory, AlertStatus, EscalationLevel

logger = logging.getLogger("alert_engine.state.store")
settings = get_alert_settings()


class PersistentStore:
    def __init__(self, db_path: str = settings.ALERT_DB_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Creates tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_code TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    rule_version TEXT,
                    alert_type TEXT,
                    event_type TEXT,
                    severity TEXT,
                    status TEXT,
                    escalation_level TEXT,
                    title TEXT,
                    message TEXT,
                    confidence REAL,
                    source_count INTEGER,
                    evidence JSON,
                    affected_area TEXT,
                    lat REAL,
                    lng REAL,
                    impact_radius_km REAL,
                    mode TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    triggered_at TEXT,
                    resolved_at TEXT,
                    expires_at TEXT,
                    acknowledgement_status TEXT,
                    acknowledged_by TEXT,
                    acknowledged_at TEXT,
                    notification_status TEXT,
                    delivery_attempts INTEGER,
                    fingerprint TEXT UNIQUE
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_event_code ON alerts(event_code);
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    history_id TEXT PRIMARY KEY,
                    alert_id TEXT,
                    previous_status TEXT,
                    new_status TEXT,
                    reason TEXT,
                    timestamp TEXT,
                    triggering_event_id TEXT,
                    rule_id TEXT,
                    actor TEXT,
                    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
                )
            """)
            await db.commit()
            logger.info(f"Initialized SQLite store at {self.db_path}")

    async def save_alert(self, alert: Alert):
        """Insert or replace an alert."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO alerts (
                    alert_id, event_id, event_code, rule_id, rule_version,
                    alert_type, event_type, severity, status, escalation_level,
                    title, message, confidence, source_count, evidence,
                    affected_area, lat, lng, impact_radius_km, mode,
                    created_at, updated_at, triggered_at, resolved_at, expires_at,
                    acknowledgement_status, acknowledged_by, acknowledged_at,
                    notification_status, delivery_attempts, fingerprint
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                alert.alert_id, alert.event_id, alert.event_code, alert.rule_id, alert.rule_version,
                alert.alert_type, alert.event_type, alert.severity, alert.status.value, alert.escalation_level.value,
                alert.title, alert.message, alert.confidence, alert.source_count, json.dumps(alert.evidence),
                alert.affected_area, alert.lat, alert.lng, alert.impact_radius_km, alert.mode,
                alert.created_at.isoformat(), alert.updated_at.isoformat(),
                alert.triggered_at.isoformat() if alert.triggered_at else None,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
                alert.expires_at.isoformat() if alert.expires_at else None,
                alert.acknowledgement_status, alert.acknowledged_by,
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                alert.notification_status, alert.delivery_attempts, alert.fingerprint
            ))
            await db.commit()

    async def save_history(self, history: AlertHistory):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO alert_history (
                    history_id, alert_id, previous_status, new_status,
                    reason, timestamp, triggering_event_id, rule_id, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                history.history_id, history.alert_id, history.previous_status, history.new_status,
                history.reason, history.timestamp.isoformat(), history.triggering_event_id,
                history.rule_id, history.actor
            ))
            await db.commit()

    async def get_alert_by_fingerprint(self, fingerprint: str) -> Optional[Alert]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM alerts WHERE fingerprint = ?", (fingerprint,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_alert(row)
        return None
        
    async def get_active_alert_for_event(self, event_code: str) -> Optional[Alert]:
        """Gets the most recent active/escalated alert for an event code."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Try to find an active/escalated/acknowledged one first
            async with db.execute("""
                SELECT * FROM alerts 
                WHERE event_code = ? AND status IN ('ACTIVE', 'ESCALATED', 'ACKNOWLEDGED')
                ORDER BY updated_at DESC LIMIT 1
            """, (event_code,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_alert(row)
                    
            # Fall back to any alert for this event
            async with db.execute("""
                SELECT * FROM alerts 
                WHERE event_code = ?
                ORDER BY updated_at DESC LIMIT 1
            """, (event_code,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_alert(row)
        return None

    async def list_active_alerts(self, mode: Optional[str] = None) -> List[Alert]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM alerts WHERE status IN ('ACTIVE', 'ESCALATED', 'ACKNOWLEDGED')"
            params = []
            if mode:
                query += " AND mode = ?"
                params.append(mode)
            query += " ORDER BY updated_at DESC"
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_alert(row) for row in rows]

    def _row_to_alert(self, row: aiosqlite.Row) -> Alert:
        return Alert(
            alert_id=row["alert_id"],
            event_id=row["event_id"],
            event_code=row["event_code"],
            rule_id=row["rule_id"],
            rule_version=row["rule_version"],
            alert_type=row["alert_type"],
            event_type=row["event_type"],
            severity=row["severity"],
            status=AlertStatus(row["status"]),
            escalation_level=EscalationLevel(row["escalation_level"]),
            title=row["title"],
            message=row["message"],
            confidence=row["confidence"],
            source_count=row["source_count"],
            evidence=json.loads(row["evidence"]) if row["evidence"] else {},
            affected_area=row["affected_area"],
            lat=row["lat"],
            lng=row["lng"],
            impact_radius_km=row["impact_radius_km"],
            mode=row["mode"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            triggered_at=datetime.fromisoformat(row["triggered_at"]) if row["triggered_at"] else None,
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            acknowledgement_status=row["acknowledgement_status"],
            acknowledged_by=row["acknowledged_by"],
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            notification_status=row["notification_status"],
            delivery_attempts=row["delivery_attempts"],
            fingerprint=row["fingerprint"]
        )
