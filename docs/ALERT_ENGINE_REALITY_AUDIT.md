# INDRA Alert Engine — Reality Audit

This document provides an honest, evidence-grounded comparison of every subsystem
in the Alert Engine against the question: **is this component real or a stub?**

---

## Audit Table

| Component | Status | Evidence | Real or Mock? |
|---|---|---|---|
| **Event ingestion — WebSocket** | ✅ Implemented | `adapters/websocket_event_source.py` connects to `ws://localhost:8000/ws/events` and processes `VERIFIED_EVENT` messages | **REAL** — reads actual backend stream |
| **Event ingestion — REST polling** | ✅ Implemented | `adapters/api_event_source.py` polls `GET /api/events` at configurable interval | **REAL** — reads actual API |
| **Unified source routing** | ✅ Implemented | `adapters/event_source.py` coordinates WS (primary) + REST (fallback) via asyncio Queue | **REAL** |
| **Event normalization** | ✅ Implemented | `IndraEvent.from_api_response()` and `from_ws_verified_event()` parse real field names confirmed against backend source | **REAL** — maps actual fields |
| **Rule evaluation** | ✅ Implemented | `rules/registry.py` evaluates severity, confidence_score, source_count thresholds from env config | **REAL** — no hardcoded pass |
| **Rule definitions** | ✅ Implemented | 3 default rules (CRITICAL, FLOOD-HIGH, GENERAL) with configurable thresholds | **REAL** — env-driven, extendable |
| **Decision engine** | ✅ Implemented | `engine/decision.py` evaluates CREATE/UPDATE/ESCALATE/RESOLVE/NO_ACTION based on severity delta and confidence delta | **REAL** — deterministic logic |
| **Deduplication** | ✅ Implemented | `engine/deduplication.py` generates SHA-256 fingerprint from event_code + rule_id | **REAL** — prevents duplicate alerts |
| **Alert lifecycle** | ✅ Implemented | `engine/lifecycle.py` manages transitions: NORMAL→ACTIVE→ESCALATED→RESOLVED | **REAL** — enforces valid transitions |
| **Persistence** | ✅ Implemented | `state/persistent_store.py` writes to SQLite (`alert_engine.db`) with separate `alerts` and `alert_history` tables | **REAL** — survives restart |
| **State recovery** | ✅ Implemented | SQLite reads on startup, no in-memory-only state | **REAL** |
| **REST API** | ✅ Implemented | `api/routes.py` — GET /alerts, GET /alerts/{id}, POST /acknowledge, POST /resolve, GET /history, GET /stats, GET /rules | **REAL** endpoints |
| **WebSocket push** | ✅ Implemented | `GET /ws/alerts` — sends INITIAL_ALERTS on connect, pushes ALERT_UPDATE on every state change | **REAL** |
| **Notification — In-App** | ✅ Implemented | `notifications/dispatcher.py` broadcasts via WebSocket to all connected clients | **REAL** |
| **Notification — Webhook** | 📋 Scaffolded | Dispatcher scaffold present; HTTP POST not yet implemented | **STUB** — env configured but not executed |
| **Notification — Email** | 📋 Configured | Settings in `config.py`; SMTP send not yet implemented | **STUB** — settings present only |
| **Frontend API layer** | ✅ Implemented | `api.ts` — `fetchEngineAlerts`, `acknowledgeEngineAlert`, `resolveEngineAlert`, `checkAlertEngineHealth` | **REAL** — no mock fallback |
| **Frontend alerts page** | ✅ Implemented | `alerts/page.tsx` — removed all `mockAlerts`; shows Engine Offline state if engine is down | **REAL** — zero mock data |
| **Frontend WebSocket sub** | ✅ Implemented | `alerts/page.tsx` connects to `ws://localhost:8001/api/ws/alerts` for real-time updates | **REAL** |
| **Demo mode** | ✅ Implemented | When backend serves DEMO_EVENTS (DB offline), Alert Engine processes them identically | **REAL** — same code path |
| **Mode labeling** | ✅ Implemented | Each Alert has `mode` field ("live"/"demo") sourced from event's `raw_source` | **REAL** — no deception |
| **Cooldown enforcement** | ✅ Implemented | Decision engine checks `(now - alert.updated_at) > cooldown_seconds` | **REAL** |
| **Stale/expiry resolution** | ⚠️ Partial | Alert lifecycle transitions are present but background TTL expiry worker not yet scheduled | **PARTIAL** — manual resolve works |
| **Webhook HMAC auth** | 📋 Configured | `config.py` has `ALERT_WEBHOOK_SECRET`; signing not implemented yet | **STUB** |
| **Configuration** | ✅ Complete | `config.py` — all thresholds from env vars, safe defaults for dev | **REAL** |
| **Failure handling** | ✅ Implemented | WS reconnect with backoff, API timeout handling, SQLite error logging, malformed event skip | **REAL** |
| **Backend isolation** | ✅ VERIFIED | Zero lines modified in `backend/` directory | **CONFIRMED** |

---

## Summary

| Category | Count |
|---|---|
| **REAL** (fully implemented) | 20 |
| **REAL** (partially implemented) | 1 (TTL expiry worker) |
| **STUB** (scaffolded but not complete) | 3 (Webhook send, Email send, HMAC signing) |
| **MOCK** (fake data, no real logic) | **0** |

---

## What is NOT mock data

The following are explicitly verified to NOT use hardcoded mock values:

1. `fetchEngineAlerts()` returns `[]` (not mock alerts) when engine is offline.
2. `alerts/page.tsx` shows an "Engine Offline" state — it does NOT fall back to the old `mockAlerts` array.
3. Every `Alert` object is created from a real `VerifiedEvent` parsed from an existing INDRA API response.
4. Alert `confidence`, `severity`, `source_count` are always the actual values from the event, never invented.
5. Alert IDs are generated with `uuid4()` — never hardcoded.

---

## Next Steps for Completing Stubs

| Component | Effort | Description |
|---|---|---|
| TTL expiry worker | Low | Add background asyncio task to call `lifecycle.resolve_alert()` for expired alerts |
| Webhook delivery | Medium | Add `httpx.AsyncClient.post()` in `dispatcher.py` with HMAC-SHA256 signing |
| Email delivery | Medium | Add `aiosmtplib` SMTP send in `dispatcher.py` |
