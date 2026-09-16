# Backend Architecture — `INDRA/backend`

Backend-only detail, deeper than the whole-system `architecture.md`. Aditya's reference for module boundaries and data flow. Re-verified against the live code on 16 Sep 2026.

> **Sprint:** backend completion run, **16–20 Sep 2026**. Day plan in `backend-todo.md`; today's tasks in `aditya_16-sep.md`. The "competition readiness" section at the bottom of this file is the *why* behind that plan's ordering.

> ### ⚠ Where the code actually is (16 Sep)
>
> **Day 1's work is complete and pushed, but split across six unmerged branches** for review:
> `aditya_16sep-test-harness`, `aditya_16sep-fix-event-detail`, `aditya_16sep-geo-clustering`,
> `aditya_16sep-service-tests`, `aditya_16sep-pipeline`, `aditya_16sep-consumer-wiring`.
> **None of it is on `aditya_16sep` or `main`.**
>
> This document describes the **merged** state. Read it against a checkout of `aditya_16sep`
> or `main` and you will find `services/pipeline.py` and `tests/` missing and
> `report_consumer.py` still a raw relay — that is the branch state, not a regression, and
> it is the single most confusing thing about this repo right now.
>
> **Merge order matters:** `test-harness` first (it adds the `pytest.ini` and `conftest.py`
> every other branch's tests import), then `geo-clustering` before `pipeline` (pipeline calls
> the new `get_cluster_stats()` and `assign_reports_to_event()`), then `consumer-wiring` last
> (it imports `pipeline`). `fix-event-detail` and `service-tests` are independent and can go
> any time after `test-harness`.

## Where the backend sits in the 9-layer architecture

The team's canonical SIH26069 system diagram has nine layers. **Seven of them are backend
territory** (layers 2–8); layer 1 is external sources plus the frontend's citizen PWA, and
layer 9 is the frontend's command center. Status verified against code, not intent.

Legend: ✅ built · 🟡 partial · ⬜ designed, not built · ⬛ not backend's layer

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. DATA SOURCES                                          🟡 1 of 6  ⬛/✅ │
│    ✅ Citizen reports  ⬜ IMD/Govt APIs  ⬜ Weather APIs                  │
│    ⬜ Social media     🟡 Public datasets  🟡 Images/Videos               │
│    → backend owns the ingest endpoint; no external feed is polled at all │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 2. DATA INGESTION                                        ✅ complete     │
│    ✅ REST API/Webhooks  ✅ Kafka/Redpanda  ✅ Batch  ✅ Stream          │
│    → api/reports.py (producer) + workers/report_consumer.py (consumer)   │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 3. DATA PROCESSING LAYER                                 🟡 2 of 6       │
│    ✅ Deduplication  🟡 Normalization  🟡 Geocoding                      │
│    ⬜ Cleaning  ⬜ Timestamp processing  ⬜ Metadata extraction           │
│    → services/dedup.py, services/geocoding.py                           │
└───────────────┬────────────────────────────────┬────────────────────────┘
┌───────────────▼──────────────┐ ┌───────────────▼────────────────────────┐
│ 4. AI / ML LAYER   ⬜ 1 of 6 │ │ 5. GEO-ANALYTICS        ✅ mostly      │
│    ✅ Duplicate matching     │ │    ✅ Location mapping                  │
│    ⬜ NLP classifier         │ │    ✅ Spatial clustering                │
│    ⬜ Event detection        │ │    🟡 Heatmaps (H3 stored, unread)      │
│    ⬜ Fake detection         │ │    🟡 Event boundaries (polygon unused) │
│    ⬜ Image analysis         │ │    ⬜ Risk zones                        │
│    ⬜ Anomaly detection      │ │    🟡 Time-space trends                 │
│    → MiniLM, dedup only      │ │    → services/geo_clustering.py         │
└───────────────┬──────────────┘ └───────────────┬────────────────────────┘
┌───────────────▼────────────────────────────────▼────────────────────────┐
│ 6. EVENT FUSION ENGINE                                   ✅ the spine    │
│    ✅ Correlate observations  ✅ Merge duplicates  ✅ Build event        │
│    🟡 Calculate confidence (4 of 6 factors are placeholders)             │
│    🟡 Determine severity (from report count, not content)               │
│    → services/pipeline.py + services/fusion_engine.py                   │
└────────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────────┐
│ 7. DATA PLATFORM                                         🟡 1.5 of 4     │
│    ✅ PostgreSQL + PostGIS   🟡 Redis (running, zero client code)        │
│    ⬜ Object Storage S3/MinIO  🟡 Historical datasets                    │
└───────────────┬────────────────────────────────┬────────────────────────┘
┌───────────────▼──────────────┐ ┌───────────────▼────────────────────────┐
│ 8a. REAL-TIME API ✅ complete│ │ 8b. ALERT ENGINE          ⬜ absent    │
│    ✅ FastAPI ✅ WS ✅ REST  │ │    ⬜ Critical events                   │
│    ⚠ every endpoint is open  │ │    ⬜ SMS/Email  ⬜ Dashboard alerts     │
└───────────────┬──────────────┘ └───────────────┬────────────────────────┘
┌───────────────▼────────────────────────────────▼────────────────────────┐
│ 9. IMD COMMAND CENTER                                    ⬛ frontend      │
│    Next.js dashboard — not backend's to edit. Note every fetch falls     │
│    back to mock data, so a complete-looking UI proves nothing about us.  │
└─────────────────────────────────────────────────────────────────────────┘
```

**What this means for the sprint.** The backend's spine — layers 2, 5, 6, 8a — is genuinely
built. The gaps cluster in three places, and the day plan is ordered to match: layer 4
(AI/ML) is the weakest and is largely a deliberate deferral, layer 3's missing processing
steps are mostly cosmetic *except* the coordinate-snapping defect, and layer 8b (alerting)
does not exist at all. The `audit_logs` writers, the human-review endpoint and RBAC
enforcement cut across layers 6–8a and are Day 3.

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
│   └── security.py            REAL and complete: bcrypt hash/verify, HS256 JWT create/verify (8h expiry,
│                              claims {sub, role, agency, iat, exp}), get_current_operator() dependency,
│                              require_roles(*roles) guard factory, 4 demo users (admin/commander/analyst/citizen).
│                              Catch: require_roles and get_current_operator have ZERO callers — no endpoint
│                              is actually guarded. Scheduled for Day 3.
├── api/                     one router per domain, all prefixed /api/<domain>, all imported via api/__init__.py
│   ├── dashboard.py           prefix /api/dashboard — GET /summary
│   ├── events.py               prefix /api/events   — GET "", GET /distribution, GET /{event_id}
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
│   ├── fusion_engine.py       compute_receipt / assign_quadrant / determine_review_status + the
│   │                          generate_heuristic_scores() random stub. Called by pipeline.py since T10.
│   ├── dedup.py               is_duplicate(new_text, lat, lng, time, existing[]) — AND of three gates.
│   ├── geo_clustering.py      cluster_unassigned_reports() / get_cluster_stats() /
│   │                          assign_reports_to_event() / assign_h3_cells() / update_geom_points().
│   ├── geocoding.py           sanitize_coordinates() — used by reports.py to validate/snap incoming lat/lng to Indian bounds and resolve city/state
│   └── pipeline.py            ✅ SHIPPED Day 1 T10. process_report(db, report) orchestrates
│                              dedup → cluster → stats → fusion → persist → return event.
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
   ├─ ReportSubmission pydantic model validates lat/lng bounds + text length (5–2000 chars)
   ├─ geocoding.sanitize_coordinates() snaps coords, resolves city/state
   ├─ h3.latlng_to_cell() computes H3 cell (best-effort, swallows exceptions)
   ├─ INSERT INTO raw_reports (... credibility_score hardcoded to 0.5 ...)   ← direct DB write, not through any service
   ├─ Kafka producer sends the same payload to indra.raw.reports            ← fire-and-forget, failure is non-fatal
   └─ returns 202 {id, status: "accepted"}

separately, async:
Kafka topic indra.raw.reports
   │
   └─ report_consumer.py broadcasts NEW_REPORT, then runs the pipeline (see below)
```

## Request flow through the pipeline — **live as of Day 1 T11**

```
Kafka topic indra.raw.reports
   │
   └─ report_consumer.py → opens an AsyncSession → pipeline.process_report(db, report)
        │
        ├─ 1. SELECT recent nearby reports (ST_DWithin 1km, created_at > now()-15min)
        ├─ 2. DedupService.is_duplicate(...)  ──► duplicate? log, return None, broadcast NEW_REPORT only
        ├─ 3. update_geom_points() + assign_h3_cells()
        ├─ 4. cluster_unassigned_reports() → find the cluster containing this report
        │       └─ report in no cluster (DBSCAN noise / lone report)? return None. This is CORRECT:
        │          one uncorroborated report is not an event.
        ├─ 5. get_cluster_stats(report_ids) → count, centroid, radius_km, max_pairwise_km
        ├─ 6. FusionEngine.compute_receipt(...)   ← Day 1: heuristic/None. Day 2: real signals.
        ├─ 7. assign_quadrant(severity, confidence) + determine_review_status(confidence)
        ├─ 8. INSERT INTO verified_events (…, verification_receipt JSONB, center_point, impact_radius_km)
        ├─ 9. assign_reports_to_event(report_ids, new_event_id)   ← backfills raw_reports.event_id
        └─ 10. return the event dict
             │
             └─ consumer broadcasts {"type": "VERIFIED_EVENT", "event": {...}} over /ws/events
```

The whole of `process_report` is wrapped in try/except following the codebase's existing fail-soft convention
(`reports.py::reports_trend` is the reference) — a pipeline crash must never kill the consumer loop.

**Frontend handover note (do not implement):** this adds a new WebSocket message type `VERIFIED_EVENT`,
shaped like `GET /api/events/{id}`. The existing `NEW_REPORT` and `DEMO_PULSE` types are unchanged and
`NEW_REPORT` keeps firing for reports that don't produce an event, so nothing currently consumed breaks.

Two things worth internalizing from this:

1. **The report is already durably stored (`raw_reports`) and already has a `credibility_score`, hardcoded to `0.5` for every submission** — that's a placeholder, not a computed value, and is a second "randomness"-adjacent gap alongside `fusion_engine.generate_heuristic_scores()`.
2. **Kafka is currently redundant with the DB write** — the same report is written directly to Postgres by the API handler *and* separately pushed to Kafka, but nothing downstream of Kafka does anything with it except rebroadcast. Once the pipeline is wired (backend-todo.md P0), decide whether processing should happen synchronously in the API handler, asynchronously via the Kafka consumer, or both (e.g. immediate DB write + async enrichment via consumer) — right now it's neither, functionally.

## Query endpoints — read paths

- `GET /api/dashboard/summary` — KPI numbers for the dashboard cards (total reports, verified events, critical events, citizen reports + deltas).
- `GET /api/events`, `GET /api/events/{event_id}`, `GET /api/events/distribution` — verified events list/detail/aggregation. 481 lines total in `events.py` — this is the biggest router, worth a dedicated read before changing event-related behavior.
- `GET /api/reports/trend?range=7d|14d|30d` — daily report counts; has a raw-SQL query with a hardcoded `DEMO_TREND` fallback if the query fails (good pattern to reuse elsewhere — fail soft, log a warning, return demo data).
- `GET /api/feed/recent` — live feed items.
- `GET /api/teams`, `/api/teams/{team_id}`, `/api/teams/hackathon/sixth-sense` — team roster/detail.
- `GET /api/profile/me`, `/activity`, `/operators`, `/preferences` — operator profile data.

## Auth — verified 16 Sep

`POST /api/auth/token` is the only endpoint in `auth.py` (49 lines). It takes an OAuth2 password form, checks
the password with bcrypt against `DEMO_USERS`, and returns a real HS256 JWT with `{sub, role, agency, iat, exp}`
and an 8-hour expiry, plus `role` and `agency` in the response body. `401` on bad credentials.

`core/security.py` backs it with `hash_password` / `verify_password` (bcrypt), `create_access_token`,
`verify_token`, a `get_current_operator` FastAPI dependency, and a `require_roles(*allowed_roles)` guard
factory returning `403` on a role mismatch.

Demo users: `admin`/`admin123` (ADMIN, NDMA), `commander`/`commander123` (COMMANDER, SDMA_BIHAR),
`analyst`/`analyst123` (ANALYST, IMD), `citizen`/`citizen123` (CITIZEN, PUBLIC).

**So the machinery is real and correct — and it guards nothing.** `require_roles` and `get_current_operator`
have zero callers outside `security.py`; every endpoint in every router is open. Note also that `ROLES` in
`security.py` lists 4 roles while `models/enums.py::OperatorRole` has 5 (it adds `FIELD_RESPONDER`) — worth
reconciling when the guards go on. Day 3, and coordinate before gating anything the dashboard already calls.

## Config surface (`core/config.py` / `.env`)

Thresholds and tunables that affect backend behavior directly:

- `AUTO_PUBLISH_THRESHOLD=0.90`, `HUMAN_REVIEW_THRESHOLD=0.70` — used by `fusion_engine.determine_review_status()`.
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
   **This was the single highest-risk gap and it is closed.** Remaining caveat: it is on the six
   unmerged branches listed at the top of this file, so it is not yet true on `main`.
2. **Replace at least 2 of the 6 fusion factors with real computed signals**, not `random.uniform(...)`. The cheapest wins: `report_density` from the actual count of deduplicated reports in a cluster, and `spatial_coherence` from the actual DBSCAN cluster tightness — both are already computed as byproducts of `geo_clustering.py`, so this is wiring, not new modeling. Also replace the hardcoded `credibility_score = 0.5` in `reports.py`'s insert. If a judge reads `fusion_engine.py` (or asks "how is this score computed") and finds it's random, the core technical claim of the project — an explainable, evidence-based confidence score — is disproven in front of them.
3. **Make `audit_logs` actually get written to**, for at least one transition (e.g. every `review_status` change). Right now the table exists but has zero writers anywhere in the codebase. "Unalterable audit trail" and "provenance chain" are repeated selling points in the README and `understand.md` — if a judge opens the database and the table is empty, that claim is provably false, which is worse for credibility than never having mentioned an audit trail at all.
4. **Add the missing human-review endpoint** (see `api-requirements.md` gap #1 — something like `PATCH /api/events/{event_id}/review`). The 2×2 confidence/severity matrix is the project's headline idea, but right now it's a read-only label with no action behind it. Judges respond well to seeing the "high severity, low confidence → flagged for human review → operator overrides/confirms" story actually work live, not just described in a slide.
5. **Keep `/api/demo/trigger` as an explicit, clearly-separate fallback**, and be ready to explain the distinction if asked. Once #1 works, the canned scenario becomes a legitimate "what if the network drops" failsafe (which the project's own docs correctly argue for) instead of being, as it is today, the *only* thing that actually produces a verified event.

### Strong differentiators if time remains after the above

6. **Make `/healthz` check something real** (DB ping, Redis ping, reuse `report_consumer.py`'s existing `check_kafka_connection()` for Kafka) instead of returning hardcoded `"connected"` strings. Cheap, and defuses "is this actually running right now" questions during a live demo.
7. **Produce to `KAFKA_EVENTS_TOPIC`** once real verified events exist, so the documented data flow (Kafka in *and* out) is actually demonstrable, not just half-true.
8. **Verify auth actually gates the new review endpoint** before demo day — an unauthenticated "approve/override a disaster event" endpoint is a bad look for a system whose whole pitch is trustworthiness, and it's an easy thing for a technical judge to probe.

### What NOT to spend remaining time on

9. Full NLP/CV models, ClickHouse/Iceberg, Kubernetes, MinIO/S3 — all correctly deferred already per the project's own phased plan. Resist scope-creep into "let's add real ML" before #1–#4 above are done; a wired pipeline with honest heuristic scores and a real audit trail beats an unwired pipeline with one impressive but disconnected ML model. Judges reward a working end-to-end slice over an isolated impressive component.
