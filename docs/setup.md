# INDRA — Setup

**What this is:** how to get the stack running from a fresh clone. Verified end to end on
21 Sep 2026; migration head, health gate and test counts re-checked 22 Sep.

If you only want to *run the demo*, this page plus [`demo-runbook.md`](demo-runbook.md) is
everything.

---

## Prerequisites

| | |
|---|---|
| Docker + Docker Compose | for PostGIS, Redis and Redpanda |
| Python 3.11+ | backend |
| Node.js | frontend only — skip it if you are working on the backend |

> **On Aditya's machine, Docker Desktop lives on an external SSD** and every `/usr/local/bin/docker*`
> entry is a symlink into it. If the drive is unmounted, those symlinks dangle and every command
> fails with `command not found: docker`, which looks exactly like Docker never being installed.
> **Mount the drive — do not reinstall.** With the drive mounted but the daemon stopped, the error
> is instead `Cannot connect to the Docker daemon`; start Docker.app and wait.

---

## 1. Environment

```bash
cd INDRA
cp .env.example .env
```

The defaults work for local development. The values worth knowing:

| Setting | Default | Note |
|---|---|---|
| `DATABASE_URL` | `…@localhost:5433/indra_db` | **Port 5433**, not 5432, so it cannot clash with a local Postgres |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Redpanda |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `DEMO_MODE` | **`false`** | Leave it false. See the warning below |
| `STATION_POLLER_ENABLED` | `true` | Polls Open-Meteo every 10 min into `station_readings` |
| `OPENWEATHER_API_KEY`, `IMD_API_KEY`, `TWITTER_BEARER_TOKEN` | empty | **Nothing reads them.** Those feeds do not exist; leave them blank |

> **`DEMO_MODE=true` makes the API serve data nothing computed.** An empty database answers
> `GET /api/events` with a fabricated `0.94 / AUTO_PUBLISHED / CRITICAL` event — a score the real
> engine cannot reach. It is off by default for that reason. Never demonstrate with it on.

The backend reads the **repo-root `.env`**. A `backend/.env`, if one exists, silently wins over it
— which has cost this project a debugging session before.

---

## 2. Infrastructure

```bash
docker compose up -d --wait        # or: ./start.sh infra up — both wait for "healthy"
docker ps --format '{{.Names}}\t{{.Status}}'
```

Expect `indra-postgres` and `indra-redis` `(healthy)` and `indra-redpanda` `Up` (it has no
healthcheck; `/healthz` checks it once the API is running).

> **Why `--wait` is enough now (BUG-028).** On a brand-new volume the Postgres entrypoint runs a
> temporary server on the Unix socket, creates `indra_db`, then restarts. A socket `pg_isready`
> went green on that temporary server, before the database existed. The healthcheck now probes
> over TCP, which only the real server listens on, so `healthy` means `indra_db` is there. Still
> read the migration output below.

---

## 3. Backend

```bash
cd backend
python3 -m venv .venv                     # if it does not exist
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head            # → 0010_report_submitted_by (head)
```

**Read the output of `alembic upgrade head`.** A silently failed migration leaves a database with
no schema, and that once produced a `/healthz` reporting `healthy` against it (BUG-027). The check
now covers the schema, but confirm the migration anyway.

Run it:

```bash
cd ..
./start.sh bg          # background; ./start.sh -b is the same thing
# or, directly:
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl -s localhost:8000/healthz | jq .status     # → "healthy"
open http://localhost:8000/docs                 # interactive API docs
```

| `/healthz` | HTTP | Meaning |
|---|---|---|
| `healthy` | 200 | all four dependencies up |
| `degraded` | 200 | Redis or Open-Meteo down — **fine**, neither is load-bearing |
| `unhealthy` | 503 | Postgres or Kafka down — a report would be lost |

First start loads the MiniLM embedding model (~13 s). It is warmed on a background thread, so the
API answers immediately; wait for `✓ Embedding model warm` before timing anything.

---

## 4. Tests

```bash
cd backend
.venv/bin/pytest -q                                        # 746 passed, 2 skipped
.venv/bin/pytest -q -m "not integration"                   # no Docker needed
.venv/bin/pytest -q -m "not integration and not network"   # fully offline
```

The suite runs against its own **`indra_test`** database and cannot touch your development data.
It creates it if missing.

---

## 5. Seeing it work

```bash
backend/.venv/bin/python scripts/run_patna_demo.py
```

Five synthetic citizen reports → one verified event, with every number read back out of the API.
Add `--official` to file one more report as the commander through the authenticated route and
watch source reliability go to 1.00. Expected output and the full walkthrough:
[`demo-runbook.md`](demo-runbook.md).

Load test, if you want one:

```bash
backend/.venv/bin/python scripts/burst_reports.py --count 100 --spread-km 3 --city patna
```

> `scripts/seed_national_data.py` writes **synthetic** rows and refuses to run without
> `--synthetic`, marking every receipt it creates. It is not a data import.

---

## 6. Frontend

Owned by the rest of the team. (On 22 Sep, on request, the backend side fixed a list of defects
in it; they are written up in [`frontend-handover.md`](frontend-handover.md).)

```bash
cd frontend && npm install && npm run dev      # http://localhost:3000

# production build and the browser tests (backend on :8000 first)
npm run build                                  # type check + lint + build
npx playwright test                            # 26 tests, serves the build on :3000
```

The backend's CORS list defaults to `http://localhost:3000` and `http://127.0.0.1:3000`. If you
serve the dashboard from anywhere else, add it to `CORS_ORIGINS` in `.env` — it is an explicit
list, not a wildcard.

---

## Operational rules

**Run one backend process.** WebSocket fan-out is an in-process list, the station poller has no
leader election, and two consumers against one broker will re-deliver reports. This is a deliberate
limit of a demo stack, not a bug to work around.

**A shared remote server exists** — the full stack also runs on a dedicated cloud box in
`ap-south-1`, with the project at `/opt/indra`. Its address, instance identifiers and SSH key are
**deliberately not written here**: this repository is shared, and infrastructure identifiers do not
belong in it. Ask Aditya for access.

---

## When something is wrong

Check [`bug-register.md`](bug-register.md) first — the failure you are looking at may already be
recorded, with the reason. The recovery table in [`demo-runbook.md`](demo-runbook.md) covers
everything that has actually gone wrong on this stack.
