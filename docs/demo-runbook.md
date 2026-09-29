# INDRA — Demo Runbook

The sequence to bring INDRA up and walk an audience through it **on live data only**: the feeds
the platform is already reading, and real reports filed in front of the audience by people who can
see what they describe. Nothing in this runbook generates, replays or seeds data into the platform.
Each thing that can go wrong has a one-line recovery.

| | |
|---|---|
| **Applies to** | `main` after Phase 4 (PR #47) |
| **Last reviewed** | 28 Sep 2026 |
| **Rehearsal status** | Scene 5b was run live on the server on 27 Sep. The full sequence has not been rehearsed end to end since the 25 Sep rewrite, so rehearse it before presenting |

Numbers from 20–24 Sep are marked as past measurements, taken with test reports that are no longer
in any database. Read [`nodal-officer-qa.md`](nodal-officer-qa.md) before presenting: this file is
what to type, and that one is what to say.

---

## Before you start

| Check | Command | Expected |
|---|---|---|
| External SSD mounted | `ls /Volumes/"Aditya ssd"/Applications/Docker.app` | exists |
| Docker running | `docker ps` | no error |
| Feeds switched on | `grep -E '^(STATION\|SACHET\|METAR\|MASTODON\|NEWS)_POLLER_ENABLED' .env` | all five `true`. METAR, Mastodon and News default to `false`: turn them on and restart **at least an hour before**, so there is something to show |
| Operators can sign in | **Sign in** on the dashboard as `commander` | the topbar's account menu shows `commander` and its role. "Incorrect username or password" on a known account means its password was never set on this database (see Cold start) |

> **`command not found: docker` means the SSD is unmounted, not that Docker is missing.** Every
> `/usr/local/bin/docker*` entry is a symlink into the drive. Mount it — do not reinstall.
> If instead you get `Cannot connect to the Docker daemon`, the drive is there and the daemon is
> not: `open -a "/Volumes/Aditya ssd/Applications/Docker.app"` and wait.

> **There is no demo mode and no seed script.** Every read answers what the database holds: no
> rows is an empty list or zero counts, an unknown id is a 404, a database error is a 503. An
> empty database therefore shows an empty event list until real reports cluster. That is the
> correct opening; the live feeds are what fill the screen. A `DEMO_MODE` line left in an old
> `.env` is ignored.

---

## Cold start

```bash
cd ~/CODING/sih/INDRA

docker compose down -v          # only on a rehearsal machine: destroys every collected warning, reading, post and report
docker compose up -d --wait     # returns when Postgres and Redis are healthy and Redpanda is running
                                # (./start.sh infra up does the same)
```

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
# indra-postgres      Up (healthy)
# indra-redis         Up (healthy)
# indra-redpanda      Up             ← no healthcheck is defined for it; /healthz checks it instead
# indra-objectstore   Up             ← the S3 store; /healthz checks it too
```

> **Healthy now means `indra_db` exists (BUG-028, fixed 22 Sep).** The Postgres healthcheck used a
> socket `pg_isready`, which went green on the entrypoint's temporary init server before the
> database was created. It now probes over TCP, which only the real server listens on. The
> migration below is still the proof — read its output.

```bash
cd backend && .venv/bin/alembic upgrade head && cd ..
# → 0023_report_withdrawal (head)
```

**Do not skip the output of that command.** A silently failed migration leaves a database with no
schema, and `/healthz` used to answer `healthy` against exactly that (BUG-027). It now checks the
schema too, but check the migration anyway.

**Then set the operator passwords, or nobody can sign in.** Accounts live in `user_profiles`, and
an account with no password hash cannot sign in; a fresh database, or one just migrated to 0019,
has none. No password is in the code or in this file.

```bash
backend/.venv/bin/python scripts/set_operator_password.py commander analyst
# prints the host, port and database it is about to change, then asks for each password twice
```

It refuses a username that is not in `user_profiles` (exit 2) and a password shorter than 10
characters. `--all` sets every account; `--generate` makes a password for each and prints it once;
`--from-env VAR` reads one password from an environment variable. After deploying to a server, the
order is the same: `alembic upgrade head`, then this script.

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
| `healthy` | all six checks up | continue |
| `degraded` (200) | Redis, Open-Meteo or the object store down, or reports have waited over 60 s for Kafka (`outbox_backlog`) | **continue** — none of these loses anything, and this is worth showing |
| `unhealthy` (503) | Postgres or Kafka down | stop and fix. Postgres down: reports are refused with 503. Kafka down: reports are kept in the outbox and processed when it is back, but nothing new reaches the map until then |

**Cold start to a ready API: under 5 minutes**, nearly all of it Docker pulling and the embedding
model loading. The model is warmed on a background thread, so `/healthz` answers immediately and
the first report pays nothing.

---

## Scene 1 — The platform is already watching: five live feeds

```bash
curl -s localhost:8000/api/meta/sources | jq -r '.feeds[] | "\(.feed)\t\(.status)\t\(.rows_24h)"'
curl -s 'localhost:8000/api/alerts/agency?limit=5' | jq '.[] | {sender, event, area_desc, severity}'
curl -s 'localhost:8000/api/stations/latest?feed=open_meteo' | jq '.stations[] | {station_name, rainfall_mm, recorded_at}'
curl -s 'localhost:8000/api/stations/latest?feed=metar' | jq '.count'
curl -s 'localhost:8000/api/feed/recent?limit=10' | jq '.[] | {kind, sourceLabel, message, time}'
```

`/api/meta/sources` lists each feed with its state (`ok`, `stale`, `failing` or `disabled`) from
the poller's own heartbeat, and how many rows it stored in the last 24 hours. On the dashboard:
**Early Warnings** (`/alerts`) and the warnings layer of the **Live Tactical Map** for SACHET; the
live feed on the home page, where warnings, collected posts and headlines, reports and events
scroll past on one clock; **Telemetry Analytics** (`/analytics`) for the Open-Meteo rainfall
points; and **Geospatial Feeds** (`/datasets`) for each feed's state and row counts, METAR
included. Read the numbers off the screen on the day; do not quote rehearsal values. For example,
on 21 Sep the six Open-Meteo points read Kolkata **17.2 mm**, Guwahati 5.6, Chennai 2.4, Delhi 1.5,
Mumbai 1.1, Patna 0.2 — real differentiated 24-hour accumulations, not fixtures.

**What to say:** everything on this screen was published by someone else in the last hours: IMD,
CWC and state SDMAs through NDMA's SACHET, Open-Meteo, airport METARs, public posts and news
headlines. Nothing here was typed for today. `anomaly_score` is `NULL` on every `station_readings`
row because nothing computes it — the column stays empty rather than claiming a normal reading
from a model that does not run.

---

## Scene 2 — A real report, filed in front of them

On the dashboard: **Report Incident** → the location (the locate button fills it from the device's
GPS, which browsers allow only over HTTPS or on `localhost`; otherwise type the coordinates) →
what you can actually see, in your own words, at least 10 characters → **Submit Report**. The form
confirms it, and the report is in the live feed within seconds. The form does not print the
docket; the API returns one, and curl shows it.

The same with curl:

```bash
curl -s -X POST localhost:8000/api/reports/submit -H 'Content-Type: application/json' \
  -d '{"latitude": <where you are>, "longitude": <where you are>, "text": "<what you can see>"}'
# → 202, "status": "accepted", a "docket", "queued": true
curl -s localhost:8000/api/reports/track/<docket> | jq .status
# → "received", then "not_yet_an_event" once the pipeline has processed it, alone
```

> **File only what is actually happening where the reporter is, now.** This is the production
> database: a report typed for effect is fabricated data, and it stays in the audit trail. The
> best reporter is a nodal officer or a teammate who is somewhere something is happening, on their
> own phone.

**What to say:** one report never makes an event. DBSCAN needs two within 5 km, so a lone report
waits as `not_yet_an_event` until someone else corroborates it.

---

## Scene 3 — A second witness, and one event

A second person, within 5 km of the first, files what *they* see, in their own words. The dashboard
receives a `VERIFIED_EVENT`: one event, a boundary polygon and a receipt. Both dockets now read
`part_of_event`.

A near-verbatim copy of the first text is suppressed as a duplicate (cosine ≥ 0.88, within 1 km and
15 minutes; its docket reads `duplicate`) and never counts as corroboration. Two reports from one
person are not two witnesses, but the dashboard's form sends no reporter id, so the platform would
count them as two. That is exactly why it must never be staged.

**Expect** a score of about 0.4–0.5 at coverage 0.80 on a dry day, and `QUARANTINED` — or
`PENDING_HUMAN_REVIEW` if the reports describe a High or Critical situation, or the day's rain
lifts the score past 0.60. Read the number off the receipt; do not promise one in advance.

Receipt, the factors and their states:

| Factor | Weight | State | Reads |
|---|---|---|---|
| Weather Station Corroboration | 25% | computed | the 24 h rainfall near the event, on IMD's categories |
| Report Density Analysis | 20% | computed | independent, non-duplicate reports |
| Spatial Coherence Score | 20% | computed | how tight the cluster is |
| Computer Vision Analysis | 15% | **offline** | out of scope since 20 Sep |
| Source Reliability Index | 15% | computed | the best source prior in the cluster |
| Anomaly Detection Signal | 5% | **offline** | out of scope since 20 Sep |

`total_weighted / factor_coverage` is printed so anyone can check it, and the dashboard's receipt
shows it too.

Severity: `max(content_axis, count_axis, impact_floor)` — the content axis read from the words by
the hazard's own measure (for a flood, depth: "knee deep" is 50 cm, `MODERATE`), the count axis from
the number of reports (≥ 5 `MODERATE`, ≥ 10 `HIGH`), and impact words such as "stranded" or "died"
setting a floor. The receipt names the winning axis and the phrase it read.

> **`QUARANTINED` is the correct answer, not a failure.** Say this before anyone asks. A few
> unverified reports and a dry day is not a verified disaster. The receipt shows exactly which
> evidence produced that number, and the score rises with independent corroboration and with real
> rainfall. A system that called this a confirmed flood would be the broken one.

For reference only: between 20 and 24 Sep, test clusters of five scripted Patna reports scored
0.4984–0.6198 at coverage 0.80 (`0.3987 / 0.80 = 0.4984` on 20 Sep), depending only on the day's
rainfall; after 22.1 mm of rain on 24 Sep the same five crossed 0.60 into review. The script, the
reports and the event were deleted on 25 Sep.

### If no event forms

That is a correct outcome, and it is the corroboration rule working: one person's report stays
`not_yet_an_event`, and nobody on stage adds a second. Say so, and show the report waiting in the
live feed (or its docket, if it was filed with curl). Then show any
event the platform has already formed from real reports, posts or headlines (the Events page, or
`curl -s localhost:8000/api/events | jq length`), and carry on with the scenes that need no new
event: the permission gate (3b), the geography of whatever has been reported (5), and breaking it
on purpose (6).

---

## Scene 3b — Who may file an official dispatch (nothing is written)

Show the gate, not a dispatch. Signed in as `analyst` on the dashboard, the Report Incident form
does not offer *"File as an official dispatch"*; signed in as `commander`, it does. Do not tick it
on stage: a dispatch is stored as `OFFICIAL_DISPATCH` with the commander's name, and an invented
one would be a fake official report in the production record. File a real dispatch only when a
real control room reports a real incident.

With curl, the API refuses before anything is stored:

```bash
read -rs INDRA_PW      # type the analyst's password; it is not echoed or saved
ANALYST_TOKEN=$(curl -s -X POST localhost:8000/api/auth/token \
  --data-urlencode 'username=analyst' --data-urlencode "password=$INDRA_PW" | jq -r .access_token)
unset INDRA_PW

curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/api/reports/official \
  -H 'Content-Type: application/json' \
  -d '{"latitude":25.6,"longitude":85.1,"text":"authorisation check, refused and not stored"}'
# → 401: no token
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/api/reports/official \
  -H "Authorization: Bearer $ANALYST_TOKEN" -H 'Content-Type: application/json' \
  -d '{"latitude":25.6,"longitude":85.1,"text":"authorisation check, refused and not stored"}'
# → 403: an analyst may not file one
```

**What to say:** a citizen cannot claim to be official — the public route stores `CITIZEN_APP`
whatever the request says. A trusted report comes through a route that needs a commander's token
and records who filed it; the event's **Reports** tab says *"filed by"* and the name. One trusted
report does not publish anything: it lifts source reliability to 1.00 and can move an event across
0.60 into a human's queue. Measured 22 Sep on a test cluster: one dispatch moved it 0.5146 →
0.6065 and into review.

---

## Scene 4 — A commander takes the decision

On the dashboard: signed in as `commander`, open the event, **Approve** or **Reject**, with the
true reason — "Two independent on-site reports" if that is what there is, or reject with "Not
corroborated". It goes into the audit chain and cannot be edited. The same with curl:

```bash
read -rs INDRA_PW      # type the commander's password; it is not echoed or saved
TOKEN=$(curl -s -X POST localhost:8000/api/auth/token \
  --data-urlencode 'username=commander' --data-urlencode "password=$INDRA_PW" | jq -r .access_token)
unset INDRA_PW

curl -s -X PATCH localhost:8000/api/events/<EVENT_ID>/review \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"approve","reason":"<the true reason>"}' | jq .review_status
# → "HUMAN_APPROVED"
```

An `EVENT_REVIEWED` message goes out on the WebSocket, and an audit row is chained.

**Try it without the token** — `401`. **With the analyst token** — `403`. That is the point of the
scene: the decision is gated, attributed and recorded.

```bash
curl -s localhost:8000/api/events/<EVENT_ID>/provenance \
  -H "Authorization: Bearer $TOKEN" | jq '.chain, (.reports | length)'
# → {"valid": true, "checked": N, "broken_at_seq": null}, then the number of reports
```

`confidence_score` is unchanged by the review. The machine's reading and the human's decision are
recorded separately, on purpose.

---

## Scene 5 — The geography

```bash
curl -s 'localhost:8000/api/geo/heatmap?resolution=8' | jq '[.cells[].report_count] | add'
curl -s 'localhost:8000/api/geo/heatmap?resolution=7' | jq '[.cells[].report_count] | add'
```

The two totals are equal. **Zooming out is aggregation, not re-binning** — the coarser count is the
exact sum of its children, nothing smoothed or spread.

`GET /api/events/{id}` returns `boundary_geojson`, a Polygon containing every contributing report.

---

## Scene 5b — A fabricated heatwave caught by a thermometer, and a recycled photo (Phases 4 and 5)

*Run live on the server 27 Sep, 23:32 IST: case A was Uttarkashi under an Extreme Uttarakhand SDMA
rain warning with 54.6 mm fallen, **0.712 CORROBORATED**; case B was five "47 degree" reports 5 km
from Dehradun airport, which measured 20.0 °C, **0.4369 CONTRADICTED**; exit code 0. That run's
inputs are committed as `data/demo/verification_cases.json` for the offline fallback. Rehearse it
live again on the day: the places change with the weather.*

```bash
backend/.venv/bin/python scripts/run_verification_demo.py --record data/demo/verification_cases.json
# → Case A CORROBORATED, Case B CONTRADICTED, side by side; exit code 0
```

It chooses both places from **today's** data: A where an IMD warning is in force and rain has
fallen, or where an airport reports rain, a thunderstorm or fog; B where a plains airport's maximum
over the last day was under 35 °C. It scores five labelled reports at each through the pipeline's
own scoring, and **writes nothing to the database**. Say so: the reports are synthetic and labelled,
the stations, warnings and readings are real.

Point at case B's contradiction line: the station, its distance and the temperature it measured.
Then at case A's official-warning line: which office issued it, how severe, until when.

If there is no genuine case today (no warning, no rain anywhere), the script says so and exits 1;
it never invents one. Offline, replay the recording (it prints the time it was recorded; say so):

```bash
backend/.venv/bin/python scripts/run_verification_demo.py --frozen data/demo/verification_cases.json
```

**Case C, a recycled 2023 flood photo (Phase 5).** The same command prints a third case: a citizen
flood report whose photo is a re-save of an image first seen on Mastodon three days earlier, with
the camera date 14 Aug 2023. Both pictures are drawn by the script and labelled synthetic; the
extraction and the rules are the media worker's own. Live on the server 28 Sep, 19:54 IST, the
closing lines read:

```
A  genuine urban flood, Muzaffarpur, Bihar  → CORROBORATED  (official 0.85, weather 0.00; confidence 0.537)
B  fabricated heatwave, Ranchi, Jharkhand   → CONTRADICTED  (VERC max 24.0 °C)
C  recycled 2023 flood photo                → media flagged (first seen 25 Sep; taken 14 Aug 2023)
```

Live again on the team database, 29 Sep, 18:30 IST (exit 0):

```
A  genuine urban flood, Saran, Bihar                → CORROBORATED  (official 0.85, weather 0.00; confidence 0.537)
B  fabricated heatwave, Bengaluru Urban, Karnataka  → CONTRADICTED  (VOBL max 27.0 °C)
C  recycled 2023 flood photo                        → media flagged (first seen 26 Sep; taken 14 Aug 2023)
```

Until that day B's line could name a hotter airport nearby instead of the one that decided the case
(BUG-131, fixed): check that the station in B's line is the one in its contradiction line.

Point at C's two reasons, then at "the report is kept and shown: flagged, never rejected". Its
credibility falls 0.6 → 0.072, so it counts 0.12 of a witness. If asked "does it look at the
picture?": no, it checks reuse and metadata only; `vision_analysis` is offline by design. For a
real example, Q&A "What if the photo is old?" has the two re-posted images found in real posts.

---

## Scene 6 — Break it on purpose

The most convincing part of the demo, and it takes thirty seconds.

```bash
docker stop indra-redis
curl -s localhost:8000/healthz | jq .status                            # → "degraded", still HTTP 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/events     # → 200: reads still work
curl -s localhost:8000/api/meta/sources | jq -r '.feeds[] | "\(.feed) \(.status)"'   # the pollers carry on
docker start indra-redis
```

If a second real report is on its way for Scene 3, stopping Redis just before it arrives shows it
is still scored.

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

This drill needs a report submitted while the bus is down, so it runs against the **isolated E2E
backend**, never the live one: a test sentence must not land in `indra_db`. In another terminal,
`make e2e-backend` starts it on port 8100, on the `indra_e2e` database, the `indra.e2e.*` topics and
Redis db 15, with every poller off. Stopping Redpanda stops it for both backends; that is the point.

```bash
docker stop indra-redpanda
curl -s -X POST localhost:8100/api/reports/submit -H 'Content-Type: application/json' \
  -d '{"latitude":25.5941,"longitude":85.1376,"text":"Outbox drill: test report, not an observation"}'
# → 202 … "queued": false, "will_retry": true, and a "docket"
curl -s localhost:8100/healthz | jq '.status, .checks.outbox_backlog'
# → "unhealthy" (Kafka is critical) and {"status": "up", "count": 1, "oldest_s": …}
docker start indra-redpanda
curl -s localhost:8100/healthz | jq '.checks.outbox_backlog.count'   # → 0 within a couple of seconds
curl -s localhost:8100/api/reports/track/<docket> | jq .status       # → "not_yet_an_event" or "part_of_event"
```

`make e2e-reset` empties `indra_e2e` again afterwards. It is the same backend `make e2e` runs the
browser tests against, and Playwright refuses any other: a backend on port 8000, off loopback, or
whose `/api/e2e/identity` does not name an `_e2e` database. In front of an audience, the
alternative is to stop Redpanda just before a real report is filed through the form.

**Measured 23 Sep** — ten test reports sent with Redpanda stopped, on an empty database (those
reports have since been deleted):

| | |
|---|---|
| Submits during the outage | 10 × 202, `queued: false, will_retry: true`. The first waited 2.06 s (the request's publish cap); after it the producer is taken out of service and the other nine answered in 4–66 ms |
| Waiting in the outbox | 10 rows |
| `/healthz` during | 503 `unhealthy`: `streaming_bus` down, `outbox_backlog` count 10 |
| After `docker start indra-redpanda` | all 10 published in **1.0 s**, all 10 processed in **4.8 s** |
| Result | **one `URBAN_FLOOD` event, 10 of 10 reports linked, 0 lost**; `/healthz` back to `healthy` |

**Re-run 29 Sep on the team server**, on an E2E copy of the team database (3,922 reports), with the
broker, Redis **and** the object store all pointed at dead ports, and the live stack untouched:

| | |
|---|---|
| `/healthz` during | 503 `unhealthy`: `streaming_bus`, `redis` and `object_store` down, each with its reason |
| Submits during the outage | 4 flood reports 202, `queued: false, will_retry: true`, in 0.4 s; tracked as `received` |
| A photo upload | 503 `media_store_unavailable`; the report itself unaffected |
| Rate limit with Redis down | still 10 per device: the 11th 429 (the per-process window) |
| After the services came back | 14 waiting rows published within seconds; the 4 flood reports became **one event, 4 of 4 linked, 0 lost**; `healthy`, backlog 0 |

**What to say:** Kafka is the one dependency that takes reports to the pipeline, and it is still
critical: while it is down nothing new reaches the map. But nothing is dropped either. The report and
the message that announces it are one database transaction, and a relay retries every two seconds, so
the backlog clears within seconds of the bus coming back.

`outbox.attempts` counts failed publishes. While the broker does not answer at all the relay only
probes it, so a clean outage leaves `attempts` at 0.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: docker` | SSD unmounted | Mount the drive. Do not reinstall |
| `Cannot connect to the Docker daemon` | Daemon stopped | `open -a "/Volumes/Aditya ssd/Applications/Docker.app"` |
| `/healthz` 503 on `database` | Postgres not up, or no schema | `docker compose up -d`, then `alembic upgrade head` — and read its output |
| `/healthz` 503 on `streaming_bus` | Redpanda not up | `docker compose up -d`; submit still returns 202 `queued: false` |
| `/healthz` `degraded` | Redis, Open-Meteo or the object store down | **Nothing.** This is fine, and worth showing |
| Every sign-in answers "Incorrect username or password" | The account has no password on this database: a fresh one, or one just migrated to 0019 | `backend/.venv/bin/python scripts/set_operator_password.py commander analyst` |
| A feed shows `disabled` or `stale` | Poller off in `.env`, or its source is down | Turn it on and restart, or say the source is down; the page says so too |
| The event list is empty | No two real reports have clustered yet | Correct. Show the feeds (Scene 1) and the corroboration rule |
| The same report appears twice in the feed | Two backend processes on one broker | Kill one. One process only |
| First report seems to hang | Embedding model still loading | It is warmed at startup; wait for `✓ Embedding model warm` in the log |
| An event has fewer reports than were filed | One was suppressed as a duplicate, or is still in the pipeline | Provenance lists each report; `curl localhost:8000/api/reports/track/<docket>` |
| The map's badge counts incidents but no pins show | A late map `load` wiped the pins (BUG-043 race, fixed 22 Sep) | Should not recur; if it does, switch view once and report it |
| An event has no boundary polygon | Polygon computation failed, non-fatal | The event is still correct; say so |
| Confidence differs from a past measurement | Different reports, different rainfall | Correct behaviour — it is live data |

---

## The four sentences to have ready

1. **"The score is <the number on screen>, out of a coverage of 0.80."** Never one without the other.
2. **"Quarantined is the right answer here."** Say it before it is asked.
3. **"That factor is offline, and the receipt says so."** For vision and anomaly, every time.
4. **"Nothing on this screen was typed for today."** Everything came from a public feed or from
   someone who filed a report.
