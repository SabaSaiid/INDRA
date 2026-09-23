# INDRA — Demo Runbook

**What this is:** the exact sequence to bring INDRA up from nothing and walk someone through it,
with the number to expect beside every step and a one-line recovery for each thing that can go
wrong on the table.

**Last rehearsed from an empty volume: 21 Sep 2026; re-run from an empty database on 22 Sep
2026.** Every number below was read off those runs. Where the two days differ it is the live
rainfall, and both are shown.

Read [`nodal-officer-qa.md`](nodal-officer-qa.md) before presenting. This file is what to type;
that one is what to say.

---

## Before you start

| Check | Command | Expected |
|---|---|---|
| External SSD mounted | `ls /Volumes/"Aditya ssd"/Applications/Docker.app` | exists |
| Docker running | `docker ps` | no error |
| `DEMO_MODE` | `grep DEMO_MODE .env` | **`false`** |

> **`command not found: docker` means the SSD is unmounted, not that Docker is missing.** Every
> `/usr/local/bin/docker*` entry is a symlink into the drive. Mount it — do not reinstall.
> If instead you get `Cannot connect to the Docker daemon`, the drive is there and the daemon is
> not: `open -a "/Volumes/Aditya ssd/Applications/Docker.app"` and wait.

> **`DEMO_MODE=true` will ruin the demo.** With it on, an empty database answers `GET /api/events`
> with a fabricated `0.94 / AUTO_PUBLISHED / CRITICAL` event — a score this engine cannot produce.
> The opening seconds of a live run are exactly when the database is empty. Check it every time.

---

## Cold start

```bash
cd ~/CODING/sih/INDRA

docker compose down -v          # only for a true cold rehearsal — destroys all data
docker compose up -d --wait     # returns when Postgres and Redis are healthy and Redpanda is running
                                # (./start.sh infra up does the same)
```

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
# indra-postgres   Up (healthy)
# indra-redis      Up (healthy)
# indra-redpanda   Up             ← no healthcheck is defined for it; /healthz checks it instead
```

> **Healthy now means `indra_db` exists (BUG-028, fixed 22 Sep).** The Postgres healthcheck used a
> socket `pg_isready`, which went green on the entrypoint's temporary init server before the
> database was created. It now probes over TCP, which only the real server listens on. The
> migration below is still the proof — read its output.

```bash
cd backend && .venv/bin/alembic upgrade head && cd ..
# → 0010_report_submitted_by (head)
```

**Do not skip the output of that command.** A silently failed migration leaves a database with no
schema, and `/healthz` used to answer `healthy` against exactly that (BUG-027). It now checks the
schema too, but check the migration anyway.

```bash
./start.sh bg          # or: ./start.sh -b
```

Verify:

```bash
curl -s localhost:8000/healthz | jq .status
# → "healthy"
```

| `/healthz` says | Meaning | Do |
|---|---|---|
| `healthy` | all five checks up | continue |
| `degraded` (200) | Redis or Open-Meteo down, or reports have waited over 60 s for Kafka (`outbox_backlog`) | **continue** — none of these loses anything, and this is worth showing |
| `unhealthy` (503) | Postgres or Kafka down | stop and fix. Postgres down: reports are refused with 503. Kafka down: reports are kept in the outbox and processed when it is back, but nothing new reaches the map until then |

**Cold start to a ready API: under 5 minutes**, nearly all of it Docker pulling and the embedding
model loading. The model is warmed on a background thread, so `/healthz` answers immediately and
the first report pays nothing.

---

## Scene 1 — The platform is already watching

```bash
docker exec indra-postgres psql -U indra_user -d indra_db \
  -c "SELECT station_code, rainfall_mm, recorded_at FROM station_readings ORDER BY station_code;"
```

Six rows, one per city, written by the station poller within seconds of startup. Measured on
21 Sep: Kolkata **17.2 mm**, Guwahati 5.6, Chennai 2.4, Delhi 1.5, Mumbai 1.1, Patna 0.2 — real
differentiated 24-hour accumulations from Open-Meteo, not fixtures.

**What to say:** this is the one external feed that exists, and it is real and live. `anomaly_score`
is `NULL` on every row because nothing computes it — the column stays empty rather than claiming a
normal reading from a model that does not run.

---

## Scene 2 — Five citizen reports become one event

```bash
backend/.venv/bin/python scripts/run_patna_demo.py
```

The script posts five synthetic citizen reports to `POST /api/reports/submit`, waits for the
cluster to settle, then reads **every number back out of the API**.

**Expected** (21 Sep reproduced twice; 22 Sep once, from an empty database):

| | 21 Sep | 22 Sep |
|---|---|---|
| Reports stored | 5 / 5 | 5 / 5 |
| Events created | **1** | **1** |
| Severity | `MODERATE` | `MODERATE` |
| Review status | **`QUARANTINED`** | **`QUARANTINED`** |
| Quadrant | `Noise` | `Noise` |
| Confidence | **0.4984** | **0.5146** |
| Factor coverage | **0.80** | **0.80** |
| Boundary | Polygon, **39 vertices** | Polygon, **39 vertices** |
| Heat map | 2 H3 cells at res 8, 5 reports | the same |

Only the weather factor moved: **0.0080** on 21 Sep, **0.0600** on 22 Sep, when Patna was wetter.
Every other factor was identical, including after the clustering radius became a true
great-circle distance on 22 Sep.

Receipt:

| Factor | Weight | Score | Points | State |
|---|---|---|---|---|
| Weather Station Corroboration | 25% | 0.0080 | 0.0020 | computed |
| Report Density Analysis | 20% | 0.5483 | 0.1097 | computed |
| Spatial Coherence Score | 20% | 0.9850 | 0.1970 | computed |
| Computer Vision Analysis | 15% | — | 0.0 | **offline** |
| Source Reliability Index | 15% | 0.6000 | 0.0900 | computed |
| Anomaly Detection Signal | 5% | — | 0.0 | **offline** |

`0.3987 / 0.80 = 0.4984` (21 Sep); `0.4117 / 0.80 = 0.5146` (22 Sep). The arithmetic is printed
so anyone can check it, and the dashboard's receipt shows it too.

Severity: `max(depth_axis, count_axis)` → depth `MODERATE` (50 cm, read from the phrase
"knee deep"), count `MODERATE` (5 reports).

> **`QUARANTINED` is the correct answer, not a failure.** Say this before anyone asks. Five
> unverified citizen reports and 0.2 mm of rain is not a verified disaster. The receipt shows
> exactly which evidence produced that number, and the score rises with independent corroboration
> and with real rainfall. A system that called this a confirmed flood would be the broken one.

The weather factor scoring 0.008 is **Patna being dry today**, not a failure. If you want a wetter
story, the Kolkata reading above is 17.2 mm.

The script waits until **every report it sent has joined the event** (up to 45 s) before printing.
On a backend started seconds earlier, the last few reports wait for the embedding model to warm:
expect a line like `cluster size 2 → 5`. If fewer ever join, it says so instead of printing a
partial event as final.

---

## Scene 2b — One official dispatch, and the event reaches a human

On an **empty database** (on top of Scene 2 it merges into the same event, which is fine to show
but gives different numbers):

```bash
backend/.venv/bin/python scripts/run_patna_demo.py --official
```

The same five citizen reports, plus one report filed **as the commander** through
`POST /api/reports/official`: *"District control room confirms waterlogging at Kankarbagh, SDRF
team en route."* It is stored as `OFFICIAL_DISPATCH` with `submitted_by = commander`. From the
dashboard, the same thing is the **Report Incident** button with *"File as an official dispatch"*
ticked, which only a Commander or Admin persona sees.

**Measured 22 Sep, cold start:**

| | Value |
|---|---|
| Reports in the event | **6** (5 citizen + 1 official) |
| Review status | **`PENDING_HUMAN_REVIEW`** |
| Quadrant | `Confirmed Minor Event` |
| Confidence | **0.6065** (`0.4852 / 0.80`) |
| Source Reliability | **1.0000** (0.6000 with citizens only) |
| Report Density | 0.6159 (6 reports) |
| Boundary | Polygon, 40 vertices |

**What to say:** a citizen cannot claim to be official — the public route stores `CITIZEN_APP`
whatever the request says. A trusted report comes through a route that needs a commander's token
and records who filed it; open the event's **Reports** tab and it says *"filed by commander"*. One
trusted report did not publish anything: it moved the event across 0.60 into a human's queue.

Try it as the analyst persona: the checkbox is not offered, and the API answers `403`.

---

## Scene 3 — A commander takes the decision

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/token \
  -d 'username=commander&password=commander123' | jq -r .access_token)

curl -s -X PATCH localhost:8000/api/events/<EVENT_ID>/review \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"approve","reason":"Control room confirms waterlogging at Kankarbagh"}' | jq .review_status
# → "HUMAN_APPROVED"
```

An `EVENT_REVIEWED` message goes out on the WebSocket, and an audit row is chained.

**Try it without the token** — `401`. **With the analyst token** — `403`. That is the point of the
scene: the decision is gated, attributed and recorded.

```bash
curl -s localhost:8000/api/events/<EVENT_ID>/provenance \
  -H "Authorization: Bearer $TOKEN" | jq '.chain, [.reports[].id] | length'
# → {"valid": true, "checked": N, "broken_at_seq": null}
```

`confidence_score` is unchanged by the review. The machine's reading and the human's decision are
recorded separately, on purpose.

---

## Scene 4 — The geography

```bash
curl -s 'localhost:8000/api/geo/heatmap?resolution=8' | jq '.cells'
curl -s 'localhost:8000/api/geo/heatmap?resolution=7' | jq '[.cells[].report_count] | add'
```

Res 8 gives 2 cells summing to 5; res 7 gives 1 cell with 5. **Zooming out is aggregation, not
re-binning** — the coarser count is the exact sum of its children, nothing smoothed or spread.

`GET /api/events/{id}` returns `boundary_geojson`, a Polygon containing every contributing report.

---

## Scene 5 — Break it on purpose

The most convincing part of the demo, and it takes thirty seconds.

```bash
docker stop indra-redis
curl -s localhost:8000/healthz | jq .status      # → "degraded", still HTTP 200
backend/.venv/bin/python scripts/run_patna_demo.py   # still works
docker start indra-redis
```

**What to say:** Redis holds the weather cache and the broadcast-dedup set. Both fall back to
process memory, so losing it costs cross-restart memory and nothing else. A dependency that can
take the platform down is one we would have to apologise for.

Optional, if there is time:

```bash
docker stop indra-postgres
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/healthz   # → 503, in under 5 s
docker start indra-postgres                                        # recovers, no app restart
```

### The event bus goes down, and no report is lost

Until 23 Sep this was the one outage that lost data (BUG-060): a report accepted while Redpanda was
down was stored, answered 202, and never processed. Each report's message is now written to an
outbox in the same transaction as the report, and a relay publishes whatever is waiting.

```bash
docker stop indra-redpanda
curl -s -X POST localhost:8000/api/reports/submit -H 'Content-Type: application/json' \
  -d '{"latitude":25.5941,"longitude":85.1376,"text":"Water entering ground floor shops near Kankarbagh main road"}'
# → 202 … "queued": false, "will_retry": true, and a "docket"
curl -s localhost:8000/healthz | jq '.status, .checks.outbox_backlog'
# → "unhealthy" (Kafka is critical) and {"status": "up", "count": 1, "oldest_s": …}
docker start indra-redpanda
curl -s localhost:8000/healthz | jq '.checks.outbox_backlog.count'   # → 0 within a couple of seconds
curl -s localhost:8000/api/reports/track/<docket> | jq .status       # → "not_yet_an_event" or "part_of_event"
```

**Measured 23 Sep** — ten Patna reports sent with Redpanda stopped, on an empty database:

| | |
|---|---|
| Submits during the outage | 10 × 202, `queued: false, will_retry: true`. The first waited 2.06 s (the request's publish cap); after it the producer is taken out of service and the other nine answered in 4–66 ms |
| Waiting in the outbox | 10 rows |
| `/healthz` during | 503 `unhealthy`: `streaming_bus` down, `outbox_backlog` count 10 |
| After `docker start indra-redpanda` | all 10 published in **1.0 s**, all 10 processed in **4.8 s** |
| Result | **one `URBAN_FLOOD` event, 10 of 10 reports linked, 0 lost**; `/healthz` back to `healthy` |

**What to say:** Kafka is the one dependency that takes reports to the pipeline, and it is still
critical: while it is down nothing new reaches the map. But nothing is dropped either. The report and
the message that announces it are one database transaction, and a relay retries every two seconds, so
the backlog clears within seconds of the bus coming back.

`outbox.attempts` counts failed publishes. While the broker does not answer at all the relay only
probes it, so a clean outage leaves `attempts` at 0.

---

## Throughput, if asked

```bash
backend/.venv/bin/python scripts/burst_reports.py --count 100 --spread-km 3 --city patna
```

Measured: 100/100 accepted and stored, 215 reports/s, submit p50 4 ms / p95 5 ms, connection pool
Δ+1, RSS Δ+1.9 MB, audit chain still valid.

> **Do not present the burst as a confidence-raising demo.** Confidence *fell* to 0.4555 with 101
> reports, below the 5-report cluster. That is correct: 100 reports scattered over 3 km have a wide
> diameter, so spatial coherence drops and outweighs density saturating. A tight cluster is
> stronger evidence of one incident than a diffuse one. Present it as throughput and leak evidence.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: docker` | SSD unmounted | Mount the drive. Do not reinstall |
| `Cannot connect to the Docker daemon` | Daemon stopped | `open -a "/Volumes/Aditya ssd/Applications/Docker.app"` |
| `/healthz` 503 on `database` | Postgres not up, or no schema | `docker compose up -d`, then `alembic upgrade head` — and read its output |
| `/healthz` 503 on `streaming_bus` | Redpanda not up | `docker compose up -d`; submit still returns 202 `queued: false` |
| `/healthz` `degraded` | Redis or Open-Meteo down | **Nothing.** This is fine, and worth showing |
| Dashboard shows a `0.94` CRITICAL event | `DEMO_MODE=true` | Set it `false` and restart. This is fabricated data |
| The same report appears twice in the feed | Two backend processes on one broker | Kill one. One process only |
| First report seems to hang | Embedding model still loading | It is warmed at startup; wait for `✓ Embedding model warm` in the log |
| The demo prints `… N of M reports joined` | Reports still in the pipeline, or suppressed as duplicates | Re-run the read with `curl localhost:8000/api/events`; the script waited 45 s and said so rather than guessing |
| The map's badge counts incidents but no pins show | A late map `load` wiped the pins (BUG-043 race, fixed 22 Sep) | Should not recur; if it does, switch view once and report it |
| An event has no boundary polygon | Polygon computation failed, non-fatal | The event is still correct; say so |
| Confidence is lower than last rehearsal | Rainfall changed | Correct behaviour — it is live data |

---

## The three sentences to have ready

1. **"The score is 0.4984 out of a coverage of 0.80."** Never one without the other.
2. **"Quarantined is the right answer here."** Say it before it is asked.
3. **"That factor is offline, and the receipt says so."** For vision and anomaly, every time.
