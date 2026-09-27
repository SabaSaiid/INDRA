# INDRA — Setup

**What this is:** how to get the stack running from a fresh clone. Verified end to end on
21 Sep 2026; migration head and health gate re-checked 22 Sep. Updated 25 Sep: operator
accounts and their passwords, the disposable E2E backend, and no demo mode.
The AI/ML layer's frozen local adapter arrived with PR #39 (26 Sep).

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
| `SECRET_KEY` | a value committed in `.env.example` | Signs every login token. **Replace it on any server someone else can reach** (`openssl rand -hex 32`): with the committed value, anyone who has the repository can mint a valid token without a password. Since 27 Sep, `ENVIRONMENT=production` refuses the committed value, or any key under 32 characters, and the backend will not start (BUG-120) |
| `SACHET_POLLER_ENABLED` | `true` | Polls NDMA's SACHET CAP feed every 5 min into `agency_alerts` |
| `STATION_POLLER_ENABLED` | `true` | Polls Open-Meteo every 10 min into `station_readings` |
| `METAR_POLLER_ENABLED`, `MASTODON_POLLER_ENABLED`, `NEWS_POLLER_ENABLED` | `false` | Phase 2's feeds: airport weather, #IMD posts, news headlines. No keys needed; turn them on to collect |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | placeholders | The object store's keys (Phase 2). Generate real ones — see below. Placeholders mean "not configured": the lake is off and `/healthz` says `degraded`, nothing else changes |
| `OPENWEATHER_API_KEY`, `IMD_API_KEY`, `TWITTER_BEARER_TOKEN` | empty | **Nothing reads them.** Those feeds do not exist; leave them blank |

**The object store's keys, before the first `docker compose up`.** SeaweedFS reads its keys from
`infra/seaweedfs/s3.json`, which is gitignored and generated from `.env`:

```bash
openssl rand -hex 12     # paste as S3_ACCESS_KEY in .env
openssl rand -hex 32     # paste as S3_SECRET_KEY in .env
python3 scripts/make_s3_config.py
```

`openssl rand -hex N` prints N random bytes as hexadecimal, a safe secret. If you start the
containers before running the script, Docker creates an empty *directory* at `infra/seaweedfs/s3.json`
and the object store will not start; stop it, `rmdir infra/seaweedfs/s3.json`, and run the script.

> **There is no demo mode.** A read with no rows returns the real empty result (`[]`, zero
> counts, empty cells), an unknown id is a `404`, and a database error is a `503`
> `{"detail":"Database unavailable"}` — never a made-up payload. An empty database shows an empty
> event list until real reports cluster; the pollers fill the warnings, rainfall and feed panels
> within minutes. `DEMO_MODE` was removed on 25 Sep, and a leftover `DEMO_MODE` line in an old
> `.env` is ignored.

The backend reads the **repo-root `.env`**. A `backend/.env`, if one exists, silently wins over it
— which has cost this project a debugging session before.

---

## 2. Infrastructure

```bash
docker compose up -d --wait        # or: ./start.sh infra up — both wait for "healthy"
docker ps --format '{{.Names}}\t{{.Status}}'
```

Expect `indra-postgres` and `indra-redis` `(healthy)`, and `indra-redpanda` and `indra-objectstore`
`Up` (they have no healthcheck; `/healthz` checks both once the API is running). The object store's
S3 API listens on `127.0.0.1:8333` only.

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
.venv/bin/alembic upgrade head            # → 0019_operator_password_hash (head)
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
| `healthy` | 200 | critical services and optional checks up |
| `degraded` | 200 | Redis, Open-Meteo, object store, or delayed outbox — reports remain stored |
| `unhealthy` | 503 | Postgres or Kafka down; Kafka-bound reports wait in the transactional outbox |

First start authorizes the frozen local duplicate artifact on a background thread. No MiniLM,
remote checkpoint, or network-based ML warm-up is performed. Kafka's process producer and outbox
relay also start during lifespan; a broker outage does not discard a stored report.

### Operator accounts

**No password is in this repository.** The four accounts — `admin`, `commander`, `analyst`,
`citizen` — are rows in `user_profiles`, and each signs in against a bcrypt hash in its
`password_hash` column. A `NULL` hash means the account cannot sign in, and every fresh database
starts that way. Set the passwords for this deployment, from the repo root:

```bash
backend/.venv/bin/python scripts/set_operator_password.py commander         # prompts twice
backend/.venv/bin/python scripts/set_operator_password.py --all --generate  # a new one each, printed once
backend/.venv/bin/python scripts/set_operator_password.py --all --from-env INDRA_OPERATOR_PASSWORD
```

Usage: `set_operator_password.py [USERNAME ...] [--all] [--from-env VAR | --generate]`. It writes
to `DATABASE_URL` from the environment, else the backend's own settings (`.env`), and prints the
target host, port and database — never the password — before it changes anything. It refuses a
username with no row in `user_profiles` (exit status 2; accounts are not created here) and any
password shorter than 10 characters. With neither `--from-env` nor `--generate` it prompts for each
password twice without echoing it; `--generate` prints each generated password once, so store them
then; `--from-env VAR` gives every named account the password held in that environment variable.

**Deploying this version to a server that already has data:** run `alembic upgrade head`, then set
the passwords. Until you do, every login is a `401` and nobody can sign in; read-only pages still
work.

Operators sign in from the dashboard's top bar. Behind it is `POST /api/auth/token` (form-encoded
`username` and `password`); a wrong password, an unknown username and an account with no password
all get the same `401 {"detail":"Incorrect username or password"}`. To check one account:

```bash
read -rs PW          # type the commander's password; -s means nothing is shown as you type
curl -s -X POST localhost:8000/api/auth/token --data-urlencode username=commander \
     --data-urlencode "password=$PW" | jq -c '{username, role, expires_in}'
# → {"username":"commander","role":"COMMANDER","expires_in":28800}
unset PW             # forget it again
```

`expires_in` is `JWT_EXPIRY_HOURS` (default 8) in seconds.

---

## 4. Tests

```bash
cd backend
.venv/bin/pytest -q                                        # everything; needs docker compose up
.venv/bin/pytest -q -m "not integration"                   # no Docker needed
.venv/bin/pytest -q -m "not integration and not network"   # fully offline
```

The suite runs against its own **`indra_test`** database and cannot touch your development data:
it refuses to run against `indra_db`, creates `indra_test` if missing, and gives the accounts there
passwords of its own that exist nowhere else.
Without Docker (on Windows, say), a native PostgreSQL/PostGIS on this machine works the same
way, as long as the database is `indra_test` or `indra_test_<suffix>`: the guard refuses any
other name, and any host but this one unless `INDRA_ALLOW_REMOTE_TEST_DB=1`.

---

## 5. Seeing it work

Nothing in this repository generates reports. Within minutes of startup the pollers fill the
dashboard with real data:

```bash
curl -s localhost:8000/api/meta/sources | jq -r '.feeds[] | "\(.feed)\t\(.status)\t\(.rows_24h)"'
```

That prints one line per feed — its name, its state (`ok`, `stale`, `failing` or `disabled`) and
the rows it stored in the last 24 h. `sachet` and `open_meteo` are on by default. Set
`METAR_POLLER_ENABLED`, `MASTODON_POLLER_ENABLED` and `NEWS_POLLER_ENABLED` to `true` in `.env` for
airport observations, #IMD posts and news headlines. To watch the pipeline build an event, two
people file what they actually see, in their own words, within 5 km of each other, through the
dashboard's **Report Incident** form: one report never makes an event, and a copy of the same
text from close by is suppressed as a duplicate. The walkthrough is in
[`demo-runbook.md`](demo-runbook.md).

To exercise the pipeline with test input, use the test suites, which write only to `indra_test` and
`indra_e2e` (sections 4 and 6). **Never post test sentences to the API on `:8000`**: its database
is the real one, and a test report there is fabricated data in the audit trail.

---

## 6. Frontend

Owned by the rest of the team. (On 22 and 25 Sep, on request, the backend side fixed defects in
it; they are written up in [`frontend-handover.md`](frontend-handover.md).)

```bash
cd frontend && npm install && npm run dev      # http://localhost:3000
npm run build                                  # production build: type check + lint + build
```

**The browser tests never touch the development stack.** They run against a disposable backend,
from the repo root, in two terminals:

```bash
make e2e-backend     # terminal 1: backend on 127.0.0.1:8100, database indra_e2e
make e2e             # terminal 2: builds the dashboard into .next-e2e, serves it on :3100, runs Playwright
make e2e-reset       # afterwards, if you want indra_e2e empty again
```

`make e2e-backend` (`./start.sh e2e-backend`) creates `indra_e2e` with PostGIS if it is missing,
migrates it to head, gives every account there the password in `E2E_OPERATOR_PASSWORD` (start.sh
has a default that only ever exists in that database), and starts the API with `ENVIRONMENT=e2e`
on its own Kafka topics (`indra.e2e.*`), consumer group, Redis database (15) and media bucket,
with every poller and the lake archive off. In that mode the backend refuses to start unless its
database name ends in `_e2e`, its topics start with `indra.e2e.`, its consumer group with
`indra-e2e-` and the lake archive is off, and it answers `GET /api/e2e/identity`; in every other
mode that route is a `404`.

Playwright refuses to run unless `E2E_API_URL` is set to a loopback address that is not port
8000, `/api/e2e/identity` reports `environment: "e2e"`, a database ending in `_e2e` equal to
`E2E_EXPECT_DB` (default `indra_e2e`), an `indra.e2e.*` topic and an `indra-e2e-*` consumer group,
and `/healthz` reports the database up. It builds the
dashboard with `NEXT_PUBLIC_API_BASE_URL` pointed at that backend, into `.next-e2e` so the
development build is left alone. **The specs cannot write into `indra_db`.** `make e2e-reset`
(`./start.sh e2e-reset`) drops and recreates `indra_e2e`, and refuses any name that does not end
in `_e2e`.

The backend's CORS list defaults to `http://localhost:3000` and `http://127.0.0.1:3000`. If you
serve the dashboard from anywhere else, add it to `CORS_ORIGINS` in `.env` — it is an explicit
list, not a wildcard.

---

## Operational rules

**Run one backend process.** WebSocket fan-out is an in-process list, the station poller has no
leader election, and two consumers against one broker will re-deliver reports. This is a deliberate
limit of this single-server deployment, not a bug to work around. The E2E backend on `:8100` is
not a second one: it has its own database, topics, consumer group and Redis database, and its
pollers are off.

**A shared remote server exists** — the full stack also runs on a dedicated cloud box in
`ap-south-1`, with the project at `/opt/indra`. Its address, instance identifiers and SSH key are
**deliberately not written here**: this repository is shared, and infrastructure identifiers do not
belong in it. Ask Aditya for access.

---

## When something is wrong

Check [`bug-register.md`](bug-register.md) first — the failure you are looking at may already be
recorded, with the reason. The recovery table in [`demo-runbook.md`](demo-runbook.md) covers
everything that has actually gone wrong on this stack.
