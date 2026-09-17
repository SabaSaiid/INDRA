# Backend Architecture — `INDRA/backend`

Backend-only detail, deeper than the whole-system `architecture.md`. Aditya's reference for module boundaries and data flow. Re-verified against the live code on 16 Sep 2026, end of sprint Day 3.

> **Sprint:** backend completion run, **16–20 Sep 2026**. Day plan in `backend-todo.md`; Days 1–3 are done (`aditya_16-sep.md`, `aditya_17-sep.md`, `aditya_18-sep.md`); Day 4 is next (`aditya_19-sep.md`). The "competition readiness" section at the bottom of this file is the *why* behind that plan's ordering.

> ### Where the code actually is (16 Sep, end of Day 3)
>
> - **`main`**: Day 1 (PRs #4–#9 merged). 71 tests.
> - **`aditya_17sep`**, **PR #14 open**: Day 2. 219 passed, 2 skipped.
> - **`aditya_18sep`**, **PR #15 open**, stacked on Day 2: Day 3. 287 passed, 2 skipped,
>   1 xfailed. Needs `alembic upgrade head` (migration `0003`). Merge #14 before #15.
>
> This document describes `aditya_18sep`. Read against `main`, the Day 2/Day 3 modules
> (`weather.py`, `credibility.py`, `audit.py`, `core/demo.py`, the review/provenance endpoints)
> will be missing — that is the branch state, not a regression.

## Where the backend sits in the 9-layer architecture

The team's canonical SIH26069 system diagram has nine layers. **Seven of them are backend
territory** (layers 2–8); layer 1 is external sources plus the frontend's citizen PWA, and
layer 9 is the frontend's command center. Status verified against code, not intent.

Legend: ✅ built · 🟡 partial · ⬜ designed, not built · ⬛ not backend's layer

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. DATA SOURCES                                          🟡 2 of 6  ⬛/✅ │
│    ✅ Citizen reports  ⬜ IMD/Govt APIs  🟡 Weather APIs (Open-Meteo)     │
│    ⬜ Social media     🟡 Public datasets  🟡 Images/Videos               │
│    → ingest endpoint + per-event Open-Meteo fetch; nothing polled        │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 2. DATA INGESTION                                        ✅ complete     │
│    ✅ REST API/Webhooks  ✅ Kafka/Redpanda  ✅ Batch  ✅ Stream          │
│    → api/reports.py (producer) + workers/report_consumer.py (consumer)   │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 3. DATA PROCESSING LAYER                                 🟡 3 of 6       │
│    ✅ Deduplication  ✅ Normalization (out-of-India → 422)  🟡 Geocoding │
│    ⬜ Cleaning  ⬜ Timestamp processing  ⬜ Metadata extraction           │
│    → services/dedup.py, geocoding.py, credibility.py                    │
└───────────────┬────────────────────────────────┬────────────────────────┘
┌───────────────▼──────────────┐ ┌───────────────▼────────────────────────┐
│ 4. AI / ML LAYER   ⬜ 1 of 6 │ │ 5. GEO-ANALYTICS        ✅ mostly      │
│    ✅ Duplicate matching     │ │    ✅ Location mapping                  │
│    ⬜ NLP classifier         │ │    ✅ Spatial clustering                │
│    ⬜ Event detection        │ │    🟡 Heatmaps (H3 stored, unread)      │
│    ⬜ Fake detection         │ │    🟡 Event boundaries (polygon unused) │
│    ⬜ Image analysis (offline)│ │    ⬜ Risk zones                        │
│    ⬜ Anomaly det. (offline) │ │    🟡 Time-space trends                 │
│    → MiniLM, dedup only      │ │    → services/geo_clustering.py         │
└───────────────┬──────────────┘ └───────────────┬────────────────────────┘
┌───────────────▼────────────────────────────────▼────────────────────────┐
│ 6. EVENT FUSION ENGINE                                   ✅ the spine    │
│    ✅ Correlate observations  ✅ Merge duplicates  ✅ Build event        │
│    ✅ Calculate confidence (4 measured, 2 offline, deterministic)        │
│    🟡 Determine severity (from report count, not content)               │
│    ✅ Human decisions survive merges (Day 3)                             │
│    → services/pipeline.py + fusion_engine.py + weather.py               │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 7. DATA PLATFORM                                         🟡 2 of 4       │
│    ✅ PostgreSQL + PostGIS (+ SHA-256 audit chain, Day 3)                │
│    🟡 Redis (running, zero client code)                                 │
│    ⬜ Object Storage S3/MinIO  🟡 Historical datasets                    │
└───────────────┬────────────────────────────────┬────────────────────────┘
┌───────────────▼──────────────┐ ┌───────────────▼────────────────────────┐
│ 8a. REAL-TIME API ✅ complete│ │ 8b. ALERT ENGINE          ⬜ absent    │
│    ✅ FastAPI ✅ WS ✅ REST  │ │    ⬜ Critical events                   │
│    ✅ review + provenance    │ │    ⬜ SMS/Email  ⬜ Dashboard alerts     │
│    ⚠ only those 2 are gated  │ │                                         │
└───────────────┬──────────────┘ └───────────────┬────────────────────────┘
┌───────────────▼────────────────────────────────▼────────────────────────┐
│ 9. IMD COMMAND CENTER                                    ⬛ frontend      │
│    Next.js dashboard — not backend's to edit. Note every fetch falls     │
│    back to mock data, so a complete-looking UI proves nothing about us.  │
└─────────────────────────────────────────────────────────────────────────┘
```

**What this means for the sprint.** The backend's spine — layers 2, 5, 6, 8a — is built, and
after Days 2 and 3 it is also honest (no random factors) and accountable (hash-chained audit,
human review, RBAC on the new endpoints). What remains: layer 4 (AI/ML) is a deliberate
deferral, layer 8b (alerting) does not exist, the duplicate-absorption bug and `/healthz` are
Day 4, and gating the endpoints the dashboard already calls waits on a frontend login flow.

## Module map

```
backend/app/
├── main.py                FastAPI entrypoint. CORS (allow_origins=["*"] — fine for hackathon, tighten before real deploy).
│                            Lifespan: init_db() (non-fatal on failure) + starts report_consumer as background task.
│                            Exposes: GET /, GET /legacy, GET /api/info, GET /api/scenario,
│                            POST /api/demo/trigger, GET /healthz, WS /ws/events.
├── core/
│   ├── config.py            pydantic-settings — reads .env (DATABASE_URL, KAFKA_*, DBSCAN_*, H3_HEX_RESOLUTION, thresholds).
│   ├── database.py           async SQLAlchemy engine + get_db() dependency + init_db().
│   ├── demo.py              Day 2: demo_fallback() — demo data only when DEMO_MODE=true; else [] / 404 / 503.
│   └── security.py            bcrypt hash/verify, HS256 JWT create/verify (8h expiry, claims {sub, role, agency,
│                              iat, exp}), get_current_operator(), require_roles(*roles), 4 demo users.
│                              Day 3: guards the review and provenance endpoints; ROLES derived from OperatorRole.
├── api/                     one router per domain, all prefixed /api/<domain>, all imported via api/__init__.py
│   ├── dashboard.py           prefix /api/dashboard — GET /summary
│   ├── events.py               prefix /api/events   — GET "", GET /distribution, GET /{event_id},
│   │                             PATCH /{event_id}/review (Day 3), GET /{event_id}/provenance (Day 3)
│   ├── reports.py               prefix /api/reports  — GET /trend, POST /submit
│   ├── feed.py                    prefix /api/feed     — GET /recent
│   ├── auth.py                     prefix /api/auth     — POST /token
│   ├── teams.py                     prefix /api/teams    — GET "", GET /hackathon/sixth-sense, GET /{team_id}, POST "", PATCH /{team_id}/assign
│   └── profile.py                    prefix /api/profile  — GET /me, PATCH /me, GET /activity, GET /operators, GET /preferences, PATCH /preferences
├── models/                  SQLAlchemy ORM, one file per table + enums.py for every controlled vocabulary
│   ├── raw_reports.py
│   ├── verified_events.py
│   ├── station_readings.py
│   ├── teams.py
│   ├── profiles.py
│   ├── audit_logs.py
│   └── enums.py               SourceType, EventType, Severity, ReviewStatus, Quadrant, Agency, AuditAction,
│                                TeamStatus, TeamAgency, DutyStatus, OperatorRole
├── services/                business logic — see below, this is where the actual "intelligence" lives (or should)
│   ├── fusion_engine.py       compute_receipt / assign_quadrant / determine_review_status + SOURCE_RELIABILITY
│   │                          table. generate_heuristic_scores() deleted Day 2 — no randomness left.
│   ├── weather.py             Day 2: Open-Meteo 24 h rainfall → IMD categories, cached per H3 cell; failure → None.
│   ├── credibility.py         Day 2: per-report credibility = source prior × text quality.
│   ├── audit.py               Day 3: append-only SHA-256 chain — record(), verify_rows(), verify_chain().
│   ├── dedup.py               is_duplicate(new_text, lat, lng, time, existing[]) — AND of three gates.
│   ├── geo_clustering.py      cluster_unassigned_reports() / get_cluster_stats() /
│   │                          assign_reports_to_event() / assign_h3_cells() / update_geom_points().
│   ├── geocoding.py           sanitize_coordinates() — validates lat/lng, raises OutOfIndiaBoundsError (→ 422), fixes swaps, resolves city/state
│   └── pipeline.py            process_report(db, report): dedup → cluster → stats → score_cluster() (pure,
│                              deterministic) → persist + audit row in one transaction → return event.
└── workers/
    └── report_consumer.py     background aiokafka consumer — calls process_report() per message
                               and broadcasts VERIFIED_EVENT (T11)
```

**`geo_clustering.py` — resolved 16 Sep (T9).** The problem was that `cluster_unassigned_reports()` ran the
`ST_ClusterDBSCAN` query, grouped report IDs per cluster, logged each one, and returned a bare `int`: it
**never wrote `event_id` back to `raw_reports`** and never handed the cluster→report mapping to its caller,
so both the name and its `"reports assigned"` log line overstated what it did. It now returns
`[{cluster_id, report_ids, size}]`, and two methods were added alongside it — `get_cluster_stats()`
(centroid, radius, max pairwise distance, computed in `geography`/metres, which is what Day 2 needs for the
real `spatial_coherence` and `report_density` factors) and an explicit `assign_reports_to_event()` that does
the write. Clustering still only considers `event_id IS NULL`, which is what makes reprocessing idempotent.

**Still open on that file:** the eps conversion `eps_km * 0.009` is degrees-at-equator and is off by roughly
10% at Patna's latitude. Switching the clustering itself to a `geography`-based distance is Day 5 polish;
the *stats* already use `geography`, so the numbers feeding the confidence score are not affected.

## Request flow as it exists today (verified by reading the code)

```
POST /api/reports/submit
   │
   ├─ ReportSubmission pydantic model validates lat/lng + text length (5–2000 chars)
   ├─ geocoding.sanitize_coordinates() — out-of-India → 422, nothing stored or published (Day 2)
   ├─ h3.latlng_to_cell() computes H3 cell
   ├─ credibility.compute_credibility() computes credibility_score (Day 2; was hardcoded 0.5)
   ├─ INSERT INTO raw_reports
   ├─ Kafka producer sends the stored row (valid coords, raw_text, h3_res8, credibility) to indra.raw.reports
   └─ returns 202 {id, status: "accepted"}   ⚠ still 202 if the insert failed — Day 4
```

## Request flow through the pipeline

```
Kafka topic indra.raw.reports
   │
   └─ report_consumer.py broadcasts NEW_REPORT → opens an AsyncSession → pipeline.process_report(db, report)
        │
        ├─ 1. SELECT recent nearby reports (ST_DWithin 1km, created_at > now()-15min)
        ├─ 2. DedupService.is_duplicate(...)  ──► duplicate? log, return None
        │       ⚠ the duplicate stays event_id NULL and can be absorbed later — Day 4 fix
        ├─ 3. update_geom_points() + assign_h3_cells()
        ├─ 4. cluster_unassigned_reports() → the cluster containing this report (lone report → None)
        ├─ 5. get_cluster_stats(report_ids) → count, centroid, radius_km, max_pairwise_km
        ├─ 6. weather_score() (Open-Meteo, cached, ≤3 s) → score_cluster(): 4 measured factors, 2 offline
        ├─ 7. overlapping recent event?  merge: lock it FOR UPDATE, keep HUMAN_APPROVED / severity override
        │                                 new:   INSERT INTO verified_events
        ├─ 8. assign_reports_to_event(commit=False) + audit.record() on create / status change
        ├─ 9. COMMIT once (links + event + audit row), or roll back all of it
        └─ 10. return the event dict → consumer broadcasts VERIFIED_EVENT over /ws/events

PATCH /api/events/{id}/review   (COMMANDER/ADMIN)
   └─ lock event → validate transition (409 if illegal) → HUMAN_APPROVED / REJECTED / severity override
      → audit.record(HUMAN_APPROVE | HUMAN_REJECT | MANUAL_OVERRIDE) → COMMIT → broadcast EVENT_REVIEWED
```

The whole of `process_report` is wrapped in try/except following the codebase's fail-soft convention —
a pipeline crash must never kill the consumer loop.

**Frontend handover notes (do not implement):** `VERIFIED_EVENT` (Day 1) is shaped like
`GET /api/events/{id}`. Day 3 adds `EVENT_REVIEWED`, the `HUMAN_APPROVED` review status, and the two
auth-gated endpoints — full shapes in the Day 3 handover note. Existing message types are unchanged.

## Query endpoints — read paths

- `GET /api/dashboard/summary` — KPI numbers for the dashboard cards (total reports, verified events, critical events, citizen reports + deltas).
- `GET /api/events`, `GET /api/events/{event_id}`, `GET /api/events/distribution` — verified events list/detail/aggregation. 481 lines total in `events.py` — this is the biggest router, worth a dedicated read before changing event-related behavior.
- `GET /api/reports/trend?range=7d|14d|30d` — daily report counts; has a raw-SQL query with a hardcoded `DEMO_TREND` fallback if the query fails (good pattern to reuse elsewhere — fail soft, log a warning, return demo data).
- `GET /api/feed/recent` — live feed items.
- `GET /api/teams`, `/api/teams/{team_id}`, `/api/teams/hackathon/sixth-sense` — team roster/detail.
- `GET /api/profile/me`, `/activity`, `/operators`, `/preferences` — operator profile data.

## Auth — verified 16 Sep (Day 3)

`POST /api/auth/token` takes an OAuth2 password form, checks the password with bcrypt against
`DEMO_USERS`, and returns an HS256 JWT with `{sub, role, agency, iat, exp}` and an 8-hour expiry. `401` on
bad credentials.

Demo users: `admin`/`admin123` (ADMIN, NDMA), `commander`/`commander123` (COMMANDER, SDMA_BIHAR),
`analyst`/`analyst123` (ANALYST, IMD), `citizen`/`citizen123` (CITIZEN, PUBLIC).

**Enforced since Day 3, on two endpoints only:**

| Endpoint | Allowed roles | No / expired / bad token | Wrong role |
|---|---|---|---|
| `PATCH /api/events/{id}/review` | COMMANDER, ADMIN | 401 | 403 |
| `GET /api/events/{id}/provenance` | ANALYST, COMMANDER, ADMIN | 401 | 403 |

Pinned by a 7-token × 3-case test matrix. A missing token on an unknown id returns 401, not 404, so ids
can't be probed anonymously. `ROLES` is now derived from `OperatorRole` (5 roles, incl. `FIELD_RESPONDER`).

**Everything the dashboard already calls is still open**, because the frontend never requests a token.
Gating the mutations (`POST /api/teams`, `PATCH /api/teams/{id}/assign`, `PATCH /api/profile/*`) is
proposed in the Day 3 handover and waits on a dashboard login flow.

## Config surface (`core/config.py` / `.env`)

Thresholds and tunables that affect backend behavior directly:

- `AUTO_PUBLISH_THRESHOLD=0.90`, `HUMAN_REVIEW_THRESHOLD=0.70` — used by `fusion_engine.determine_review_status()`. With vision/anomaly offline the max confidence is 0.80, so auto-publish is currently unreachable.
- `DEMO_MODE` (Day 2) — gates every demo fallback. `.env` has `true`.
- `SNAP_OUT_OF_BOUNDS_COORDINATES` (Day 2, default `false`) — old snapping behaviour behind an explicit flag.
- `OPEN_METEO_API_URL`, `WEATHER_TIMEOUT_SECONDS=3.0` (Day 2) — weather factor.
- **Fixed Day 2:** `.env` is actually read now (`env_file` is anchored to `config.py`, not the working directory).
- `DBSCAN_EPS_KM=5.0`, `DBSCAN_MIN_SAMPLES=2` — used by `geo_clustering.cluster_unassigned_reports()`. Note: `status.md`'s dedup constants (`GPS_DELTA_KM=1.0`, `TIME_DELTA_MINUTES=15`) are hardcoded in `dedup.py` itself, not read from settings — inconsistent with how the clustering service reads its constants from `get_settings()`. Worth aligning if touching either file.
- `H3_HEX_RESOLUTION=8` — used in both `geo_clustering.py` and `reports.py`'s inline H3 call.
- `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_REPORTS_TOPIC`, `KAFKA_EVENTS_TOPIC` — note `KAFKA_EVENTS_TOPIC` is defined in `.env.example` but I have not yet found any code that produces to it; only `KAFKA_REPORTS_TOPIC` is used (in `reports.py` producer and `report_consumer.py`'s consumer).

## Competition readiness — what has to change to actually win SIH

Everything above describes what the code *is*. This section is about closing the gap to what it needs to *become* to survive judging, not just look good in a README. SIH judges generally score on: does the prototype visibly work live, is the technical depth real (not just claimed), is the novelty explainable, and does it hold up if someone pokes at it. Mapped onto this specific backend, in priority order:

### Non-negotiable before demo day — these are what make the pitch *true*

1. ~~**Wire the real pipeline**~~ ✅ **DONE — Day 1, 16 Sep.** A live-submitted report now flows
   `POST /api/reports/submit` → Kafka → `DedupService` → `GeoClusteringService` → `FusionEngine`
   → a persisted `verified_events` row → `VERIFIED_EVENT` over `/ws/events`, covered end-to-end
   by tests. The pitch — "we turn many noisy reports into one verified event" — is now
   demonstrable in the live code path rather than only in `data/samples/patna_flood_scenario.json`.
   **This was the single highest-risk gap and it is closed.** It is merged to `main`.
2. ~~**Replace at least 2 of the 6 fusion factors with real computed signals**~~ ✅ **DONE — Day 2.** 4 factors measured (incl. live Open-Meteo), 2 explicitly offline, credibility computed, determinism tested. Original note:, not `random.uniform(...)`. The cheapest wins: `report_density` from the actual count of deduplicated reports in a cluster, and `spatial_coherence` from the actual DBSCAN cluster tightness — both are already computed as byproducts of `geo_clustering.py`, so this is wiring, not new modeling. Also replace the hardcoded `credibility_score = 0.5` in `reports.py`'s insert. If a judge reads `fusion_engine.py` (or asks "how is this score computed") and finds it's random, the core technical claim of the project — an explainable, evidence-based confidence score — is disproven in front of them.
3. ~~**Make `audit_logs` actually get written to**~~ ✅ **DONE — Day 3.** SHA-256 hash chain written by the pipeline and the review endpoint. Original note:, for at least one transition (e.g. every `review_status` change). Right now the table exists but has zero writers anywhere in the codebase. "Unalterable audit trail" and "provenance chain" are repeated selling points in the README and `understand.md` — if a judge opens the database and the table is empty, that claim is provably false, which is worse for credibility than never having mentioned an audit trail at all.
4. ~~**Add the missing human-review endpoint**~~ ✅ **DONE — Day 3.** `PATCH /api/events/{id}/review` + `GET /api/events/{id}/provenance`. Original note: (see `api-requirements.md` gap #1 — something like `PATCH /api/events/{event_id}/review`). The 2×2 confidence/severity matrix is the project's headline idea, but right now it's a read-only label with no action behind it. Judges respond well to seeing the "high severity, low confidence → flagged for human review → operator overrides/confirms" story actually work live, not just described in a slide.
5. **Keep `/api/demo/trigger` as an explicit, clearly-separate fallback**, and be ready to explain the distinction if asked. Once #1 works, the canned scenario becomes a legitimate "what if the network drops" failsafe (which the project's own docs correctly argue for) instead of being, as it is today, the *only* thing that actually produces a verified event.

### Strong differentiators if time remains after the above

6. **Make `/healthz` check something real** (DB ping, Redis ping, reuse `report_consumer.py`'s existing `check_kafka_connection()` for Kafka) instead of returning hardcoded `"connected"` strings. Cheap, and defuses "is this actually running right now" questions during a live demo.
7. **Produce to `KAFKA_EVENTS_TOPIC`** once real verified events exist, so the documented data flow (Kafka in *and* out) is actually demonstrable, not just half-true.
8. ~~**Verify auth actually gates the new review endpoint**~~ ✅ **DONE — Day 3** (7×3 test matrix). Original note: before demo day — an unauthenticated "approve/override a disaster event" endpoint is a bad look for a system whose whole pitch is trustworthiness, and it's an easy thing for a technical judge to probe.

### What NOT to spend remaining time on

9. Full NLP/CV models, ClickHouse/Iceberg, Kubernetes, MinIO/S3 — all correctly deferred already per the project's own phased plan. Resist scope-creep into "let's add real ML" before #1–#4 above are done; a wired pipeline with honest heuristic scores and a real audit trail beats an unwired pipeline with one impressive but disconnected ML model. Judges reward a working end-to-end slice over an isolated impressive component.
