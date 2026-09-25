# INDRA — Backend Architecture

**What this is:** how the backend is put together — module boundaries, what each one owns, and
the exact path a citizen report takes from an HTTP request to a pin on the dashboard. Deeper than
[`ARCHITECTURE.md`](ARCHITECTURE.md), which covers the whole nine-layer system; this file is only
`backend/`.

**Last verified against the code and a running stack: 22 Sep 2026.** Updated 25 Sep from the code
for the demo-data removal: accounts in `user_profiles`, `core/empty.py`, the E2E mode and the
current background tasks. Those parts have not been re-run on a stack.

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
   ├─ 2. cluster          DBSCAN, great-circle eps 5 km, min 2 samples (off the event loop)
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
│                        Lifespan starts, and cleanly stops, the background tasks:
│                          · the Kafka report consumer and the outbox relay
│                          · the embedding-model warm-up (off the event loop)
│                          · the object-store bucket check
│                          · the pollers: Open-Meteo stations, SACHET, METAR, Mastodon, Google News
│                          · the lake archiver
│                        Serves GET /, /api/info, /healthz, WS /ws/events, and only with
│                        ENVIRONMENT=e2e, GET /api/e2e/identity.
├── core/
│   ├── config.py        pydantic-settings, reads the REPO-ROOT .env (not backend/.env).
│   │                    Every threshold lives here: dedup gates, DBSCAN, H3 resolution,
│   │                    review thresholds, poller intervals and freshness gates.
│   ├── database.py      async SQLAlchemy engine, get_db() dependency, init_db().
│   ├── security.py      accounts: bcrypt against user_profiles.password_hash; HS256 JWT
│   │                    (8 h), get_current_operator, require_roles(). Holds no password.
│   └── empty.py         empty_or_503() — the one place a read turns no rows into its empty
│                        result and a database error into 503.
├── api/                 one router per domain, each prefixed /api/<domain>
│   ├── dashboard.py     GET /summary
│   ├── events.py        GET "" (the PS's date/event/location/status filters, X-Total-Count),
│   │                    /distribution, /{id}, PATCH /{id}/review, GET /{id}/provenance
│   ├── reports.py       GET /trend, GET /recent, POST /submit (anonymous, always
│   │                    CITIZEN_APP), POST /official (COMMANDER/ADMIN → OFFICIAL_DISPATCH),
│   │                    GET /track/{docket} (open; status only, never text or place)
│   ├── meta.py          GET /filters — the filter bar's options with counts, cached 60 s
│   ├── feed.py          GET /recent
│   ├── geo.py           GET /heatmap
│   ├── auth.py          POST /token — an account's username and password; one 401 for an
│   │                    unknown user, a wrong password or an account with none set
│   ├── teams.py         team records; create and dispatch need COMMANDER/ADMIN
│   ├── profile.py       operator records; /me is the token's own, read or edited
│   ├── alerts.py        GET /agency, /agency/{id}/polygon — official SACHET warnings
│   └── audit.py         GET /recent — newest ledger rows, whole chain verified
├── models/              SQLAlchemy ORM, one file per table, plus enums.py for every
│                        controlled vocabulary (SourceType, Severity, ReviewStatus,
│                        Quadrant, Agency, AuditAction, OperatorRole, …)
├── services/            where the intelligence lives
│   ├── ingest.py        store_report(): the report and its outbox message in one
│   │                    transaction, then an immediate publish if the producer is up.
│   │                    Dockets, and the HMAC reporter pseudonym.
│   ├── kafka.py         the process's one Kafka producer. Requests never connect;
│   │                    the outbox relay (re)starts it.
│   ├── hazards.py       the hazard taxonomy: 16 event types, 4 families, precedence,
│   │                    labels and gradients, in one table.
│   ├── pipeline.py      the orchestrator above. Fails soft: one bad report cannot
│   │                    kill the consumer loop. Stamps processed_at on every report
│   │                    it finishes with.
│   ├── fusion_engine.py compute_receipt / assign_quadrant / determine_review_status.
│   ├── dedup.py         the three-gate AND. MiniLM encode runs in a thread.
│   ├── geo_clustering.py DBSCAN (haversine), H3 assignment, cluster stats, report→event linking.
│   ├── geocoding.py     India bounds check; forward and reverse geocoding over the
│   │                    737-district gazetteer (data/geo/india_districts.csv).
│   ├── credibility.py   source prior × text quality, per report.
│   ├── text_processing.py cleaning, language detection, depth and place extraction.
│   │                    Regex and dictionaries. No model.
│   ├── weather.py       Open-Meteo 24 h accumulation → IMD daily-category curve.
│   ├── cache.py         Redis, with an in-memory fallback. Never load-bearing.
│   ├── audit.py         the SHA-256 hash chain.
│   ├── event_publisher.py verified events → indra.verified.events
│   └── health.py        the six real checks behind /healthz, including the outbox backlog
│                        and the object store.
├── workers/
│   ├── report_consumer.py  aiokafka consumer driving the pipeline.
│   ├── outbox_relay.py     publishes every outbox row the request could not, every 2 s,
│   │                       FOR UPDATE SKIP LOCKED, so no report is lost to a Kafka outage.
│   ├── station_poller.py   the scheduled Open-Meteo feed into station_readings.
│   ├── sachet_poller.py    NDMA SACHET CAP warnings into agency_alerts, every 5 min.
│   ├── metar_poller.py     airport observations into station_readings (off by default).
│   ├── mastodon_poller.py  weather-tagged Mastodon posts into raw_reports (off by default).
│   ├── news_poller.py      Google News weather headlines into raw_reports (off by default).
│   └── lake_archiver.py    every report-stream message, raw, to the object store.
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
| **PostgreSQL + PostGIS** | everything of record: `raw_reports`, `verified_events`, `station_readings`, `agency_alerts`, `audit_logs`, `outbox`, teams, and `user_profiles`, which are also the sign-in accounts | submit returns 503, sign-in returns 503, `/healthz` 503. **Critical** |
| **Redpanda** | `indra.raw.reports` in, `indra.verified.events` out | submit still returns 202 (`queued: false, will_retry: true`) and the report waits in the outbox; the relay publishes it within seconds of Redpanda returning. `/healthz` 503. **Critical**, but no longer lossy (BUG-060) |
| **Redis** | the Open-Meteo cache (`wx:{cell}`, TTL 600 s), the broadcast-dedup set (`bcast:{id}`, TTL 24 h) and the filter options (`meta:filters`, 60 s) | all fall back to process memory, `/healthz` 200 `degraded`. **Never load-bearing** |
| **Object storage** | the raw archive of every report-stream message (Phase 2), when `S3_ACCESS_KEY`/`S3_SECRET_KEY` are set | the lake archiver stays off, `/healthz` 200 `degraded`. **Never load-bearing** |

Nineteen migrations, `0001` … `0019`. Phase 1 added four: `0011` the hazard and source enum values,
`0012` the report intake columns (`observed_at`, `reporter_hash`, `docket`, `platform`,
`external_id`, `source_meta`, `citizen_hazard`, `processed_at`), `0013` the outbox, `0014` the event
filter indexes and the long-missing index on `raw_reports.event_id`. Phases 2 and 3 added `0015`
to `0017`. The 25 Sep demo removal added two: `0018` clears the badge numbers, callsigns, team role
and citizen agency that `0008` invented for the four seeded accounts, and `0019` adds
`user_profiles.password_hash`, seeded with nothing. Alembic runs every pending
migration in one transaction, so a migration never uses an enum value added in the same run. `audit_logs` carries a row-level trigger rejecting `UPDATE` and `DELETE`. On a fresh
volume, Postgres is reported healthy only once it listens on TCP, which is after `indra_db` exists
(BUG-028); `./start.sh infra up` waits for that.

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
| SACHET poller | lifespan, if `SACHET_POLLER_ENABLED` | Same: every tick wrapped, at most `SACHET_MAX_FETCHES_PER_TICK` CAP documents a tick |
| METAR, Mastodon and Google News pollers | lifespan, each off unless its `*_POLLER_ENABLED` | Same, and each records a heartbeat that `/api/meta/sources` reads |
| Outbox relay | lifespan | Publishes what a request could not, every 2 s; restarts the producer after an outage |
| Lake archiver | lifespan, if `LAKE_ARCHIVE_ENABLED` and the object store is configured | Its own consumer group; logs one line and stays off without a store |

All of them are cancelled and **awaited** at shutdown, which is what keeps
`Task was destroyed but it is pending!` out of the logs.

> **One backend process.** WebSocket fan-out is an in-process list, the poller has no leader
> election, and two consumers on one broker re-deliver reports. This is a deliberate limit of this
> single-server deployment, recorded as BUG-011, not an accident. The E2E backend is the one
> sanctioned second process: its own database, topics and consumer group (below).

---

## Configuration

Everything tunable is in `core/config.py`, read from the **repo-root `.env`**. A `backend/.env`,
if one exists, wins — which has bitten this project before.

The settings worth knowing: `DEDUP_COSINE_THRESHOLD` (0.88), `DBSCAN_EPS_KM` (5.0),
`DBSCAN_MIN_SAMPLES` (2), `H3_HEX_RESOLUTION` (8), `AUTO_PUBLISH_THRESHOLD` (0.90),
`HUMAN_REVIEW_THRESHOLD` (0.60), `STATION_POLLER_ENABLED`, `STATION_READING_MAX_AGE_MINUTES` (180),
`KAFKA_CONSUMER_GROUP` (`indra-report-processor`), `JWT_EXPIRY_HOURS` (8), `CORS_ORIGINS`.
`DEMO_MODE` and `SNAP_OUT_OF_BOUNDS_COORDINATES` were deleted on 25 Sep; a line for either left in
an old `.env` is ignored. A coordinate outside India is always a 422.

**Accounts** are the rows of `user_profiles`. A password is a bcrypt hash in `password_hash`,
set per environment with `scripts/set_operator_password.py [USERNAME ...] [--all] [--from-env VAR
| --generate]`; `NULL` means the account cannot sign in, and no hash is seeded. After deploying
`0019` to a server, run `alembic upgrade head` and then set the passwords, or nobody can sign in.
The full contract is under `/api/auth` in [`api-contract.md`](api-contract.md).

**E2E mode.** `ENVIRONMENT=e2e` is the backend the browser tests use. It refuses to start unless
the `DATABASE_URL` database name ends in `_e2e`, `KAFKA_REPORTS_TOPIC`, `KAFKA_EVENTS_TOPIC` and
`KAFKA_DLQ_TOPIC` start with `indra.e2e.`, and `KAFKA_CONSUMER_GROUP` starts with `indra-e2e-`;
only then does it serve `GET /api/e2e/identity`. `make e2e-backend` (`./start.sh e2e-backend`)
starts one on `127.0.0.1:8100` against `indra_e2e`, with Redis db 15, the lake off and every poller
off, after migrating the database and giving every account the password in
`E2E_OPERATOR_PASSWORD` (its default is in `start.sh` and exists only in `indra_e2e`).
`make e2e-reset` drops and recreates `indra_e2e` and refuses any name not ending in `_e2e`.

---

## Testing

```bash
cd backend
.venv/bin/pytest -q                                   # 948 passed, 2 skipped
.venv/bin/pytest -q -m "not integration"              # no Docker needed
.venv/bin/pytest -q -m "not integration and not network"   # fully offline
```

The suite runs against its own **`indra_test`** database and cannot touch dev data. Its login
tests give `indra_test`'s accounts passwords of their own; none is written in `app/`. Integration
tests carry `@pytest.mark.integration`; anything hitting the network carries `network`. The
browser tests run against the E2E backend above, never the dev stack.

**The suite is necessary and not sufficient.** Every one of the most serious defects found in this
project was invisible to a green suite and was caught by running the thing end to end from an
empty volume, or by disbelieving a number that looked too good. Two examples, both in
[`bug-register.md`](bug-register.md): an empty database answering with a fabricated
`0.94 / AUTO_PUBLISHED` event that 518 passing tests could not see, and a station poller storing
one hour of rain where the score curve expected a day of it. **Rehearse from cold, and probe every
number that flatters you.**
