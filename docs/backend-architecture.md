# Backend Architecture — `INDRA/backend`

Backend-only detail, deeper than the whole-system `architecture.md`. Aditya's reference for module boundaries and data flow.

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
│   └── security.py            not yet read in depth — check before relying on it (see backend-status.md).
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
│   ├── fusion_engine.py
│   ├── dedup.py
│   ├── geo_clustering.py
│   └── geocoding.py           sanitize_coordinates() — used by reports.py to validate/snap incoming lat/lng to Indian bounds and resolve city/state
└── workers/
    └── report_consumer.py     background aiokafka consumer — currently a raw relay, see below
```

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
   └─ report_consumer.py consumes it and just re-broadcasts as {"type": "NEW_REPORT", "report": ...} over /ws/events
       (dedup / clustering / fusion scoring are NOT called here — see backend-status.md P0)
```

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

## Auth

- `POST /api/auth/token` — only endpoint in `auth.py` (49 lines total). Not yet verified whether it issues real JWTs validated elsewhere, or is a demo stub. Check `core/security.py` and whether any router actually depends on an auth check before treating any endpoint as access-controlled.

## Config surface (`core/config.py` / `.env`)

Thresholds and tunables that affect backend behavior directly:

- `AUTO_PUBLISH_THRESHOLD=0.90`, `HUMAN_REVIEW_THRESHOLD=0.70` — used by `fusion_engine.determine_review_status()`.
- `DBSCAN_EPS_KM=5.0`, `DBSCAN_MIN_SAMPLES=2` — used by `geo_clustering.cluster_unassigned_reports()`. Note: `status.md`'s dedup constants (`GPS_DELTA_KM=1.0`, `TIME_DELTA_MINUTES=15`) are hardcoded in `dedup.py` itself, not read from settings — inconsistent with how the clustering service reads its constants from `get_settings()`. Worth aligning if touching either file.
- `H3_HEX_RESOLUTION=8` — used in both `geo_clustering.py` and `reports.py`'s inline H3 call.
- `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_REPORTS_TOPIC`, `KAFKA_EVENTS_TOPIC` — note `KAFKA_EVENTS_TOPIC` is defined in `.env.example` but I have not yet found any code that produces to it; only `KAFKA_REPORTS_TOPIC` is used (in `reports.py` producer and `report_consumer.py`'s consumer).

## Competition readiness — what has to change to actually win SIH

Everything above describes what the code *is*. This section is about closing the gap to what it needs to *become* to survive judging, not just look good in a README. SIH judges generally score on: does the prototype visibly work live, is the technical depth real (not just claimed), is the novelty explainable, and does it hold up if someone pokes at it. Mapped onto this specific backend, in priority order:

### Non-negotiable before demo day — these are what make the pitch *true*

1. **Wire the real pipeline** (`backend-todo.md` P0). A live-submitted report (`POST /api/reports/submit`) must visibly flow through `DedupService` → `GeoClusteringService` → `FusionEngine` and come out the other side as a verified event over `/ws/events`. This is the single highest-risk gap: the whole pitch is "we turn 127 noisy reports into 1 verified event," and right now that transformation only exists in a canned JSON file (`data/samples/patna_flood_scenario.json`), not in the live code path. If a judge asks "submit a report and show me it get verified," nothing happens today. Fix this first — everything else is secondary.
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
