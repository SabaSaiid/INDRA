<div align="center">

# INDRA

**Intelligent National Disaster & Weather Platform**

Turns fragmented citizen reports, official warnings and weather observations into<br>
verified, explainable weather events for India's emergency operations centres.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](backend/requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20%2B%20WebSocket-009688?style=flat-square&logo=fastapi&logoColor=white)](docs/api-contract.md)
[![PostGIS](https://img.shields.io/badge/PostgreSQL%2016-PostGIS%203.4-336791?style=flat-square&logo=postgresql&logoColor=white)](docker-compose.yml)
[![Redpanda](https://img.shields.io/badge/Redpanda-Kafka%20API-E2401B?style=flat-square&logo=apachekafka&logoColor=white)](docker-compose.yml)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=nextdotjs&logoColor=white)](frontend/package.json)
[![License: Proprietary](https://img.shields.io/badge/License-All%20rights%20reserved-red?style=flat-square)](LICENSE)
[![SIH 2026](https://img.shields.io/badge/SIH%202026-SIH26069-orange?style=flat-square)](#team)

[Overview](#overview) ·
[Architecture](#architecture) ·
[Verification model](#verification-model) ·
[Quick start](#quick-start) ·
[API](#api) ·
[Operations](#deployment) ·
[Documentation](#documentation) ·
[Status](#project-status)

</div>

---

## Overview

When a cloudburst, flash flood or heatwave hits, a district emergency operations centre receives
hundreds of signals at once: citizens describing what they see, official bulletins, automated
weather observations, social posts and news headlines. Many describe the same incident in different
words. Some are copies. Some are wrong. The operator has to decide what is actually happening,
where it is happening, how serious it is and how sure anyone can be.

**INDRA answers that question as data.** It ingests every signal into one stream, cleans and
geocodes it, removes duplicates, clusters reports in space and time by hazard, and checks each
cluster against independent evidence (airport METAR observations, modelled weather and official
IMD/CWC/SDMA warnings). The output is one **verified weather event** per incident. It carries a
boundary polygon, a severity, a verdict and a **Verification Receipt** that shows every factor
behind its confidence score. Every machine decision and every human review is written to a
tamper-evident, hash-chained audit ledger.

### Capabilities

| Area | What INDRA does |
|---|---|
| **Ingestion** | REST intake with a transactional outbox into Redpanda (Kafka API). Scheduled pollers for NDMA SACHET CAP warnings, Open-Meteo, METAR from Indian aerodromes, Mastodon and Google News. A dead-letter queue, and a raw archive in an S3-compatible data lake |
| **Processing** | India-bounds validation, forward and reverse geocoding over a 737-district gazetteer, H3 indexing, rule-based cleaning and metadata extraction in English, Hindi and Hinglish, a hazard tagger covering 16 event types, misleading-text flags and coordinated-text detection |
| **Geo-analytics** | Great-circle DBSCAN per hazard family, concave-hull event boundaries, and multi-resolution H3 heatmaps |
| **Event fusion** | A deterministic seven-factor Verification Receipt with published factor coverage. Verdicts are `CORROBORATED`, `CONTRADICTED` or `UNCONFIRMED`. Severity uses each hazard's own measure. Late evidence re-scores open events |
| **Governance** | A human review queue with time-limited claims, role-based access control on every write, a SHA-256 hash-chained audit ledger and per-event history snapshots |
| **Delivery** | REST and WebSocket push to the command-center dashboard, CSV/GeoJSON exports for analysts, and a health endpoint that checks every dependency |

---

## Architecture

INDRA is a **modular monolith**: one FastAPI process hosts the API, the WebSocket fan-out, the
Kafka consumer, the outbox relay and every poller as supervised asyncio tasks. Stateful services
(PostGIS, Redis, Redpanda, SeaweedFS) run alongside it under Docker Compose. Each column below is
one layer of the platform's nine-layer reference architecture. A report or a feed item travels
from left to right.

<p align="center">
  <a href="docs/architecture/01-end-to-end-system.svg">
    <img src="docs/architecture/01-end-to-end-system.svg" alt="INDRA end-to-end system architecture: data sources, ingestion, processing, geo-analytics, event fusion, data platform, real-time API and consumers" width="100%">
  </a>
  <br>
  <sub><b>Figure 1.</b> End-to-end system. ②–⑦ are the steps of <code>pipeline.process_report()</code>. Click to open full size.</sub>
</p>

The diagram source is [`docs/architecture/indra-system-architecture.drawio`](docs/architecture/indra-system-architecture.drawio).
Open it in [diagrams.net](https://app.diagrams.net) or the draw.io desktop app. It holds four pages:

| View | What it shows |
|---|---|
| [End-to-end system](docs/architecture/01-end-to-end-system.svg) | Every layer, module and data flow (Figure 1) |
| [Report lifecycle](docs/architecture/02-report-lifecycle.svg) | One report from intake to a decision: dedup, clustering, scoring, routing, human review, late corroboration |
| [Deployment](docs/architecture/03-deployment.svg) | The reference single-node deployment: edge, services, ports and outbound calls |
| [Data model](docs/architecture/04-data-model.svg) | Tables, topics and files, with their relationships |

### Layers

| # | Layer | Responsibility | Key modules |
|:-:|---|---|---|
| 1 | **Data sources** | Citizen and official reports; SACHET, Open-Meteo, METAR, Mastodon, Google News | `api/reports.py`, `workers/*_poller.py` |
| 2 | **Ingestion** | Transactional intake, outbox relay, Kafka topics, dead-letter queue, raw data lake | `services/ingest.py`, `workers/outbox_relay.py`, `workers/report_consumer.py`, `workers/lake_archiver.py` |
| 3 | **Processing** | Validation, geocoding, text cleaning, hazard tagging, flags, credibility, deduplication | `services/text_processing.py`, `hazard_tagger.py`, `report_flags.py`, `geocoding.py`, `dedup.py` |
| 4 | **AI/ML** *(advisory)* | Six frozen local components produce typed advisory results. They never enter the fusion score | `app/ml/`, `services/ml_adapter.py` |
| 5 | **Geo-analytics** | DBSCAN clustering, H3 indexing, boundary polygons, heatmaps | `services/geo_clustering.py`, `api/geo.py` |
| 6 | **Event fusion** | Evidence gathering, the receipt, verdicts, severity, routing, late corroboration | `services/pipeline.py`, `evidence.py`, `fusion_engine.py`, `severity_rules.py`, `late_corroboration.py` |
| 7 | **Data platform** | PostgreSQL + PostGIS (20 migrations), Redis, SeaweedFS object store, audit chain | `models/`, `alembic/`, `services/audit.py`, `services/objectstore.py` |
| 8a | **Real-time API** | REST, WebSocket, authentication and RBAC, review queue, health | `api/`, `core/security.py`, `main.py` |
| 8b | **Alert engine** | A separate service in [`alert_engine/`](alert_engine/) (port 8001), maintained independently and not part of the core deployment | [`docs/ALERT_ENGINE_INTEGRATION.md`](docs/ALERT_ENGINE_INTEGRATION.md) |
| 9 | **Command center** | The Next.js dashboard: live map, events, reports, review, analytics. Built by Saba Saeed | [`frontend/`](frontend/) |

### The live path

```
Citizen report ─► POST /api/reports/submit ─► raw_reports + outbox (one transaction) ─► Redpanda
                                                                                           │
                                                          workers/report_consumer ◄────────┘
                                                                     │
      ② dedup ─► ②b coordinated text ─► ③④ DBSCAN cluster ─► ⑤ geometry ─► ⑤a merge into a recent event
                                                                     │
      ⑥ evidence: METAR ≤ 50 km · Open-Meteo · SACHET warnings · news by publisher
      ⑥ receipt v2 ─► verdict ─► severity ─► routing
                                                                     │
      ⑦ one transaction: verified_events + boundary polygon + report links + snapshot + audit row
                                                                     │
          WebSocket VERIFIED_EVENT ◄─────────────────────────────────┤
          indra.verified.events    ◄─────────────────────────────────┘

      Commander: claim ─► PATCH /api/events/{id}/review ─► HUMAN_APPROVED | REJECTED + audit row ─► EVENT_REVIEWED
      New SACHET warning or METAR observation ─► late corroboration re-scores open events ⑥ → ⑦
```

### Engineering principles

- **An absent signal is reported, never invented.** A factor with no real input is marked
  `offline` with a reason. Confidence is re-normalised over the factors that reported, and the
  share of the model that reported is published beside it as `factor_coverage`.
- **Deterministic scoring.** There is no randomness anywhere in the pipeline. The same cluster and
  the same evidence produce a byte-identical receipt, and a test pins this.
- **No silent data loss.** A report and its Kafka message commit in one transaction. The relay
  publishes whatever a request could not. A message that fails three times goes to a dead-letter
  topic, and the lake archiver commits offsets only after the object write succeeds.
- **Humans hold final authority.** A reviewer's decision survives later merges and re-scores.
  A contradicted event is capped at human review and never auto-rejected, and events built only
  from posts or with an unclassified hazard always wait for a person.
- **Degrade, don't fail.** Redis, the object store and Open-Meteo are non-critical. When one is
  down, `/healthz` reports `degraded` and every report is still accepted.
- **No fallback data.** No demo mode exists and no read returns a placeholder payload. No rows
  gives the real empty result, an unknown id gives `404` and a database error gives `503`.

---

## Verification model

### The Verification Receipt

Every event carries a receipt (`receipt_version: 2`). The receipt lists each factor, the evidence
behind it, its score and its weight:

```
online           = { factors that reported a score }
confidence       = Σ_online (weight × score) / Σ_online weight
factor_coverage  = Σ_online weight
```

| Factor | Weight | Evidence |
|---|:-:|---|
| Weather station corroboration | 0.20 | The hazard's own variable (rain, temperature, wind, visibility…). An airport METAR within 50 km is used first, otherwise the Open-Meteo model |
| Official warning | 0.10 | IMD, CWC and SDMA warnings in force that cover the event, from NDMA SACHET. The factor is online while the feed was polled in the last 30 minutes |
| Report density | 0.20 | *Effective* independent reporters, so coordinated copies and repeat reporters count once |
| Spatial coherence | 0.15 | The cluster's span relative to its hazard family's search radius |
| Source reliability | 0.15 | A documented per-source prior. News scores 0.75 from two independent publishers and 0.55 from one |
| Computer vision | 0.15 | `offline`. Image analysis is not part of the scoring path |
| Anomaly detection | 0.05 | `offline`. Anomaly detection is not part of the scoring path |

With vision and anomaly permanently offline, **coverage is 0.80 and is always quoted with the
score**. The frozen AI/ML components (layer 4) write separate advisory results to
`raw_reports.analysis.ml`, and those results never feed a fusion factor.

### Verdict and routing

| Verdict | Rule |
|---|---|
| `CONTRADICTED` | The measured weather affirmatively contradicts the claim, for example a heatwave reported beside an airport that measured 20 °C. The weather factor scores 0, and the event is capped at `PENDING_HUMAN_REVIEW` and never auto-rejected |
| `CORROBORATED` | There is no contradiction, and the official warning or the weather scores ≥ 0.6 |
| `UNCONFIRMED` | Everything else |

| Confidence | Status |
|---|---|
| ≥ 0.90 | `AUTO_PUBLISHED`, unless capped: contradicted, posts only, or an unclassified hazard |
| ≥ 0.60 | `PENDING_HUMAN_REVIEW` |
| < 0.60 | `QUARANTINED`, **except `HIGH` or `CRITICAL` severity, which goes to review**. A catastrophic claim is never quarantined |

The thresholds are `AUTO_PUBLISH_THRESHOLD` and `HUMAN_REVIEW_THRESHOLD` in `.env`. The receipt's
`routing.basis` records why an event landed where it did.

### Severity

Severity is `max(content axis, corroboration axis)`. The content axis reads the worst value any
report quotes, graded on the hazard's own published scale:

| Hazard family | Measure | MODERATE | HIGH | CRITICAL |
|---|---|---|---|---|
| Water | depth | ≥ 20 cm | ≥ 60 cm | ≥ 120 cm |
| Water | 24 h rain (IMD) | ≥ 64.5 mm | ≥ 115.6 mm | ≥ 204.5 mm |
| Thermal, heat (IMD) | max temperature | ≥ 40 °C | ≥ 45 °C | ≥ 47 °C |
| Thermal, cold (IMD) | min temperature | ≤ 10 °C | ≤ 4 °C | ≤ 2 °C |
| Visibility (IMD fog classes) | visibility | < 500 m | < 200 m | < 50 m |
| Convective (Beaufort) | wind | ≥ 39 km/h | ≥ 62 km/h | ≥ 89 km/h |

Impact words set a floor ("stranded", "rescue" → HIGH; "drowned", "house collapsed" → CRITICAL);
a denied impact sets none. The corroboration axis tops out at HIGH, because a count shows that
something is happening but not how bad it is. The receipt names the winning axis and the phrase it
read. Full rules: [`services/severity_rules.py`](backend/app/services/severity_rules.py).

### A measured example

Five labelled synthetic "heatwave, 47 degree" reports were placed 5 km from Dehradun airport and
scored against that day's real observations on 27 Sep 2026 by
[`scripts/run_verification_demo.py`](scripts/run_verification_demo.py), which writes nothing to
the database:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                  VERIFICATION RECEIPT — receipt_version 2                    │
├──────────────────────────────────────────────────────────────────────────────┤
│  Weather station corroboration (20%)  0.00 × 0.20 = 0.0000   CONTRADICTED    │
│     VIDN (Dehradun airport, 5 km) measured a maximum of 20.0 °C; a heatwave  │
│     claim is contradicted below 35 °C on the plains (Open-Meteo: 20.3 °C)    │
│  Official warning (IMD/SDMA)   (10%)  0.00 × 0.10 = 0.0000                   │
│     no official warning in force covers this event (SACHET, polled < 30 min) │
│  Report density                (20%)  0.55 × 0.20 = 0.1097   5 witnesses     │
│  Spatial coherence             (15%)  1.00 × 0.15 = 0.1498                   │
│  Computer vision               (15%)  offline                                │
│  Source reliability            (15%)  0.60 × 0.15 = 0.0900   citizen reports │
│  Anomaly detection              (5%)  offline                                │
├──────────────────────────────────────────────────────────────────────────────┤
│  total_weighted 0.3495 / factor_coverage 0.80 = confidence 0.4369            │
│  VERDICT: CONTRADICTED   →  PENDING_HUMAN_REVIEW (never auto-rejected)       │
└──────────────────────────────────────────────────────────────────────────────┘
```

The same run scored a genuine case at **0.712, `CORROBORATED`**: five flood reports in
Uttarkashi under an Extreme Uttarakhand SDMA rain warning, where 54.6 mm had fallen.

---

## Data sources

| Source | Content | Format | Cadence | Default |
|---|---|---|---|:-:|
| Citizens | The dashboard's Report Incident form: text, location, time and an optional hazard | JSON over HTTPS | on demand | on |
| Commanders and admins | Official field reports, attributed to the signed-in operator | JSON + JWT | on demand | on |
| [NDMA SACHET](https://sachet.ndma.gov.in) | IMD, CWC and state SDMA warnings with area polygons | CAP 1.2 XML | 5 min | on |
| [Open-Meteo](https://open-meteo.com) | 24 h precipitation for six cities, plus per-event hourly weather | JSON | 10 min | on |
| [aviationweather.gov](https://aviationweather.gov) | METAR observations from Indian aerodromes (ICAO VA/VE/VI/VO) | CSV | 10 min | off |
| Mastodon | Posts tagged `#IMD` and other weather hashtags | JSON | 5 min | off |
| Google News | Weather headlines in English and Hindi (headline, link and publisher only) | RSS | 15 min | off |

No source needs an API key. Pollers marked *off* are enabled with `*_POLLER_ENABLED=true` in
`.env`. The status of each feed (heartbeat, rows in the last 24 h, last error) is available at
`GET /api/meta/sources`. The IMD API, CWC river gauges and Twitter/X are **not** connected. The IMD
API requires IP whitelisting, and SACHET is the public route to IMD and CWC warnings.

---

## Tech stack

| Concern | Technology |
|---|---|
| API and workers | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, asyncio |
| Streaming | Redpanda 23.3 (Kafka API), aiokafka |
| Database | PostgreSQL 16, PostGIS 3.4, SQLAlchemy 2 (async, asyncpg), GeoAlchemy2, Alembic |
| Geospatial | Uber H3 v4, scikit-learn DBSCAN (haversine), Shapely |
| Cache | Redis 7 |
| Object storage | SeaweedFS 4.47 (S3 API) via boto3. Any S3-compatible store works with only a configuration change |
| Security | JWT (HS256), bcrypt, role-based access control, HMAC reporter pseudonyms |
| Command center | Next.js 14, React 18, TypeScript, MapLibre GL, Recharts |
| Testing | pytest (asyncio, integration and network markers), Playwright |
| Operations | Docker Compose, Caddy 2 (automatic TLS), systemd |

---

## Quick start

### Prerequisites

- Docker with Compose v2
- Python 3.11+
- Node.js 18+ and npm (only for the dashboard)
- `make` and `openssl`

### Run the stack

```bash
git clone https://github.com/SabaSaiid/INDRA.git
cd INDRA
cp .env.example .env

# Object-store keys: generate them, then write SeaweedFS's identity file.
# This must happen before the first `docker compose up`.
sed -i.bak -e "s/^S3_ACCESS_KEY=.*/S3_ACCESS_KEY=$(openssl rand -hex 12)/" \
           -e "s/^S3_SECRET_KEY=.*/S3_SECRET_KEY=$(openssl rand -hex 32)/" .env && rm .env.bak
python3 scripts/make_s3_config.py

make infra-up                      # PostGIS, Redis, Redpanda, SeaweedFS; waits for healthy
make setup                         # backend virtualenv + dependencies (and the dashboard's, if npm is present)
(cd backend && .venv/bin/alembic upgrade head)
backend/.venv/bin/python scripts/set_operator_password.py --all --generate   # prints each password once

make dev                           # API on http://localhost:8000
```

Verify it:

```bash
curl -s localhost:8000/healthz | jq .status            # "healthy"
curl -s localhost:8000/api/meta/sources | jq '.feeds'  # each feed's state
open http://localhost:8000/docs                         # OpenAPI / Swagger UI
```

Run the command center in a second terminal:

```bash
cd frontend && npm install && npm run dev               # http://localhost:3000
```

**Operator accounts.** The accounts `admin`, `commander`, `analyst` and `citizen` are rows in
`user_profiles`. Each signs in against a bcrypt hash, and a fresh database has no hashes, so no
account can sign in until you set its password. No password is stored in this repository.
[`docs/setup.md`](docs/setup.md) covers the other ways to set passwords, the object store,
troubleshooting and running without `make`.

**Seeing it work.** Within minutes of startup the pollers fill the warnings, rainfall and feed
panels. An event forms when two independent reports of the same hazard family fall within the
family's radius, for example 5 km for floods. A single report never makes an event. Nothing in
the repository generates or replays reports. To exercise the pipeline with test input, use the
test suites, which write only to their own databases.

### Developer commands

| Command | Description |
|---|---|
| `make dev` · `make bg` · `make stop` · `make restart` | Run the API in the foreground or background, stop it or restart it |
| `make status` · `make logs` · `make doctor` | Process and container status, streaming logs and a full environment audit |
| `make infra-up` · `make infra-down` | Start or stop the Docker services |
| `make test` · `make test-integration` | Unit tests, or the full suite (needs Docker), on the isolated `indra_test` database |
| `make e2e-backend` · `make e2e` · `make e2e-reset` | A disposable backend on `:8100` / `indra_e2e`, and Playwright against it |
| `make smoke` | HTTP probes against a running backend |

The `make` targets are shortcuts for `./start.sh` subcommands and the test runners. Run
`./start.sh help` for the full list.

---

## Configuration

All settings are environment variables, read from the repository-root `.env` through
`backend/app/core/config.py`. [`.env.example`](.env.example) documents every one.

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` refuses the committed `SECRET_KEY` and any key shorter than 32 characters. `e2e` enforces an isolated database, topics and consumer group |
| `SECRET_KEY` | development value | Signs JWTs. Generate a key per deployment with `openssl rand -hex 32` |
| `REPORTER_SALT` | empty | HMAC key for reporter pseudonyms. Set it per deployment and keep it stable |
| `DATABASE_URL` | `…@localhost:5433/indra_db` | PostGIS runs on port 5433, so it cannot clash with a local Postgres |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Redpanda |
| `AUTO_PUBLISH_THRESHOLD` / `HUMAN_REVIEW_THRESHOLD` | `0.90` / `0.60` | Routing gates |
| `DBSCAN_EPS_KM` / `DBSCAN_MIN_SAMPLES` | `5.0` / `2` | Base clustering parameters. Hazard families set their own radius and time window |
| `SACHET_POLLER_ENABLED`, `STATION_POLLER_ENABLED` | `true` | Official warnings and Open-Meteo |
| `METAR_POLLER_ENABLED`, `MASTODON_POLLER_ENABLED`, `NEWS_POLLER_ENABLED` | `false` | Airport observations, posts and headlines |
| `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | local SeaweedFS | Data lake. With placeholder keys the lake is disabled and health reports `degraded` |
| `CORS_ORIGINS` | `localhost:3000` | An explicit allow-list, never `*` |

> A `backend/.env`, if present, takes precedence over the root `.env`. Keep a single `.env` at the
> repository root.

---

## API

The complete contract lists every endpoint, request and response shape, status code and auth rule
in [`docs/api-contract.md`](docs/api-contract.md). Interactive documentation is served at `/docs`.

| Group | Endpoints | Access |
|---|---|---|
| `/api/reports` | `submit`, `official`, `track/{docket}`, `trend`, `recent`, `search`, `export` | `submit` and `track` are anonymous. `official` needs COMMANDER/ADMIN. `search` and `export` need ANALYST+ |
| `/api/events` | list (date, type, location, status and verdict filters), `distribution`, `{id}`, `review`, `claim`, `history`, `provenance`, `export` | Reads are open. Review and claim need COMMANDER/ADMIN. History, provenance and export need ANALYST+ |
| `/api/review` | `queue`: pending, contradicted, suspicious, high-impact and recent tabs, with claim state | ANALYST+ |
| `/api/geo`, `/api/stations` | H3 heatmap, rainfall stations, latest airport observations | open |
| `/api/alerts` | Official SACHET warnings in force, with polygons | open |
| `/api/meta`, `/api/feed`, `/api/dashboard` | Filter options, feed health, activity feed, KPI summary | open |
| `/api/audit` | Newest ledger rows, with the chain verified | ANALYST+ |
| `/api/auth`, `/api/profile`, `/api/teams` | Sign-in, operator profile, response teams | Every write needs a token |
| `/healthz` | Dependency health: Postgres, Kafka, Redis, Open-Meteo, the object store and the outbox backlog. `200 healthy`, `200 degraded` or `503 unhealthy` | open |

**WebSocket** `/ws/events` pushes `NEW_REPORT`, `NEW_FEED_ITEM`, `VERIFIED_EVENT`,
`EVENT_REVIEWED` and `EVENT_CLAIMED`.

Every state-changing endpoint requires a token, except sign-in and citizen report submission,
which are anonymous by design. `tests/test_mutation_auth.py` walks the whole router tree and fails
the build if a mutation ships without a guard.

---

## Testing

```bash
cd backend
.venv/bin/pytest -q -m "not integration"                    # unit tests, no Docker
.venv/bin/pytest -q                                         # full suite, needs `make infra-up`
.venv/bin/pytest -q -m "not integration and not network"    # fully offline
```

| Suite | Scope | Isolation |
|---|---|---|
| Backend (pytest) | Unit and integration: pipeline, receipt, evidence, auth matrix, audit chain, migrations, pollers | Its own `indra_test` database. The suite refuses to run against any other |
| Browser (Playwright) | The command center against a real backend | A disposable backend on `127.0.0.1:8100` with the `indra_e2e` database, `indra.e2e.*` topics and every poller off |

Latest recorded run, 27 Sep 2026, on the code now on `main`: **1,788 passed, 10 skipped and 2
known failures**, both in the layer-4 AI/ML package
([BUG-106](docs/bug-register.md)).

---

## Deployment

The reference deployment is a single Linux host (see
[Deployment view](docs/architecture/03-deployment.svg)):

- **Edge:** Caddy 2 terminates TLS with automatically renewed Let's Encrypt certificates. It routes
  `/api/*`, `/ws/*`, `/healthz` and `/docs` to Uvicorn on `:8000`, and everything else to the
  Next.js server on `:3000`. See [`infra/caddy/Caddyfile`](infra/caddy/Caddyfile).
- **Processes:** the API and the dashboard run as systemd services. The stateful services run
  under Docker Compose, and the host firewall never opens their ports. SeaweedFS also binds to
  `127.0.0.1` only.
- **Release:** `git pull`, `alembic upgrade head`, restart. After upgrading an existing database
  to migration `0020`, run `scripts/rescore_events.py` once, which is idempotent, so that every
  stored event gets a v2 receipt and a verdict.

> **Run exactly one backend process.** WebSocket fan-out is in-process, and pollers have no leader
> election. The E2E backend is the only sanctioned second process, with its own database, topics
> and consumer group.

### Security

- **Authentication:** bcrypt password hashes in `user_profiles` and HS256 JWTs (8 h). Roles are
  `CITIZEN`, `ANALYST`, `COMMANDER`, `ADMIN` and `FIELD_RESPONDER`.
- **Authorization:** every mutation is role-guarded, and a route-walking test enforces this.
  Provenance, history, exports and the audit ledger require ANALYST or above.
- **Integrity:** the audit ledger is an append-only SHA-256 hash chain. It is appended under an
  advisory lock, and a database trigger rejects `UPDATE` and `DELETE`.
- **Privacy:** a citizen's device id is stored only as an HMAC pseudonym. WebSocket payloads never
  carry dockets or reporter hashes.
- **Secrets:** none are committed. The only secret-like value in `.env.example` is a development
  JWT key, which `ENVIRONMENT=production` refuses.

Please report vulnerabilities privately to the maintainers rather than in a public issue.

---

## Project status

The core platform (layers 1–3 and 5–8a) is feature-complete through Phase 5, merged to `main` and
deployed to the team server.

| Phase | Scope | State |
|---|---|---|
| 1 · Foundation | 16 hazard types, event filters, citizen dockets, transactional outbox, HTTPS | Done |
| 2 · Collect everything | METAR, Mastodon and Google News pollers, object store and data lake, DLQ, search and export | Done |
| 3 · Every hazard | Multilingual hazard tagger, per-family clustering, hazard-specific severity, misleading-text flags | Done |
| 4 · Verification | Receipt v2, official-warning factor, per-hazard weather evidence, verdicts, late corroboration, review queue and claims | Done ([#47](https://github.com/SabaSaiid/INDRA/pull/47)) |
| 5 · Media and trust | Resumable photo and video upload, EXIF and recycled-media checks, reporter reputation, rate limits, EXIF-free serving, retention and withdrawal | Done ([#50](https://github.com/SabaSaiid/INDRA/pull/50)) |
| 6 · Scale | Analytics endpoints, bulk ingestion of real archives, load testing | Planned |

### Known limitations

| Limitation | Detail |
|---|---|
| Vision and anomaly factors are offline | Image and anomaly analysis are not part of the scoring path, so coverage is 0.80. Layer 4's components are advisory and not validated for production |
| Single process | In-process WebSocket fan-out and no poller leader election. Horizontal scale needs Redis pub/sub and leader election |
| Audit-chain tail | Tampering with, deleting or reordering a row is detected. Truncating the tail requires an external anchor for the head hash, which does not exist yet |
| Near-identical witnesses | Two people who use nearly the same words within 1 km and 15 min can be merged as duplicates, because anonymous reports carry no identity to separate them |
| No MFA | A password is the only factor for operator accounts |
| Risk zones | Not built |

The full defect history, including every fixed and open issue with its severity, is in
[`docs/bug-register.md`](docs/bug-register.md).

---

## Repository layout

```
INDRA/
├── backend/
│   ├── app/
│   │   ├── api/            REST routers: reports, events, review, geo, stations, alerts, meta, feed, audit, auth, teams, profile
│   │   ├── core/           settings, async database, security (JWT, bcrypt, RBAC), empty-result policy, E2E isolation guard
│   │   ├── models/         SQLAlchemy models and enums (every controlled vocabulary)
│   │   ├── services/       pipeline, evidence, fusion engine, dedup, clustering, geocoding, hazard tagger, severity, audit, ingest…
│   │   ├── workers/        report consumer, outbox relay, lake archiver, SACHET/Open-Meteo/METAR/Mastodon/News pollers
│   │   └── ml/             layer 4: frozen local AI/ML components (advisory)
│   ├── alembic/            migrations 0001 … 0020
│   └── tests/              pytest suite
├── frontend/               Next.js 14 command center (layer 9)
├── alert_engine/           standalone alert service (layer 8b)
├── data/
│   ├── geo/                737-district gazetteer, city aliases, Indian METAR stations
│   ├── demo/               recorded inputs for the verification demo
│   ├── labelled/           layer 4's labelled datasets
│   └── live/               exports of real rows (scripts/export_live_data.py)
├── docs/
│   ├── architecture/       system diagram (.drawio) and its exported views (.svg)
│   └── *.md                architecture, API contract, setup, runbook, bug register…
├── infra/                  Caddyfile, SeaweedFS identity file (generated, gitignored)
├── scripts/                operations: passwords, re-scoring, DLQ replay, gazetteer builds, exports, verification demo
├── docker-compose.yml      PostGIS, Redis, Redpanda, SeaweedFS
├── start.sh · Makefile     developer control suite
└── .env.example            every setting, documented
```

---

## Documentation

| Document | Read it when |
|---|---|
| [Documentation index](docs/README.md) | You want the full map of the docs |
| [Architecture](docs/ARCHITECTURE.md) | You want the system design: layers, data flow, verification model, decisions and trade-offs |
| [Backend architecture](docs/backend-architecture.md) | You are working inside `backend/`: module map, scoring model, data platform, background tasks |
| [API contract](docs/api-contract.md) | You are calling the API |
| [Setup](docs/setup.md) | You want the stack running from a fresh clone |
| [Demo runbook](docs/demo-runbook.md) | You are presenting INDRA on live data |
| [Questions & answers](docs/nodal-officer-qa.md) | You need the evidence-backed answer to a hard question |
| [Frontend handover](docs/frontend-handover.md) | You own the dashboard and need to know what the backend changed |
| [Bug register](docs/bug-register.md) | You want every known defect, its status and its fix |
| [AI/ML architecture](docs/ML_ARCHITECTURE.md) · [Alert engine](docs/ALERT_ENGINE_INTEGRATION.md) | You work on layer 4 or layer 8b |

---

## Contributing

- **Branches:** open a feature branch per unit of work, and merge to `main` through a pull request.
- **Commits:** small and focused, in [Conventional Commits](https://www.conventionalcommits.org)
  style scoped to the area (`fix(evidence): …`, `docs(contract): …`, `test(review): …`).
- **Tests:** add or update tests with every behaviour change. `make test`, and `make
  test-integration` for anything that touches the database or Kafka, must show no failures beyond
  the known ones recorded in the bug register.
- **Contracts:** a new or changed endpoint is documented in
  [`docs/api-contract.md`](docs/api-contract.md) in the same pull request. If the dashboard must
  change too, add a section to [`docs/frontend-handover.md`](docs/frontend-handover.md).
- **Defects:** record a bug in [`docs/bug-register.md`](docs/bug-register.md) when it is observed,
  before it is fixed.

---

## Team

Built by **Team Sixth Sense** for **Smart India Hackathon 2026**, problem statement **SIH26069:
National Weather Big Data Analytics Platform** (theme: Disaster Management).

| Area | Maintainer |
|---|---|
| Core platform: data sources, ingestion, processing, geo-analytics, event fusion, data platform, real-time API (layers 1–3, 5–8a) | Aditya ([@aditbytes](https://github.com/aditbytes)) |
| AI/ML (layer 4) | Pritam Singh |
| Alert engine (layer 8b) | Meenal Sinha |
| Command center (layer 9) | Saba Saeed |

## License

Copyright © 2026 Team Sixth Sense. **All rights reserved.**

This is proprietary software. No licence is granted to use, copy, modify, distribute or deploy any
part of it without the prior written permission of the copyright holders. See [`LICENSE`](LICENSE).
