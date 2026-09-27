# INDRA — Backend Architecture

| | |
|---|---|
| **Scope** | `backend/`: layers 1–3, 5, 6, 7 and 8a. The whole system is in [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **Applies to** | `main` after Phase 4 (PR #47), migration head `0020_verification_v2` |
| **Last reviewed** | 28 Sep 2026, against the code. The Phase 4 suite ran on 27 Sep |

How the backend is put together: module boundaries, what each module owns, and the exact path a
citizen report takes from an HTTP request to a pin on the dashboard.

Two neighbouring layers have their own owners and documents. Layer 4 (AI/ML) is six frozen local
components that write advisory results and never a fusion factor
([ML architecture](ML_ARCHITECTURE.md)). Layer 8b (alerts) is the standalone service in
`alert_engine/` ([integration](ALERT_ENGINE_INTEGRATION.md)). Nothing below waits on either.

---

## The one path that matters

```
POST /api/reports/submit
   │  validate (India bounds, 5–2000 chars)  ─── outside → 422, nothing stored
   │  geocode, H3 res-8 cell, credibility score, rule-based analysis
   │  INSERT raw_reports + outbox message in one transaction ─── failed → 503
   ▼
outbox relay / process Kafka producer ──► indra.raw.reports (Redpanda)
   │
   ▼  workers/report_consumer.py
   │  broadcast NEW_REPORT once per report id (Redis-backed, survives restart)
   ▼  services/pipeline.py :: process_report
   │
   ├─ 1. dedup            frozen local Phase 19 matcher AND ≤ 1 km AND ≤ 15 min
   │                      a duplicate is marked duplicate_of and stops here
   ├─ advisory ML         typed UnifiedMLResult at raw_reports.analysis.ml
   ├─ 2. cluster          DBSCAN per hazard family, great-circle radius (5 km for water,
   │                      up to 25 km for heat), min 2 samples (off the event loop)
   ├─ 3. stats            centroid, radius, max pairwise distance, in metres
   ├─ 4. evidence         Phase 4: the hazard's own variable — an airport METAR within 50 km,
   │                      else Open-Meteo (one hourly request per res-7 cell); floods keep the
   │                      24 h rainfall (station_readings, else live); SACHET warnings in force;
   │                      the published contradiction table; news counted by publisher
   ├─ 5. score            receipt v2 (7 factors), re-normalised over the factors that reported,
   │                      and a verdict: CORROBORATED · CONTRADICTED · UNCONFIRMED
   ├─ 6. severity         max(content axis, corroboration axis), from the report texts
   └─ 7. persist          ONE transaction: event + boundary polygon + report links + audit row
   │
   ├──► WebSocket  VERIFIED_EVENT
   └──► indra.verified.events
```

NLP, credibility, deterministic event grouping, image and anomaly inference run locally as
advisory evidence when inputs exist; unavailable inputs remain `NOT_RUN`. Their synthetic scores
do not alter the legacy fusion decision. Alert dispatch is still not built.

---

## Module map

```
backend/app/
├── main.py              FastAPI entrypoint. Explicit CORS origin list (not "*").
│                        Lifespan starts, and cleanly stops, the background tasks:
│                          · the Kafka report consumer and the outbox relay
│                          · the frozen local matcher warm-up (off the event loop)
│                          · the object-store bucket check
│                          · the pollers: Open-Meteo stations, SACHET, METAR, Mastodon, Google News
│                          · the lake archiver
│                        Serves GET /, /api/info, /healthz, WS /ws/events, and only with
│                        ENVIRONMENT=e2e, GET /api/e2e/identity (api/e2e_identity.py).
├── core/
│   ├── config.py        pydantic-settings, reads the REPO-ROOT .env (not backend/.env).
│   │                    Every threshold lives here: dedup gates, DBSCAN, H3 resolution,
│   │                    review thresholds, poller intervals and freshness gates.
│   ├── database.py      async SQLAlchemy engine, get_db() dependency, init_db().
│   ├── security.py      accounts: bcrypt against user_profiles.password_hash; HS256 JWT
│   │                    (8 h), get_current_operator, require_roles(). Holds no password.
│   ├── empty.py         empty_or_503() — the one place a read turns no rows into its empty
│   │                    result and a database error into 503.
│   └── e2e.py           the E2E backend's isolation guard: refuses to start on a
│                        non-E2E database, topic, consumer group or with the lake on.
├── api/                 one router per domain, each prefixed /api/<domain>
│   ├── dashboard.py     GET /summary
│   ├── events.py        GET "" (date/type/location/status/verdict filters, X-Total-Count),
│   │                    /distribution, /export, /{id}, PATCH /{id}/review,
│   │                    POST|DELETE /{id}/claim (15 min), GET /{id}/history, /{id}/provenance
│   ├── review.py        GET /api/review/queue: pending, contradicted, suspicious,
│   │                    high_impact and recent tabs, with counts and claim state
│   ├── reports.py       GET /trend, GET /recent, POST /submit (anonymous, always
│   │                    CITIZEN_APP), POST /official (COMMANDER/ADMIN → OFFICIAL_DISPATCH),
│   │                    GET /track/{docket} (open; status only, never text or place)
│   ├── report_search.py GET /api/reports/search and /export (ANALYST+; the export is audited)
│   ├── query_params.py  the shared list-parameter rules of the filtered routes
│   ├── meta.py          GET /filters (cached 60 s) and /sources (each feed's heartbeat)
│   ├── feed.py          GET /recent
│   ├── geo.py           GET /heatmap, /stations
│   ├── stations.py      GET /api/stations/latest: the newest airport observations
│   ├── auth.py          POST /token — an account's username and password; one 401 for an
│   │                    unknown user, a wrong password or an account with none set
│   ├── teams.py         team records; create and dispatch need COMMANDER/ADMIN
│   ├── profile.py       operator records; /me is the token's own, read or edited
│   ├── alerts.py        GET /agency, /agency/{id}/polygon — official SACHET warnings
│   ├── audit.py         GET /recent — newest ledger rows, whole chain verified
│   └── e2e_identity.py  GET /api/e2e/identity, mounted only with ENVIRONMENT=e2e
├── models/              SQLAlchemy ORM, one file per table, plus enums.py for every
│                        controlled vocabulary (SourceType, Severity, ReviewStatus,
│                        Quadrant, Agency, AuditAction, OperatorRole, …)
├── services/            where the intelligence lives
│   ├── ingest.py        store_report(): the report and its outbox message in one
│   │                    transaction, then an immediate publish if the producer is up.
│   │                    Dockets, and the HMAC reporter pseudonym. Pollers use it too.
│   ├── kafka.py         the process's one Kafka producer. Requests never connect;
│   │                    the outbox relay (re)starts it.
│   ├── pipeline.py      the orchestrator above, plus rescore_event() for late
│   │                    corroboration and the v2 backfill. Fails soft: one bad report
│   │                    cannot kill the consumer loop. Stamps processed_at.
│   ├── fusion_engine.py compute_receipt / assign_quadrant / determine_review_status /
│   │                    review_caps (contradicted, unclassified, posts_only).
│   ├── evidence.py      Phase 4: each hazard's own weather variable, METAR within 50 km
│   │                    before the Open-Meteo model; the published contradiction table.
│   ├── official_warnings.py  Phase 4: the SACHET warnings in force that cover an event.
│   ├── late_corroboration.py Phase 4: re-scores open events when a warning or a
│   │                    significant airport observation arrives after them.
│   ├── clock.py         "now" for every evidence-window decision, so a re-score and a
│   │                    test read the same clock.
│   ├── hazards.py       the hazard taxonomy: 16 event types, 4 families (radius and
│   │                    time window each), precedence, labels and gradients, in one table.
│   ├── hazard_tagger.py Phase 3: which hazards a text describes, in English, Hindi and
│   │                    Hinglish, with negation, tense and the numbers it quotes.
│   ├── report_flags.py  Phase 3: misleading-text flags and their credibility effect.
│   ├── event_typing.py  Phase 3: an event's type by majority vote, ties by precedence.
│   ├── corroboration.py Phase 3: effective independent reporters (n_eff) and news
│   │                    counted by publisher.
│   ├── severity_rules.py Phase 3: the content axis, graded on each family's own measure.
│   ├── dedup.py         frozen local Phase 19 matcher with backend spatial/time gates.
│   ├── ml_adapter.py    PostGIS history reads and typed advisory ML persistence (layer 4).
│   ├── geo_clustering.py DBSCAN (haversine), H3 assignment, cluster stats, report→event linking.
│   ├── geocoding.py     India bounds check; forward and reverse geocoding over the
│   │                    737-district gazetteer (data/geo/india_districts.csv).
│   ├── credibility.py   source prior × text quality, per report.
│   ├── text_processing.py cleaning, language detection, depth and place extraction.
│   │                    Regex and dictionaries. No model.
│   ├── weather.py       Open-Meteo 24 h accumulation → IMD daily-category curve.
│   ├── cap_parser.py    CAP 1.2 documents from SACHET → agency_alerts rows.
│   ├── metar.py         METAR parsing (layer 1).
│   ├── news_rss.py      Google News RSS parsing: bytes in, items out.
│   ├── feed_status.py   the feed registry and each poller's heartbeat.
│   ├── objectstore.py   a thin S3 client over whatever S3_ENDPOINT_URL names.
│   ├── lake.py          the data lake's raw ("bronze") layer layout and writers.
│   ├── exports.py       streaming CSV and GeoJSON exports.
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
└── ml/                  Six frozen local development components; the older below-gate
                         event_classifier.py remains quarantined legacy code.
```

---

## The scoring model, precisely

Seven factors, fixed weights (receipt v2, Phase 4, 27 Sep; v1 in brackets):

| Factor | Weight | State |
|---|---|---|
| Weather Station Corroboration | 0.20 (0.25) | online: the hazard's own variable, airport METAR preferred over the model; offline only when neither answers |
| Official Warning (IMD/SDMA via SACHET) | 0.10 (—) | online while SACHET was polled in the last 30 min (0.0 when no warning of this hazard covers the event); offline otherwise |
| Report Density Analysis | 0.20 | online |
| Spatial Coherence Score | 0.15 (0.20) | online |
| Computer Vision Analysis | 0.15 | offline: layer 4, out of scope |
| Source Reliability Index | 0.15 | online; news 0.75 from two independent publishers, 0.55 from one |
| Anomaly Detection Signal | 0.05 | offline: layer 4, out of scope |

**The verdict:** CONTRADICTED if the weather affirmatively says the opposite (the table in
`services/evidence.py`; the weather factor then scores 0.0 and the event is capped at
PENDING_HUMAN_REVIEW, never rejected); else CORROBORATED if the official warning or the weather
scores ≥ 0.6; else UNCONFIRMED. **Late corroboration** re-scores an open event when a warning or a
relevant airport observation arrives after it (`LATE_CORROBORATION` in the ledger).

```
online          = { f : score(f) is not None }
total_weighted  = Σ_online  w_f · s_f
factor_coverage = Σ_online  w_f                    → 0.80 today
confidence      = total_weighted / factor_coverage
```

An offline factor **lowers the stated coverage** rather than silently scoring zero. Before this
change two unavailable factors held 20% of the scale hostage and `AUTO_PUBLISHED` (≥ 0.90)
was mathematically unreachable — a broken scale, not honesty. The receipt publishes
`factor_coverage` beside the score so the number is both usable and truthful. **Never quote one
without the other.**

Gates: `≥ 0.90` → `AUTO_PUBLISHED` · `≥ 0.60` → `PENDING_HUMAN_REVIEW` · else `QUARANTINED`.

**The curves are published, not tuned for a demo.** Rainfall is scored against IMD's own daily
rainfall categories (0 → 0.00, 2.5 → 0.10, 15.6 → 0.35, 64.5 → 0.70, 115.6 → 0.90, 204.5+ → 1.00).
Density saturates at 25 reports. Coherence is a raised cosine over twice the DBSCAN epsilon. The
reasoning for each is in the docstring beside it.

### Severity is read, not counted

`max()` of two axes over the **non-duplicate** reports, taking the higher
(`services/severity_rules.py`, Phase 3):

| Axis | Rule |
|---|---|
| Content: water | deepest quoted depth ≥ 120 cm CRITICAL · ≥ 60 HIGH · ≥ 20 MODERATE; or 24 h rain on IMD's categories (≥ 204.5 mm · ≥ 115.6 · ≥ 64.5) |
| Content: thermal | IMD plains criteria: heat ≥ 47 °C · ≥ 45 · ≥ 40; cold ≤ 2 °C · ≤ 4 · ≤ 10 |
| Content: visibility | IMD fog classes: < 50 m · < 200 · < 500 |
| Content: convective | Beaufort wind: ≥ 89 km/h · ≥ 62 · ≥ 39 |
| Impact floor | stranded, rescue, heatstroke, trees uprooted → at least HIGH; drowned, died, house collapsed → CRITICAL. A denied impact sets none |
| Corroboration (report count) | ≥ 10 HIGH · ≥ 5 MODERATE · else ADVISORY |

The count axis **never reaches CRITICAL**: a count is evidence that something is happening, not of
how bad it is. The depth cuts are operational — 20 cm stops a two-wheeler, 60 cm floats a small
car, 120 cm turns wading into a rescue — and every other cut is a published IMD or Beaufort
threshold, numbers a nodal officer can argue with, which is the point. The receipt names the
winning axis and the phrase it read.

---

## The data platform

| Store | What it holds | What happens without it |
|---|---|---|
| **PostgreSQL + PostGIS** | everything of record: `raw_reports`, `verified_events`, `station_readings`, `agency_alerts`, `audit_logs`, `event_snapshots`, `outbox`, teams, and `user_profiles`, which are also the sign-in accounts | submit returns 503, sign-in returns 503, `/healthz` 503. **Critical** |
| **Redpanda** | `indra.raw.reports` in, `indra.verified.events` out | submit still returns 202 (`queued: false, will_retry: true`) and the report waits in the outbox; the relay publishes it within seconds of Redpanda returning. `/healthz` 503. **Critical**, but no longer lossy (BUG-060) |
| **Redis** | the Open-Meteo cache (`wx:{cell}`, TTL 600 s), the broadcast-dedup set (`bcast:{id}`, TTL 24 h) the filter options (`meta:filters`, 60 s), and which event–evidence pairs late corroboration has already evaluated | all fall back to process memory, `/healthz` 200 `degraded`. **Never load-bearing** |
| **Object storage** | the raw archive of every report-stream message (Phase 2), when `S3_ACCESS_KEY`/`S3_SECRET_KEY` are set | the lake archiver stays off, `/healthz` 200 `degraded`. **Never load-bearing** |

Twenty migrations, `0001` … `0020`. Phase 1 added four: `0011` the hazard and source enum values,
`0012` the report intake columns (`observed_at`, `reporter_hash`, `docket`, `platform`,
`external_id`, `source_meta`, `citizen_hazard`, `processed_at`), `0013` the outbox, `0014` the event
filter indexes and the long-missing index on `raw_reports.event_id`. Phases 2 and 3 added `0015`
to `0017`. The 25 Sep demo removal added two: `0018` clears the badge numbers, callsigns, team role
and citizen agency that `0008` invented for the four seeded accounts, and `0019` adds
`user_profiles.password_hash`, seeded with nothing. Phase 4 added `0020_verification_v2`: the
event verdict, review claims, `event_snapshots` and the `LATE_CORROBORATION` audit action; after
it, `scripts/rescore_events.py` gives every stored event a v2 receipt (idempotent). Alembic runs every pending
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
`MANUAL_OVERRIDE`; an analyst's export writes `DATA_EXPORT` (no event id); a re-score from late
evidence writes `LATE_CORROBORATION` with `{trigger, before, after}`.

> **Honest limit:** editing, deleting or reordering a row is detected at that row. Rows cut off
> the **end**, or a `TRUNCATE`, leave a valid chain. Detecting that needs an external anchor for
> the head hash, which is not built.

---

## Background tasks, and why each is safe

| Task | Started | Failure behaviour |
|---|---|---|
| Kafka report consumer | lifespan | Retries with backoff; logs the broker being offline once, not per attempt |
| Frozen local matcher warm-up | lifespan, in a thread | Local artifact load is non-fatal at startup; no MiniLM or remote checkpoint is loaded |
| Station poller | lifespan, if `STATION_POLLER_ENABLED` | Every tick wrapped; a failure logs one WARNING and the next tick retries |
| SACHET poller | lifespan, if `SACHET_POLLER_ENABLED` | Same: every tick wrapped, at most `SACHET_MAX_FETCHES_PER_TICK` CAP documents a tick |
| METAR, Mastodon and Google News pollers | lifespan, each off unless its `*_POLLER_ENABLED` | Same, and each records a heartbeat that `/api/meta/sources` reads |
| Outbox relay | lifespan | Publishes what a request could not, every 2 s; restarts the producer after an outage |
| Lake archiver | lifespan, if `LAKE_ARCHIVE_ENABLED` and the object store is configured | Its own consumer group; logs one line and stays off without a store |

All started tasks are cancelled and **awaited** at shutdown, which is what keeps
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
`KAFKA_DLQ_TOPIC` start with `indra.e2e.`, `KAFKA_CONSUMER_GROUP` starts with `indra-e2e-` and
`LAKE_ARCHIVE_ENABLED` is false (`core/e2e.py`, checked when `main.py` loads); only then does it
serve `GET /api/e2e/identity`. `make e2e-backend` (`./start.sh e2e-backend`)
starts one on `127.0.0.1:8100` against `indra_e2e`, with Redis db 15, the lake off and every poller
off, after migrating the database and giving every account the password in
`E2E_OPERATOR_PASSWORD` (its default is in `start.sh` and exists only in `indra_e2e`).
`make e2e-reset` drops and recreates `indra_e2e` and refuses any name not ending in `_e2e`.

---

## Testing

```bash
cd backend
.venv/bin/pytest -q                                   # everything; needs docker compose up
.venv/bin/pytest -q -m "not integration"              # no Docker needed
.venv/bin/pytest -q -m "not integration and not network"   # fully offline
```

Latest recorded run, 27 Sep 2026, on the tree now on `main`: **1,788 passed, 10 skipped, 2 failed**;
both failures are layer 4's CRLF hash tests (BUG-106), handed to its owner.

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
