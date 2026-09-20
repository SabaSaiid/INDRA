# INDRA — Backend Architecture

**What this is:** how the backend is put together — module boundaries, what each one owns, and
the exact path a citizen report takes from an HTTP request to a pin on the dashboard. Deeper than
[`ARCHITECTURE.md`](ARCHITECTURE.md), which covers the whole nine-layer system; this file is only
`backend/`.

**Last verified against the code and a running stack: 21 Sep 2026.**

Scope note, once: layers **4 (AI/ML)** and **8b (the alert engine)** left this backend's scope on
20 Sep and are **cancelled, not deferred**. Nothing below is waiting on them.

---

## The one path that matters

```
POST /api/reports/submit
   │  validate (India bounds, 5–2000 chars)  ─── outside → 422, nothing stored
   │  geocode, H3 res-8 cell, credibility score, rule-based analysis
   │  INSERT raw_reports  ─── failed → 503, nothing published
   ▼
indra.raw.reports  (Redpanda)
   │
   ▼  workers/report_consumer.py
   │  broadcast NEW_REPORT once per report id (Redis-backed, survives restart)
   ▼  services/pipeline.py :: process_report
   │
   ├─ 1. dedup            MiniLM cosine ≥ 0.88 AND ≤ 1 km AND ≤ 15 min
   │                      a duplicate is marked duplicate_of and stops here
   ├─ 2. cluster          PostGIS ST_ClusterDBSCAN, eps 5 km, min 2 samples
   ├─ 3. stats            centroid, radius, max pairwise distance, in metres
   ├─ 4. weather          station_readings within 3 h and 25 km  ─── miss → live Open-Meteo
   ├─ 5. score            6-factor receipt, re-normalised over the factors that reported
   ├─ 6. severity         max(depth axis, corroboration axis), from the report texts
   └─ 7. persist          ONE transaction: event + boundary polygon + report links + audit row
   │
   ├──► WebSocket  VERIFIED_EVENT
   └──► indra.verified.events
```

Everything on that line is live and covered by the test suite. Everything off it — classification,
vision, anomaly detection, alerting — is not, and is not coming.

---

## Module map

```
backend/app/
├── main.py              FastAPI entrypoint. Explicit CORS origin list (not "*").
│                        Lifespan starts, and cleanly stops, three background tasks:
│                          · the Kafka report consumer
│                          · the embedding-model warm-up (off the event loop)
│                          · the Open-Meteo station poller
│                        Serves GET /, /api/info, /healthz, WS /ws/events.
├── core/
│   ├── config.py        pydantic-settings, reads the REPO-ROOT .env (not backend/.env).
│   │                    Every threshold lives here: dedup gates, DBSCAN, H3 resolution,
│   │                    review thresholds, poller interval and freshness gates, DEMO_MODE.
│   ├── database.py      async SQLAlchemy engine, get_db() dependency, init_db().
│   ├── security.py      bcrypt + HS256 JWT (8 h), get_current_operator, require_roles().
│   └── demo.py          demo_fallback() — the single gate every demo response goes through.
├── api/                 one router per domain, each prefixed /api/<domain>
│   ├── dashboard.py     GET /summary
│   ├── events.py        GET "", /distribution, /{id}, PATCH /{id}/review, GET /{id}/provenance
│   ├── reports.py       GET /trend, POST /submit
│   ├── feed.py          GET /recent
│   ├── geo.py           GET /heatmap
│   ├── auth.py          POST /token
│   ├── teams.py         team records
│   └── profile.py       operator records
├── models/              SQLAlchemy ORM, one file per table, plus enums.py for every
│                        controlled vocabulary (SourceType, Severity, ReviewStatus,
│                        Quadrant, Agency, AuditAction, OperatorRole, …)
├── services/            where the intelligence lives
│   ├── pipeline.py      the orchestrator above. Fails soft: one bad report cannot
│   │                    kill the consumer loop.
│   ├── fusion_engine.py compute_receipt / assign_quadrant / determine_review_status.
│   ├── dedup.py         the three-gate AND. MiniLM encode runs in a thread.
│   ├── geo_clustering.py DBSCAN, H3 assignment, cluster stats, report→event linking.
│   ├── geocoding.py     coordinate sanitising against India's bounds, 56-city gazetteer.
│   ├── credibility.py   source prior × text quality, per report.
│   ├── text_processing.py cleaning, language detection, depth and place extraction.
│   │                    Regex and dictionaries. No model.
│   ├── weather.py       Open-Meteo 24 h accumulation → IMD daily-category curve.
│   ├── cache.py         Redis, with an in-memory fallback. Never load-bearing.
│   ├── audit.py         the SHA-256 hash chain.
│   ├── event_publisher.py verified events → indra.verified.events
│   └── health.py        the four real dependency checks behind /healthz.
├── workers/
│   ├── report_consumer.py  aiokafka consumer driving the pipeline.
│   └── station_poller.py   the scheduled Open-Meteo feed into station_readings.
└── ml/                  FROZEN. event_classifier.py is trained, measured below its
                         acceptance gate, and returns None. Out of scope since 20 Sep.
```

---

## The scoring model, precisely

Six factors, fixed weights:

| Factor | Weight | State |
|---|---|---|
| Weather Station Corroboration | 0.25 | online |
| Report Density Analysis | 0.20 | online |
| Spatial Coherence Score | 0.20 | online |
| Computer Vision Analysis | 0.15 | **permanently offline** |
| Source Reliability Index | 0.15 | online |
| Anomaly Detection Signal | 0.05 | **permanently offline** |

```
online          = { f : score(f) is not None }
total_weighted  = Σ_online  w_f · s_f
factor_coverage = Σ_online  w_f                    → 0.80 today
confidence      = total_weighted / factor_coverage
```

An offline factor **lowers the stated coverage** rather than silently scoring zero. Before this
change two permanently-offline factors held 20% of the scale hostage and `AUTO_PUBLISHED` (≥ 0.90)
was mathematically unreachable — a broken scale, not honesty. The receipt publishes
`factor_coverage` beside the score so the number is both usable and truthful. **Never quote one
without the other.**

Gates: `≥ 0.90` → `AUTO_PUBLISHED` · `≥ 0.60` → `PENDING_HUMAN_REVIEW` · else `QUARANTINED`.

**The curves are published, not tuned for a demo.** Rainfall is scored against IMD's own daily
rainfall categories (0 → 0.00, 2.5 → 0.10, 15.6 → 0.35, 64.5 → 0.70, 115.6 → 0.90, 204.5+ → 1.00).
Density saturates at 25 reports. Coherence is a raised cosine over twice the DBSCAN epsilon. The
reasoning for each is in the docstring beside it.

### Severity is read, not counted

`max()` of two axes over the **non-duplicate** reports, taking the higher:

| Axis | Rule |
|---|---|
| Depth (deepest quoted in any report) | ≥ 120 cm CRITICAL · ≥ 60 HIGH · ≥ 20 MODERATE · else ADVISORY |
| Corroboration (report count) | ≥ 10 HIGH · ≥ 5 MODERATE · else ADVISORY |

The count axis **never reaches CRITICAL**: a count is evidence that something is happening, not of
how bad it is. The depth cuts are operational — 20 cm stops a two-wheeler, 60 cm floats a small
car, 120 cm turns wading into a rescue — and are numbers a nodal officer can argue with, which is
the point. The receipt names the winning axis and the phrase it read.

---

## The data platform

| Store | What it holds | What happens without it |
|---|---|---|
| **PostgreSQL + PostGIS** | everything of record: `raw_reports`, `verified_events`, `station_readings`, `audit_logs`, teams, profiles | submit returns 503, `/healthz` 503. **Critical** |
| **Redpanda** | `indra.raw.reports` in, `indra.verified.events` out | submit returns 202 `queued: false`, `/healthz` 503. **Critical** |
| **Redis** | the Open-Meteo cache (`wx:{cell}`, TTL 600 s) and the broadcast-dedup set (`bcast:{id}`, TTL 24 h) | both fall back to process memory, `/healthz` 200 `degraded`. **Never load-bearing** |
| **Object storage** | nothing — configured in `.env`, not deployed | n/a |

Six migrations, `0001` … `0006`. `audit_logs` carries a row-level trigger rejecting `UPDATE` and
`DELETE`.

### The audit chain

One global chain ordered by `seq`:
`sha256(canonical_json{prev_hash, event_id, operator_id, action, reason, details, logged_at})`,
genesis `"0"*64`. Appended under `pg_advisory_xact_lock` inside the caller's transaction, so
twenty concurrent writers cannot fork it. The pipeline writes `AUTO_VERIFY` / `ESCALATE` /
`QUARANTINE` on create and on a status-changing merge — **not per report**, so the ledger records
decisions rather than traffic. A reviewer writes `HUMAN_APPROVE` / `HUMAN_REJECT` /
`MANUAL_OVERRIDE`.

> **Honest limit:** editing, deleting or reordering a row is detected at that row. Rows cut off
> the **end**, or a `TRUNCATE`, leave a valid chain. Detecting that needs an external anchor for
> the head hash, which is not built.

---

## Background tasks, and why each is safe

| Task | Started | Failure behaviour |
|---|---|---|
| Kafka report consumer | lifespan | Retries with backoff; logs the broker being offline once, not per attempt |
| Embedding warm-up | lifespan, in a thread | Non-fatal. Without it the first report blocked the **entire** event loop for ~13 s — the API stopped answering, not just that report |
| Station poller | lifespan, if `STATION_POLLER_ENABLED` | Every tick wrapped; a failure logs one WARNING and the next tick retries |

All three are cancelled and **awaited** at shutdown, which is what keeps
`Task was destroyed but it is pending!` out of the logs.

> **One backend process.** WebSocket fan-out is an in-process list, the poller has no leader
> election, and two consumers on one broker re-deliver reports. This is a deliberate limit for a
> demo stack, recorded as BUG-011, not an accident.

---

## Configuration

Everything tunable is in `core/config.py`, read from the **repo-root `.env`**. A `backend/.env`,
if one exists, wins — which has bitten this project before.

The settings worth knowing: `DEMO_MODE` (default **false**, and it must stay false for a demo),
`DEDUP_COSINE_THRESHOLD` (0.88), `DBSCAN_EPS_KM` (5.0), `DBSCAN_MIN_SAMPLES` (2),
`H3_HEX_RESOLUTION` (8), `AUTO_PUBLISH_THRESHOLD` (0.90), `HUMAN_REVIEW_THRESHOLD` (0.60),
`STATION_POLLER_ENABLED`, `STATION_READING_MAX_AGE_MINUTES` (180),
`SNAP_OUT_OF_BOUNDS_COORDINATES` (false — true lets junk reports cluster at India's centroid),
`CORS_ORIGINS`.

---

## Testing

```bash
cd backend
.venv/bin/pytest -q                                   # 568 passed, 2 skipped
.venv/bin/pytest -q -m "not integration"              # no Docker needed
.venv/bin/pytest -q -m "not integration and not network"   # fully offline
```

The suite runs against its own **`indra_test`** database and cannot touch dev data. Integration
tests carry `@pytest.mark.integration`; anything hitting the network carries `network`.

**The suite is necessary and not sufficient.** Every one of the most serious defects found in this
project was invisible to a green suite and was caught by running the thing end to end from an
empty volume, or by disbelieving a number that looked too good. Two examples, both in
[`bug-register.md`](bug-register.md): an empty database answering with a fabricated
`0.94 / AUTO_PUBLISHED` event that 518 passing tests could not see, and a station poller storing
one hour of rain where the score curve expected a day of it. **Rehearse from cold, and probe every
number that flatters you.**
