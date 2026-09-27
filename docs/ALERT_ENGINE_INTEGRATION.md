# INDRA Alert Engine — Integration Architecture

## 1. Repository Audit Summary

### 1.1 How VerifiedEvents Are Produced

```
RawReport submitted → Kafka topic (indra.raw.reports)
        │
        ▼
report_consumer.py (aiokafka consumer, background asyncio task)
        │
        ▼
pipeline.py::process_report()
  ├── dedup.py (DedupService)
  ├── geo_clustering.py (GeoClusteringService — DBSCAN)
  └── fusion_engine.py (FusionEngine — 6-factor confidence receipt)
        │
        ▼
verified_events table (PostgreSQL + PostGIS)
        │
        ▼
WebSocket broadcast: type="VERIFIED_EVENT" on /ws/events
```

### 1.2 VerifiedEvent Schema (confirmed from source)

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| event_code | String(20) | UNIQUE, e.g. INDRA-20260915-001 |
| event_type | Enum | URBAN_FLOOD, CLOUDBURST, CYCLONE_INUNDATION, RIVER_BREACH |
| severity | Enum | ADVISORY, MODERATE, HIGH, CRITICAL |
| confidence_score | Float 0-1 | 6-factor fusion score |
| review_status | Enum | AUTO_PUBLISHED, PENDING_HUMAN_REVIEW, QUARANTINED, REJECTED |
| quadrant | Enum | Critical Verified Event, Unverified Threat, Confirmed Minor Event, Noise |
| impact_radius_km | Float | Spatial footprint |
| center_point | PostGIS POINT | WGS-84 |
| boundary_polygon | PostGIS POLYGON | WGS-84 |
| verification_receipt | JSONB | 6 factors + cluster stats + provenance |
| verified_at | DateTime TZ | Creation / last update time |

### 1.3 Existing API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /api/events | List events |
| GET | /api/events/{id} | Single event detail |
| GET | /api/dashboard/summary | KPI counts |
| GET | /api/scenario | Golden Patna scenario |
| WS | /ws/events | Real-time event stream |

### 1.4 WebSocket Messages from Existing Backend

| Type | When |
|---|---|
| NEW_REPORT | Every raw report from Kafka |
| VERIFIED_EVENT | Every created/updated VerifiedEvent |
| DEMO_PULSE | POST /api/demo/trigger |

## 2. Integration Strategy

The existing backend already exposes everything the Alert Engine needs via its public API and WebSocket. The Alert Engine is a **completely separate service** that:
- Consumes existing events via WebSocket or REST polling
- Persists its own state in a separate SQLite database
- Runs on its own port (8001)
- Never modifies any existing backend file

## 3. Alert Engine Data Flow

```
INDRA Backend (/ws/events or GET /api/events)
        │
        ▼
alert_engine/adapters/ (WebSocket + API adapters)
        │
        ▼
alert_engine/engine/evaluator.py (Rule evaluation)
        │
        ▼
alert_engine/engine/decision.py (CREATE/UPDATE/ESCALATE/SUPPRESS)
        │
        ▼
alert_engine/engine/deduplication.py (Fingerprint check)
        │
        ▼
alert_engine/state/persistent_store.py (SQLite)
        │
        ├── alert_engine/api/routes.py (REST + WebSocket /ws/alerts)
        └── alert_engine/notifications/dispatcher.py
```

## 4. Alert Lifecycle States

NORMAL → TRIGGERED → ACTIVE → ESCALATED
                                    │
                    ACKNOWLEDGED ←──┤
                    RESOLVED     ←──┤
                    EXPIRED      ←──┤
                    SUPPRESSED   ←──┘

## 5. Failure Handling

| Failure | Behavior |
|---|---|
| Backend WS disconnects | Switch to polling, reconnect with backoff |
| Backend API unavailable | Serve persisted alerts, retry |
| SQLite unavailable | In-memory fallback, log error |
| Webhook timeout | Retry with exponential backoff |
| Malformed event | Log, skip, continue |
| Missing confidence | Use 0.0, ADVISORY only |
| Duplicate event | Suppress, update existing alert |
