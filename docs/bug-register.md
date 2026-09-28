# INDRA — Bug Register

| | |
|---|---|
| **Scope** | The core platform: layers 1, 2, 3, 5, 6, 7 and 8a, plus the test suites and infrastructure. A layer 4 or layer 9 defect is recorded when it affects this code or its suite, and handed to that layer's owner |
| **Entries** | BUG-001 … BUG-122 |
| **Last reviewed** | 28 Sep 2026 |

Every defect found since the 16 Sep 2026 sprint began: what was observed, what was done about it
and, for anything not fixed, the honest sentence to say if asked. **Nothing is ever removed.** An
entry changes status and never disappears, and a fix is appended to the entry it closes. The log
below is chronological. The summary directly below it is the current state.

**Why it is published.** A defect list is the most useful document a team can share and the one
most often kept private. A teammate who hits `command not found: docker`, or a reviewer who asks
whether the audit trail can be edited, should find the answer here without having to ask.

> **Reading older entries.** Entries describe the system as it was when they were found. The
> MiniLM measurements and "vision/anomaly missing" findings predate the frozen AI/ML components of
> PR #39. For layer 4's current state see [ML architecture](ML_ARCHITECTURE.md) and
> [ML validation](ML_VALIDATION_REPORT.md).

## Current status — 28 Sep 2026

### Open

| Bug | Sev | Layer | Summary |
|---|:-:|---|---|
| BUG-099 | S3 | 7 | Test and demo rows remain in the committed `data/live/` snapshot. The exporter is fixed; deleting the rows is the remaining step |
| BUG-059 | S3 | Tests | One test compares `CORS_ORIGINS` with the code default and fails on a server that adds its public origin |
| BUG-066 | S3 | 6 | The merge catchment (`impact_radius_km + eps`) has no upper bound |
| BUG-106 | S3 | 4 | Two dataset-hash tests in layer 4's package fail on LF checkouts. Handed to the ML owner; these are the suite's only failures |
| BUG-115 … BUG-118 | S3 | 3 | Hazard-tagger misses measured on the third independent real-post sample (16 of 100 rows). Bounded: a posts-only event always waits for a human |

### Accepted

| Bug | Status | Summary |
|---|---|---|
| BUG-010 | `BY-DESIGN` | The audit chain cannot detect a truncated tail without an external anchor for the head hash |
| BUG-011 | `BY-DESIGN` | Two backends on one broker re-deliver reports, so the rule is one backend process |
| BUG-013 | `BY-DESIGN` | The dedup threshold is measured from both sides; catching more paraphrases would discard real witnesses |
| BUG-019 | `BY-DESIGN` | Re-normalisation means losing a weak factor can raise the score. Coverage is published beside it |
| BUG-015 | `WONT-FIX` | The layer 4 event-type classifier never met its gate and stays frozen. Rule-based tagging replaced it |

### Recently closed

BUG-120 (S1): the server's JWT signing key was the published default. Fixed in code, so production
refuses it, and the key on the server was rotated on 27 Sep. BUG-121 and BUG-122 (S2): SACHET
warnings and per-hazard weather now enter the score, merged in PR #47. **Every other entry is
`FIXED`**, with its commit and the test that covers it.

**Rule this file runs on:** a bug is written here **the moment it is observed**, before it is
fixed. A bug that was fixed but never recorded is a bug that comes back during the demo.

## Severity scale

| | Meaning | Handling |
|---|---|---|
| **S1** | Breaks the demo, corrupts data, or loses a report | Fix today, no exceptions |
| **S2** | Wrong number, wrong status, or a lie in an API response | Fix today |
| **S3** | Degraded behaviour with a correct fallback | Fix if time; otherwise document |
| **S4** | Known limit, honest and stated | Never "fixed" — answered |

## Status values

`OPEN` · `IN-PROGRESS` · `FIXED` (with commit SHA + the test that now covers it) ·
`WONT-FIX-TODAY` (with the sentence to say if asked) · `BY-DESIGN`

## Row format

```
### BUG-0NN — one-line title
Severity · Layer · Status · Found by (task or drill) · Date
Repro:    the exact command or input
Expected: …
Actual:   …
Fix:      commit SHA + test name, or the reason it is not being fixed
Say:      (WONT-FIX / BY-DESIGN only) the honest sentence for the nodal officer
```

---

# Open at the start of 20 Sep

These come from `backend-status.md` "Broken / disconnected" and from the Day 4 session A report.
They are carried in here so that today's plan and today's defects live in one place.

### BUG-001 — Confidence can never exceed 0.80, so `AUTO_PUBLISHED` is unreachable
**S2** · Layer 6 · **`FIXED`** by `afbbec5` (T1) · Found by: Day 2 scoring review, re-rated today · 20 Sep

Fix: confidence is now `Σ_online(w·s) / Σ_online w` and the receipt publishes `factor_coverage`.
Six factors at 1.0 with vision and anomaly offline → **1.0, coverage 0.80**.
Tests: `test_a_single_offline_factor_costs_nothing_but_lowers_coverage`,
`test_coverage_is_the_sum_of_reporting_weights`, `test_confidence_stays_in_range_at_every_coverage`,
`test_the_points_column_adds_up_to_the_published_total` (all in `test_fusion_engine.py`).
Measured ladder re-pinned in `test_pipeline_audit.py`: **0.5393 / 0.5654 / 0.5871 / 0.6052**.

Repro: score any cluster with every online factor at 1.0.
Expected: `1.0`.
Actual: `0.80` — `vision_analysis` (0.15) and `anomaly_detection` (0.05) score `0.0` while keeping
full weight. Acceptable while they were unbuilt; **since AI/ML left the scope on 20 Sep they will
never come online**, so the scale is permanently broken.
Fix: T1 — re-normalise over online factors, publish `factor_coverage`.

### BUG-002 — Severity is derived from cluster size, not from the reports
**S2** · Layer 6 · **`FIXED`** by `e3113bc` (T3) · Found by: Day 1 code read · 20 Sep

Fix: `max()` of a depth axis (≥120 CRITICAL / ≥60 HIGH / ≥20 MODERATE / else ADVISORY) and a
corroboration axis (≥10 HIGH / ≥5 MODERATE / else ADVISORY), over non-duplicate reports only.
Depth is re-extracted from `raw_text` at scoring time by the pure `extract_metadata`, so the rule
cannot silently degrade to count-only when an enrichment step fails. Receipt gains `severity_basis`
naming the winning axis, the deepest measurement and the phrase it came from.
Tests: `tests/test_severity_rules.py` (38 tests), plus
`test_a_waist_deep_report_raises_severity_without_more_reports` and
`test_a_suppressed_duplicate_cannot_grade_the_event` in `test_pipeline.py`.

Two traps found and pinned while fixing it:
- **`Severity` is a `str` enum, so `max(CRITICAL, HIGH)` returns `HIGH`** — alphabetically. The
  two-axis maximum needed `key=SEVERITY_ORDER.index`; without it the bug is silent and confined to
  the most serious events. `test_max_is_not_alphabetical`.
- **A reposted alarming text could grade an event.** Dedup keeps duplicates out of clusters, but
  severity takes a *maximum*, so `_report_texts` filters `duplicate_of IS NULL` too.

Side effect to state plainly: **`ADVISORY` is now reachable and common.** With
`DBSCAN_MIN_SAMPLES=2` most fresh clusters are 2–4 depth-free reports, where the old rule floored at
`MODERATE`. Two people reporting water on a road is an advisory. No quadrant changes
(`assign_quadrant` already groups ADVISORY with MODERATE), but the dashboard's severity filter chips
are `['ALL','CRITICAL','HIGH','MODERATE']` — **ADVISORY events show under ALL but are not
filterable. Frontend handover item, not a backend fix.**

Repro: one report saying "water 2 metres deep" → `LOW`. Twelve reports saying "small puddle" →
`HIGH`.
Expected: severity reflects the evidence.
Actual: `pipeline.py::_derive_severity(cluster_size)` grades by popularity. The docstring already
admits it is a stand-in.
Fix: T3 — rule over max depth and corroboration count.

### BUG-003 — `text_processing.py` is committed but imported by nothing
**S3** · Layer 3 · **`FIXED`** by `b1aa2e1` (T2) and `e3113bc` (T3) · Found by: T0 baseline read · 20 Sep

Fix: two consumers now, not one. `api/reports.py` calls it at ingest and stores the result in
`raw_reports.analysis` (migration `0005`); `pipeline.py` calls `extract_metadata` at scoring time for
content severity. Added `detect_language(s)` → `en`/`hi`/`hinglish`.
Tests: 7 new cases in `test_reports_api.py`, 25 new in `test_text_processing.py`.
Verified against real Postgres — `(analysis->>'depth_cm')::int` reads back `76` for
`"2.5 ft paani Kankarbagh main road"`. Migration `0005` down→up round-trips clean.

**Two corrections to what the day plan assumed** (worth keeping, because the plan's test table is
what a reader would trust):
- **There is no landmark extraction, and T2 did not add one.** `places` resolves the gazetteer, so it
  yields *cities* — `"Patna"`, never `"Gandhi Maidan"`. Pinned in
  `test_places_are_gazetteer_cities_not_landmarks` so the field name cannot quietly become a claim.
- **Ingest accepts text of 5–2000 characters.** The plan's table implied `""` and a 4,000-character
  string were accepted and analysed; they are correctly **422** before analysis runs.

### BUG-020 — A flat Hinglish marker list scored 100% and was still wrong
**S3** · Layer 3 · **`FIXED`** by `b1aa2e1` (T2) · Found by: probing the detector before trusting its score · 20 Sep

Recorded because the *number* was fine and the *detector* was not — exactly the failure mode this
project's honesty rules exist to catch.

Repro: a single flat romanised-Hindi marker set, measured on `data/labelled/reports_v1.csv`.
Expected: a score that reflects real behaviour.
Actual: **100% on both splits**, while misreading **5 of 7** plain English sentences as Hinglish —
"Water is rising towards me", "Please log this report", "The auto stand…", "A band of heavy rain…",
"…on par with last year". The markers `me`, `log`, `auto`, `band`, `par` are ordinary English words.
The synthetic dataset simply never contained such a sentence, so the metric could not see the bug.

Fix: two tiers — strong markers (never English: `paani`, `ghutno`, `hai`, `mein`, …) count alone;
weak particles (`me`, `par`, `log`, `band`, `auto`, `ka`, `ke`, `se`, …) need **two**. Still 100% on
both splits, and all 7 English probes now correct.
Tests: `test_plain_english_is_not_mistaken_for_hinglish` (6 cases) documents the reason the design
has two tiers, so nobody "simplifies" it back.

Say: "It scores 100% on my labelled split, and I don't quote that as an accuracy figure. The data is
synthetic and generated by this project, so the three languages are cleanly separated — the number
says the rule agrees with how I wrote the data, not that it reads real reports perfectly. I found
that out by probing it with ordinary English sentences, and the first version failed five of seven."

Repro: `grep -rn "text_processing" backend/app --include='*.py'` → only the module itself.
Expected: cleaned text and extracted metadata stored per report.
Actual: 236 lines of tested dead code (Day 4 T10); its consumer was the cancelled ML task T11.
Fix: T2 — migration `0005`, `raw_reports.analysis jsonb`.

### BUG-004 — `GET /api/dashboard/summary` serves demo KPIs on DB error regardless of `DEMO_MODE`
**S2** · Layer 8a · **`FIXED`** by `bcd4b85` (T8) · Found by: Day 2 demo-gate sweep · 20 Sep

Fix: routed through `demo_fallback()`. `DEMO_MODE=false` + DB error → **503**; empty DB → **zeroes**.
**Root cause of its survival:** the endpoint was missing from `test_demo_mode.py`'s `LIST_ENDPOINTS`,
so the hole had no test and outlived a gate added three days earlier. It and `/api/geo/heatmap` are
both in that list now — that, not the fix, is what prevents a recurrence.
**25 Sep:** the gate itself is gone (BUG-100); the test file is now `tests/test_empty_and_unavailable.py`.

### BUG-005 — CORS is `allow_origins=["*"]`
**S3 → S2** · Layer 8a · **`FIXED`** by `bcd4b85` (T8) · Found by: code read · 20 Sep

Re-rated **S2 on inspection**: the wildcard was paired with `allow_credentials=True`, which the CORS
spec forbids and which Starlette resolves by **echoing back whatever `Origin` it is sent**. Any page
on the internet could read this API with the viewer's credentials attached. That is not a hardening
nicety, it is a live cross-origin read.
Fix: `CORS_ORIGINS` setting, defaulting to the two dashboard dev origins.
`test_cors_origins_never_contains_a_wildcard` guards it; `localhost:3000` is asserted to still work.

### BUG-021 — `GET /api/scenario` and `POST /api/demo/trigger` served a fabricated event
**S2** · Layer 8a · **`FIXED`** by `bcd4b85` (T8) · Found by: grepping for other invented numbers during T8 · 20 Sep

**Not in the day plan, and the worst of T8's four.** Found only because T8's exit criterion is
"nothing in the API invents a number the database did not provide", so I went looking for the others.

Repro: `curl localhost:8000/api/scenario`.
Actual: `data/samples/patna_flood_scenario.json` served as a real verified event — **127 signals,
confidence 0.94, `AUTO_PUBLISHED`, `CRITICAL`, "Open-Meteo & IMD AWS recorded 92mm rainfall", 2 "CWC
river level sensors", 10 "verified multimedia evidence".** Every one of those is fabricated: there is
no IMD or CWC feed (no API keys, decided 16 Sep), vision is permanently offline since layer 4 left
the scope, and the real pipeline **cannot reach 0.94**. `POST /api/demo/trigger` broadcast it to the
dashboard over the live WebSocket as a `DEMO_PULSE`, beside genuine `VERIFIED_EVENT` messages.

Fix: both routes and the JSON deleted. Verified first that **nothing in `frontend/` called either**,
so no frontend change was needed. `start.sh`'s banner also advertised the file as "127 reports
verified" and now reports the labelled dataset as synthetic.
Tests: `test_the_scenario_endpoint_is_gone`, `test_the_demo_trigger_endpoint_is_gone`,
`test_the_fabricated_scenario_file_is_deleted`.
**25 Sep:** the dashboard's leftover `DEMO_PULSE` message type went too (BUG-100).

### BUG-022 — `scripts/run_patna_demo.py` exercised nothing and contradicted the code
**S2** · Demo tooling · **`FIXED`** by `bcd4b85` (T8) · Found by: T12/T14 dependency check during planning · 20 Sep

Repro: read the script.
Actual: pure print-theatre — **no HTTP, no Kafka, no database, zero code paths exercised**. It also
printed claims the code contradicts: `ST_ClusterDBSCAN within 0.8km & 4 mins` (real values 5 km /
120 min), a PyTorch/OpenCV vision pipeline and an Isolation Forest that `pipeline.py` passes as
`None`, and it read `receipt['confidence_total']`, a key the code stopped producing. **This was the
script the Day 5 plan had scheduled to drive the nodal-officer rehearsal.**

Fix: rewritten to POST five reports to `/api/reports/submit`, poll `/api/events` for the fused event,
and print **only values read back from the API** — including `factor_coverage`, the per-factor
`state` column and `severity_basis`. Exits non-zero if no event appears, so it is a smoke test rather
than a slideshow. `--official` adds the dispatch report that crosses the review gate.
**25 Sep:** `run_patna_demo.py` and `run_hazard_demo.py` were deleted (BUG-100).

### BUG-023 — `/legacy` serves a prototype dashboard full of fabricated telemetry
**S2** · Layer 8a · **`FIXED`** by `fd0842c` · Found by: T8 sweep · 20 Sep

Decision taken: the route and its template were deleted rather than gated. A page that invents
IMD and CWC telemetry is not made safe by being hard to reach.

Repro: `curl localhost:8000/legacy`, or open it in a browser.
Actual: `backend/app/templates/index.html` (1,069 lines) is the old prototype command center, served
live by the backend, and it claims what the system does not have:

- `IMD AWS Station 42410 registered 92.4mm rain pulse` — no IMD feed exists
- `CWC Gauge: Ganga level rising 4.2cm/hr at Digha Ghat` — no CWC feed exists
- `PyTorch Vision detected waist-deep floodwater (Prob: 0.91)` and `Photo flood_412.jpg verified by
  PyTorch CV (0.94 water prob)` — vision is permanently offline
- `127 Signals`, `Run Patna Demo (127 → 1)`, `Scene 7: Multi-Modal PyTorch & Anomaly Corroboration`

It is the same class of problem as BUG-021 and larger. **Not changed unilaterally** — deleting a
1,069-line artefact that may be wanted for the pitch is a decision, not a test fix.

Options: (a) remove the `/legacy` route and the template; (b) keep it behind `DEMO_MODE` with a
banner stating it is a non-functional mockup; (c) strip every unsupported claim from it.
**Recommendation: (a)** — the real dashboard is on :3000, and a mockup that contradicts the backend
is a liability with a nodal officer in the room.

Say (until decided): "That's the original prototype mockup from before the pipeline existed. It's
static and it is not what I'm demonstrating — the live system is the Next.js dashboard on 3000. I'd
rather delete it than have it contradict the backend."

Repro: `DEMO_MODE=false`, stop Postgres, `curl /api/dashboard/summary`.
Expected: 503.
Actual: invented KPIs, presented as real. The one endpoint that escaped the Day 2 gate.
Fix: T8 — route through `demo_fallback()`.

### BUG-005 — CORS is `allow_origins=["*"]`
**S3** · Layer 8a · **`FIXED`** by `bcd4b85` (T8) · Found by: code read · 20 Sep

Fix: `CORS_ORIGINS` in `config.py`, defaulting to the dashboard's two dev origins. Paired with
`allow_credentials=True`, the wildcard was a combination the CORS spec forbids and Starlette papers
over by echoing whatever `Origin` it is sent — so any page on the internet could read this API with
the user's credentials attached.

Repro: `curl -H 'Origin: http://evil.example' -I localhost:8000/api/events`.
Expected: no `Access-Control-Allow-Origin`.
Actual: `main.py:64` allows every origin.
Fix: T8 — settings list defaulting to the demo origins. **The dashboard on :3000 must keep working.**

### BUG-006 — First event takes 12.7 s (cold MiniLM load) — **re-rated S1: it freezes the whole API**
**S3 → S1** · Layers 3, 8a · **`FIXED`** by `bf626eb` (dedup off the event loop) and the startup warm-up · Found by: Day 1/Day 2 live runs; **true severity found by the T14 cold-start rehearsal** · 20–21 Sep

Re-rated after the cold rehearsal, which is the first time this was measured from an empty volume.

Repro: `docker compose down -v && up -d`, `alembic upgrade head`, start the backend, run
`scripts/run_patna_demo.py`.
Expected: a slow first event, per the original S3 reading.
Actual: **`GET /api/events` timed out entirely.** The demo script died on a 10 s read timeout while
polling. The pipeline then completed normally (5 reports → 1 event) and the endpoint answered in
**0.03 s** immediately afterwards.

**Cause — worse than "the first event is slow".** `DedupService.find_duplicate` is a synchronous
method, and `model.encode(...)` inside it (`dedup.py`) is blocking, CPU-bound work. It is called
directly from the async `process_report`, so loading MiniLM and encoding on the first report **blocks
the uvicorn event loop for ~13 s**. Nothing else can be served in that window — not `/api/events`,
not `/healthz`, not the WebSocket. The original framing ("first-event latency is 12.7 s") described
the symptom on one request; the reality is that **the entire API is unavailable during it, on a cold
start, which is exactly when a demo begins.**

Why 518 tests missed it: the unit tests call `find_duplicate` directly (no event loop to starve), and
the integration tests run against an already-warm process.

Two fixes, both applied — the first is the real one:

1. **Dedup runs off the event loop.** `pipeline.py` now calls it through `asyncio.to_thread(...)`, so
   model loading and every subsequent encode happen on a worker thread. This fixes the whole class of
   problem, not just the first call: every dedup check was blocking the loop for its duration, so
   throughput under load was also serialised behind it.
2. **The model is warmed at startup** (the old T9 stretch task), in a background lifespan task that
   does not delay readiness. The first real report then pays nothing, and `/healthz` answers
   throughout.

This is the clearest argument for the day's rule that a rehearsal must actually be run: the bug was
invisible to the whole test suite, was mis-rated S3 for five days, and would have presented as a
frozen dashboard in the opening seconds of the demo.

Repro: start the backend, submit one report, time the `VERIFIED_EVENT` broadcast.
Expected: a couple of seconds.
Actual: 12.7 s, nearly all of it loading the embedding model on first use. In front of a nodal
officer this reads as a hang.
Fix: T9 — warm the model in a lifespan task.

### BUG-007 — Redis is deployed and health-checked but used by nothing
**S3** · Layer 7 · **`FIXED`** by `efc9c38` (Day 6 T1) · Found by: Day 1 audit · 20 Sep · Closed 21 Sep

Repro: `redis-cli dbsize` after a full demo run → `0`.
Expected: a dependency in `docker-compose.yml` either does a job or comes out.
Actual: it is checked by `/healthz` and otherwise idle; the weather cache and the broadcast-dedup
set are both process-local and lost on restart.
Fix: `services/cache.py` gives Redis two real jobs — the Open-Meteo reading per H3 cell
(`wx:{cell}`, TTL 600 s, 60 s for a remembered failure) and the broadcast-dedup set
(`bcast:{id}`, TTL 24 h, `SET NX`). Both keep the previous in-memory path as a fallback, so a
stopped Redis degrades and breaks nothing.

The half worth having: before this, a restarted backend re-broadcast every re-delivered report,
because the `OrderedDict` died with the process. That is the one thing memory could not do.

Two decisions recorded while fixing it:
- **A failure cools down for 30 s.** Without it, a 100-report burst against a dead Redis waits out
  one connect timeout per report. The outage logs once, not once per call.
- **The suite runs on the memory fallback** (autouse fixture). A Redis is usually running on this
  machine and the dedup keys live 24 h, so a shared one would carry report ids between test runs
  and make the suite depend on what ran yesterday. `test_cache.py` opts back in deliberately.

Tests: 16 in `test_cache.py`, 5 against a live Redis (TTL bounds, and a reconnect standing in for a
restart). Verified live: `redis-cli dbsize` → 5 after a demo run.

### BUG-008 — `station_readings` has never held a row
**S3** · Layers 1, 7 · **`FIXED`** by `1b84bad` (Day 6 T2) · Found by: Day 2 · 20 Sep · Closed 21 Sep

Repro: `SELECT count(*) FROM station_readings;` → `0`.
Expected: the one real external feed leaves a trace in the historical table.
Actual: Open-Meteo is fetched per event and cached in memory; nothing is persisted; the scheduled
poller was never built.
Fix: `workers/station_poller.py`, a lifespan task polling Open-Meteo every 10 minutes for six
cities and writing one row each, plus `pipeline._weather_for_cluster` preferring a stored reading
within 3 h and 25 km over a live request.

What is **not** in a row matters as much as what is: `agency` is `OPEN_METEO` and never IMD or CWC
(neither has a feed, and a row claiming one would be a fabricated source); `river_level_m` is NULL
(no gauge feed); `anomaly_score` is NULL rather than 0.0 (see BUG-031). A failed request writes no
row at all, so the table never holds a zero that means "we do not know".

Verified live 21 Sep: six rows within seconds of a cold start — Kolkata 17.2 mm, Guwahati 5.6,
Chennai 2.4, Delhi 1.5, Mumbai 1.1, Patna 0.2 — and the demo event's receipt reading
`"source": "station_reading"` with **zero** HTTP calls made while scoring.

Tests: 32 in `test_station_poller.py`. Two real defects found while closing it: BUG-029 and
BUG-030, both below, both invisible to the tests that had just passed.

### BUG-009 — Auth guards only the two endpoints added on Day 3
**S3** · Layer 8a · `WONT-FIX-TODAY` → **`FIXED` 22 Sep** (see Day 9) · Found by: Day 3 · 20 Sep

Repro: `curl -X POST localhost:8000/api/teams` with no token → succeeds.
Expected: mutations require a token.
Actual: only `PATCH /api/events/{id}/review` and `GET /api/events/{id}/provenance` are gated. The
dashboard has no login flow, so gating `POST /api/teams`, `PATCH /api/teams/{id}/assign` and
`PATCH /api/profile/*` today would break the frontend mid-demo.
Fix: not today. The proposal is written in `handover-review-provenance.md` and waits on the
frontend owner.
Say: "Real JWT and role checks are implemented and enforced on the two decision endpoints — the
ones that change a verdict. Extending them to the rest needs the dashboard's login flow, which is
another team member's layer; the proposal is written and handed over."

### BUG-010 — The audit chain cannot detect a truncated tail
**S4** · Layer 7 · `BY-DESIGN` (honest limit) · Found by: Day 3 · 20 Sep

Repro: `DELETE FROM audit_logs WHERE seq > 5;` → `verify_chain` still reports valid.
Expected: tamper-evident.
Actual: each row commits to its predecessor, so any *edit* or *insertion* is caught, but removing
the newest rows leaves a shorter valid chain. Detecting that needs an external anchor for the head
hash, which is out of scope for this sprint.
Say: "The chain catches edits and insertions anywhere in the history. Deleting the newest rows
would need an external anchor for the head hash to detect — that's a known limit, and it's written
down rather than glossed over."

### BUG-011 — Two backends against one broker re-deliver reports
**S1 if it happens** · Layer 2 · `BY-DESIGN` (operational rule) · Found by: Day 2 · 20 Sep

Repro: start two backends; they share the `indra-report-processor` consumer group; a rebalance
re-delivers messages.
Actual: WebSocket fan-out is an in-process list, so a second worker also silently drops events for
half the clients.
Fix: not fixable today (needs Redis pub/sub fan-out, cut). **Demo rule: exactly one backend
process. Check with `lsof -i :8000` before starting.**
Say: "It runs as a single process by design for this build; horizontal scaling needs a shared
pub/sub for the socket fan-out, which is designed and not built."

### BUG-012 — DBSCAN clusters in degrees, ~10% anisotropic at Patna's latitude
**S3** · Layer 5 · `WONT-FIX-TODAY` → **`FIXED` 22 Sep** (see Day 9) · Found by: Day 1 · 20 Sep

Repro: `geo_clustering.py` uses `eps_km * 0.009` as an `eps` in degrees.
Expected: a metre-true radius (`::geography`).
Actual: a degree of longitude is ~10% shorter than a degree of latitude at 25.6°N, so the
neighbourhood is a slight ellipse. Cluster membership is unaffected at the demo's scale.
Fix: deferred — changing clustering and scoring on the same day is forbidden by the standing rule,
and today is a scoring day.
Say: "The DBSCAN radius is in degrees, which is about 10% anisotropic at Patna's latitude. It
doesn't change membership at this scale; moving it to a geography radius is a one-line change I
deliberately didn't make on a day I was changing the scoring."

### BUG-013 — Dedup cosine threshold 0.88 misses paraphrases
**S3** · Layer 3 · `WONT-FIX-TODAY` → **`BY-DESIGN`, measured 22 Sep** (see Day 9) · Found by: Day 1 · 20 Sep

Repro: two reports of the same incident in different words score ~0.85 and are both kept.
Expected: recognised as one.
Actual: 0.88 was chosen conservatively — a false merge (two real incidents collapsed) is worse than
a false split (one incident counted twice, which corroboration handles).
Fix: not today; same standing rule as BUG-012. T8 moves the constant into settings **without
changing its value**, so it can be tuned with evidence later.
Say: "The threshold is deliberately strict. Splitting one incident into two is recoverable;
merging two real incidents hides one. I'd rather over-report to the operator."

### BUG-014 — `KAFKA_EVENTS_TOPIC` has no producer
**S4** · Layer 2 · `BY-DESIGN` · Found by: Day 1 · 20 Sep

Actual: the topic exists as a buffer for a downstream consumer that does not exist. Nothing reads
or writes it.
Say: "It's a provisioned outbound topic with no consumer yet — it's in the compose file, not in the
data path, and I'm not counting it as a working feed."

### BUG-015 — The event-type classifier never met its acceptance gate
**S4** · Layer 4 · `WONT-FIX` (out of scope from 20 Sep) · Found by: Day 4 session A · 20 Sep

Actual: test accuracy 0.789, macro-F1 0.787, but `NOT_RELEVANT` recall 0.667 and 5 of 72 real
floods dismissed — both below the gate set before training, so `accepted: false` and `classify()`
returns `None`. Trained on 300 **synthetic** rows, which the datasheet states.
Fix: none. **Layer 4 left Aditya's scope on 20 Sep**; the code stays committed and frozen as
evidence of a measured, honestly rejected model.
Say: "I trained it, measured it against a gate I set before training, and it missed on the metric
that matters — how often it throws away a real flood. So it ships switched off. A model that isn't
measured doesn't go in the confidence score."

---

# Found on 20 Sep

Rows from T11's drills, T12's burst, T14's rehearsals and anything hit while building T1–T9 go
below, numbered from **BUG-016**. Write the row **when you see it**, then fix it.

### BUG-016 — `bug.md` and the day file both understate where the code is (T0 baseline delta)
**S4** · Docs · `FIXED` (this row *is* the correction) · Found by: T0 baseline · 20 Sep

Not a code defect — a **bookkeeping** one, recorded because today's exit criteria are measured
against the baseline and an unexplained delta must never be assumed benign.

Three facts differed from `aditya_20-sep.md` §"Where the code actually is, right now":

| Claim in the day file | Measured at T0 |
|---|---|
| Last commit `b4b91d8` (Day 4 T10) | **`426dc6d` feat(ingestion): publish verified events** |
| Suite `326 passed, 2 skipped` | **372 passed, 2 skipped, 0 failed** (374 collected) |
| `pytest -m "not integration"` → 191 | **269 passed, 2 skipped**, 103 deselected |

Cause: the 326 figure was measured on branch `aditya_19sep` during Day 4 **session A**. Two
later commits are in the tree and were never folded into the ledger — `b4b91d8` (+40 tests,
`test_text_processing.py`) and `426dc6d` (+6 tests, `test_event_publisher.py`).
**The delta is +46 tests, all passing, zero failures — an under-count, not a regression.**

**`372 passed, 2 skipped` is today's authoritative baseline.** T10's "+45 new tests" target is
therefore measured from 372, i.e. ≥ 417.

Also verified at T0: `git merge origin/main` brought in 12 changed paths, **all under
`frontend/`** — no backend file moved, so the merge cannot explain any behaviour change today.

### BUG-014 — *superseded:* `KAFKA_EVENTS_TOPIC` now **has** a producer
**S4** · Layer 2 · `FIXED` by `426dc6d` (not by today's work) · Found by: T0 baseline · 20 Sep

BUG-014 above says the topic "exists as a buffer for a downstream consumer that does not exist.
Nothing reads or writes it." **The write half is no longer true.**
`backend/app/services/event_publisher.py` publishes every event the pipeline creates or updates
to `settings.KAFKA_EVENTS_TOPIC`, covered by `tests/test_event_publisher.py` (6 tests).

What remains true is only that **nothing consumes it** — it is a real outbound feed with no
subscriber yet. BUG-014's "Say:" line must be corrected in T16; as written it undersells layer 2
and would be an inaccurate answer to a nodal officer.

Say: "Verified events are published to a Kafka topic as they are created — that producer is real
and tested. There is no downstream consumer of it yet, so I count it as an outbound integration
point, not a working end-to-end feed."

### BUG-017 — `assign_quadrant` hard-codes 0.90 / 0.70 and does not follow the settings
**S2** · Layer 6 · **`FIXED`** by `5e9e2f6` (T1c) · Found by: reading `fusion_engine.py` while planning T1b · 20 Sep

Not in the day plan — found because T1b changes a threshold and I checked who else reads it.

Repro: set `HUMAN_REVIEW_THRESHOLD=0.60`, score an event at 0.62.
Expected: `PENDING_HUMAN_REVIEW` **and** a quadrant that is not `Noise`.
Actual: `determine_review_status` read the setting and said `PENDING_HUMAN_REVIEW`; `assign_quadrant`
used a **hard-coded 0.70** and said `Noise`. The Intelligence Matrix would have labelled the very
event it was asking an operator to review as noise. `determine_review_status` had the same latent
split — its own `0.90 / 0.70` defaults meant any caller omitting the arguments applied a different
policy from the pipeline.

Also found in the same read: `get_settings` was **not imported** in `fusion_engine.py`, and
`assign_quadrant`'s bare `except Exception` would have swallowed the `NameError` and fail-safed every
event to `UNVERIFIED_THREAT` instead of surfacing the mistake. A bare except over a scoring
decision hides exactly this class of bug.

Fix: both methods default both thresholds to `settings`. Tests: the quadrant and review-status
boundary tables in `test_fusion_engine.py` (now `0.60` → inclusive, `0.5999` → below).

### BUG-018 — `HUMAN_REVIEW_THRESHOLD` 0.70 sat above almost everything the system can produce
**S2** · Layer 6 · **`FIXED`** by `5e9e2f6` (T1b) · Found by: T1 planning arithmetic · 20 Sep

Repro: stream the 5-report Patna cluster; best score `0.6052`.
Expected: a corroborated multi-source cluster reaches an operator.
Actual: everything stayed `QUARANTINED`. Under coverage-aware scoring a real cluster lands roughly
**0.54–0.70**, so the 0.70 gate was above the reachable range and the pipeline's own `ESCALATE` path
was unreachable with default settings — provably so: `test_default_thresholds_write_exactly_one_
quarantine_row` had encoded "only ever one audit row" as correct behaviour.

Fix: `HUMAN_REVIEW_THRESHOLD` 0.70 → **0.60** in `config.py`, `.env`, `.env.example`, committed
separately from T1 so the scale change and the gate change are reviewable apart.
`AUTO_PUBLISH_THRESHOLD` stays **0.90** — untouched.

Say: "The auto-publish gate is 0.90 and I did not move it; nothing reaches the public without a
human. I did lower the *review* gate to 0.60, because the scoring range a genuinely corroborated
cluster can reach is about 0.54 to 0.70 — at 0.70 a real flood was being quarantined without anyone
seeing it. A quarantined real flood is invisible; an escalated weak signal costs an operator ten
seconds. That trade is the one I want."

### BUG-019 — Losing a weak factor *raises* the confidence score
**S4** · Layer 6 · `BY-DESIGN` (honest consequence, pinned in a test) · Found by: T1 · 20 Sep

Repro: score the 5-report fixture with Open-Meteo reachable, then with it blocked.
Actual: confidence **rises** 0.5874 → **0.6953** while `factor_coverage` falls 0.80 → **0.55**.

This is arithmetically correct — weather scores only 0.35 here, so removing it raises the mean of
what remains — and it is the sharpest question the new design invites. Pinned deliberately in
`test_scoring_determinism.py::test_dropping_a_weak_factor_raises_the_mean_and_lowers_coverage` so it
is documented rather than discovered in front of a nodal officer.

Say: "Yes — and that is why the score is never quoted on its own. 0.6953 means *0.70 of the 55% of
the model we could measure*, not 0.70 of the available evidence. The coverage number is published
next to it precisely so losing a feed can't be mistaken for gaining confidence. The proper fix is a
coverage floor on auto-publishing, which is designed and deliberately not in today's change."

### BUG-024 — With `DEMO_MODE=true` the demo shows a fabricated `0.94 / AUTO_PUBLISHED` event
**S1** · Layer 8a · **`FIXED`** by `a2b9868` (DEMO_MODE off by default) · Found by: **running the rewritten `run_patna_demo.py` against the live stack (T14 prep)** · 20 Sep

The single most dangerous thing found today, and it was found only by actually running the demo
rather than reasoning about it.

Repro:
```bash
# DEMO_MODE=true (the checked-in .env default), empty database
./start.sh -b && backend/.venv/bin/python scripts/run_patna_demo.py
```
Expected: the five submitted reports fuse into one event and the script prints its real numbers.
Actual: the script reported **`WX-EV-28231827-A`, severity `CRITICAL`, confidence `0.94`,
`AUTO_PUBLISHED`, quadrant "Patna Central Sector"** — **0.0 s after submitting**, before the pipeline
had run at all.

Cause: `GET /api/events` correctly routes through `demo_fallback()`, and with `DEMO_MODE=true` an
**empty** result is answered with the hardcoded demo events at `app/api/events.py:66-184` (confidences
0.94, 0.91, 0.89, 0.88, 0.87, 0.85, 0.82). In the seconds between submitting reports and the pipeline
writing the event, the database *is* empty, so the API serves the invented event — and my script
believed it. The real pipeline finished moments later: 5 reports stored, 1 event, 5 linked.

**Why this is S1 rather than S3.** `0.94` and `AUTO_PUBLISHED` are values the real pipeline
*cannot produce* — coverage-aware confidence caps a real multi-source cluster near 0.70, and nothing
reaches the 0.90 auto-publish gate. So a nodal officer watching the dashboard in the first seconds of
the demo would be shown a **confident, auto-published, CRITICAL event that no code computed**, exactly
while being told the system is live. It is the same fabrication class as BUG-021 and BUG-023, but
reachable during the demo itself rather than at a URL nobody visits.

Two fixes, both applied:

1. **`.env`: `DEMO_MODE=true` → `false`.** `config.py`'s own default has always been `False`; the
   checked-in `.env` was overriding it to `true`, so the dishonest mode was the default for every
   developer and every demo. With it off, an empty database honestly shows nothing and reports appear
   as they are submitted — which is a better demo and a true one.
2. **`run_patna_demo.py` now validates that the event it found is real** rather than trusting the
   first thing `/api/events` returns: it requires a `verification_receipt` carrying `factor_coverage`
   (the demo events have no `factors` block at all), and it refuses to continue if it sees the known
   demo `event_code`, printing what happened instead of quietly narrating a fake.

Lesson recorded on purpose: the day plan's T14 would have caught this only if the rehearsal was run
for real. It was invisible to 517 passing tests, because every one of those tests either seeds its own
rows or asserts the fallback *works* — none of them asked whether the fallback could be mistaken for
a live result.

**25 Sep:** `DEMO_MODE` and the fallback events were deleted outright, so this cannot recur (BUG-100).

### BUG-025 — The demo's "official dispatch crosses 0.60" step is not reachable through the API
**S2** · Layers 2, 6 · `WONT-FIX-TODAY` (narrative corrected instead) → **`FIXED` 22 Sep** (see Day 9) · Found by: running the demo with `--official` · 20 Sep

The escalation half of the planned nodal-officer narrative — *"add one `OFFICIAL_DISPATCH` report,
source reliability rises 0.60 → 1.00, the score crosses 0.60 into `PENDING_HUMAN_REVIEW`"* — **cannot
be demonstrated through the public API.** Two independent reasons, found by running it:

**1. `POST /api/reports/submit` hardcodes `source_type = "CITIZEN_APP"`** (`app/api/reports.py:159`).
There is no way for a submitted report to carry any other source. Verified live: after submitting the
"district control room confirms waterlogging" report, `raw_reports` held `CITIZEN_APP|6` and the
receipt's cluster block read `["CITIZEN_APP"]` with reliability 0.60.

**This hardcoding is correct and must not simply be opened up.** If a client could set its own
`source_type`, anyone could claim `OFFICIAL_DISPATCH` and hand themselves reliability **1.00** — the
highest-trust input in the whole scoring model. Source reliability would then measure what a reporter
*claims to be*, which is worth nothing. The real fix is an authenticated ingest path for trusted
sources, which is not built.

**Consequence to state plainly: `source_reliability` is always 0.60 in any live demo,** because
citizen app is the only ingest route that exists. The factor is real and tested
(`test_source_reliability_table`), but nothing in a live run can move it.

**2. Even reliability 1.00 would not have crossed 0.60 today.** Live Open-Meteo rainfall in Patna is
near zero, so the weather factor scored **0.0080** — measured, not assumed. With coverage 0.80:

| scenario | confidence |
|---|---|
| 5 citizen reports, measured | **0.4585** |
| 6 citizen reports, measured | **0.5152** |
| 6 reports with reliability 1.00 (arithmetic) | ~0.5875 — still `QUARANTINED` |
| ~25 citizen reports (density saturates) | ~0.61 — crosses |

So on a dry day the lever that actually crosses the gate is **corroboration count**, not source type.

**Fix applied:** the false claim was removed from `scripts/run_patna_demo.py` — its `--official` flag
was printing that it raised reliability to 1.00 when the submitted report was stamped `CITIZEN_APP`
like every other. The flag now says what it does: it adds one more corroborating citizen report.

Say: "Source reliability is a real factor with real priors, and in a live demo it always reads 0.60,
because the citizen app is the only ingest route built. I deliberately did not let a client set its
own source type — if anyone could claim to be an official dispatch, the factor would measure what a
reporter says about itself, which is worth nothing. A trusted, authenticated ingest path is the next
piece of work. What moves the score in front of you today is corroboration and live rainfall."

### BUG-026 — The demo printed a cluster mid-flight, so its numbers appeared unstable
**S3** · Demo tooling · **`FIXED`** by the settle step in `run_patna_demo.py` · Found by: the first live run · 20 Sep

Repro: submit five reports and read the event immediately.
Actual: printed `3 reports, confidence 0.4585`; eight seconds later the same event read
`5 reports, 0.4984`. Nothing was wrong — the consumer processes reports one at a time and the cluster
was still absorbing members — but on a projector it reads as a number that will not sit still.
Fix: the script now polls `report_count` until it has held steady for 4 s before printing anything.
Measured: all five land within ~8 s on a local stack.
**25 Sep:** `run_patna_demo.py` was deleted (BUG-100).

---

### BUG-027 — `/healthz` reports **healthy** against a database with no schema
**S2** · Layers 7, 8a · **`FIXED`** by the `to_regclass` check in `health.py` · Found by: the T14 cold-start rehearsal · 21 Sep

Repro: `docker compose down -v && docker compose up -d`, then start the backend **without** running
`alembic upgrade head`.
Expected: `/healthz` says something is wrong.
Actual: **`{"status":"healthy"}`**, `database: up`. The first citizen report then failed with
**503** and `asyncpg.exceptions.UndefinedTableError: relation "raw_reports" does not exist`.
Only **3** tables existed (the PostGIS ones); `raw_reports` was absent entirely.

Cause: `check_database()` ran `SELECT 1`, which a reachable-but-schemaless Postgres answers perfectly.
A green health check on an unmigrated database tells the operator the one thing they must not be told
before a demo — and it is the same failure class as the rest of today's work: a component reporting a
state it has not actually verified.

Fix: `check_database()` now also runs `SELECT to_regclass('public.raw_reports')` and fails if the
table is absent, with the message *"database is reachable but not migrated — run `alembic upgrade
head`"*. A catalogue lookup, not a scan, so it costs nothing.
Tests: `test_an_unmigrated_database_is_reported_down`, `test_a_migrated_database_is_healthy`.

### BUG-028 — `pg_isready` returns ready before `indra_db` exists on a fresh volume
**S3** · Infra · `BY-DESIGN` (documented, with the correct gate) → **`FIXED` 22 Sep** (see Day 9) · Found by: the T14 cold-start rehearsal · 21 Sep

This is *why* BUG-027 happened, and it will happen again to anyone scripting a cold start.

Repro:
```bash
docker compose down -v && docker compose up -d
until docker exec indra-postgres pg_isready -U indra_user; do sleep 1; done   # passes in ~2s
cd backend && .venv/bin/alembic upgrade head                                  # FAILS
```
Postgres accepts connections while its entrypoint is still creating the application database, so
`pg_isready` goes green **before `indra_db` exists**. Alembic then connects to a database that is not
there and fails. With its output redirected — as it was in my rehearsal script — it fails *silently*
and the stack comes up with no schema.

The correct readiness gate waits for the database itself, not the server:
```bash
until docker exec indra-postgres psql -U indra_user -d indra_db -c 'SELECT 1' >/dev/null 2>&1; do sleep 1; done
```
**Never redirect `alembic upgrade head` to /dev/null in a start script.** Its failure is the one you
most need to see.

---

# T11 — failure drills, executed 20–21 Sep

Every row below was **run against the live stack**, not reasoned about. Where the real outcome differs
from the day plan's expectation, the real outcome is recorded and the expectation is corrected.

| Drill | Expected | **Actual** | |
|---|---|---|---|
| `docker stop indra-postgres` | 503, `/healthz` 503 < 5 s | `/healthz` **503 `unhealthy` in 1 s**; `database: down`, other three up; submit **503** `{"detail":"Report could not be stored"}`; `GET /api/events` **503** | ✅ |
| Postgres restart | recovers < 30 s, no app restart | **3 s**, no restart, events served again | ✅ |
| `docker stop indra-redpanda` | `/healthz` 503, submit 202 `queued:false` | `/healthz` **503**, `streaming_bus: down`; submit **202 `queued:false`** — stored, not queued | ✅ |
| `docker stop indra-redis` | `/healthz` 200 `degraded`, scoring unaffected | `/healthz` **200 `degraded`**, `redis: down`; submit 202 `queued:true`; event re-scored to **0.5421** while Redis was down | ✅ |
| Open-Meteo unreachable | weather `offline`, event still created, coverage **0.55** | `/healthz` **200 `degraded`**, `weather_api: down`; event created; `factor_coverage` **exactly 0.55**; `provenance.weather_station` = **`offline`** | ✅ |
| Same drill, confidence | — | rose to **0.6647** vs 0.5421 with weather online — **BUG-019 reproduced live.** Weather scored 0.0080, so dropping it raised the mean. This is the number to be ready for. | ⚠ by design |
| `app/ml/artifacts/` removed | app starts, classifier stays offline | app started in **3 s**, `/healthz` **healthy**, ingest and scoring unaffected. **Layer 4 is provably not load-bearing.** | ✅ |
| Garbage input | 422 each, nothing stored, no 500 | no text **422** · empty text **422** · `lat=999` **422** · out-of-India **422** · malformed JSON **422** · 10 MB text **422** · `latitude:"north"` **422**. No 500s. | ✅ |
| SQL in the text field | plan said 422 | **202, and that is correct.** `'; DROP TABLE raw_reports; --` is valid *report text* (28 chars). It was stored **verbatim**, language `en`, and all **10 tables survived** — which is the actual proof that queries are parameterised. Rejecting it would be theatre. **Plan expectation corrected.** | ✅ |
| Kill the backend mid-pipeline (`SIGKILL` during 8 concurrent submits) | no half-written event, chain valid | **0** events with NULL confidence, **0** with NULL receipt, **0** orphaned `event_id` links; `verify_chain` **valid**; recovered in **6 s** with no manual repair | ✅ |
| Two backends on one broker | known-bad, documented | not re-run; **BUG-011** stands as the operational rule. `lsof -i :8000` before starting. | ⏸ by design |
| Review + provenance end to end | approved, chained, score untouched | token via `POST /api/auth/token`; provenance listed **103 reports**, chain valid; approve → **`HUMAN_APPROVED`**, audit `[QUARANTINE, HUMAN_APPROVE]`, chain valid at 2 rows; **`confidence_score` unchanged at 0.4555** | ✅ |

**Correction to the day plan:** it says to start the backend with `./start.sh bg`. There is no `bg`
subcommand — the flag is **`-b`** / `--background`. Both demo scripts now say so.

# T12 — 100-report burst, measured

`backend/.venv/bin/python scripts/burst_reports.py --count 100 --spread-km 3 --city patna`
(model pre-warmed, so these are steady-state numbers, not a cold MiniLM load). The script was deleted
on 25 Sep with the other synthetic injectors; the numbers stand as measured.

| Measure | Value |
|---|---|
| Accepted | **100/100**, 0 rejected, 0 accepted-but-not-queued |
| Stored | **100/100** — nothing lost between 202 and the database |
| Throughput | 215 reports/s (0.5 s wall) |
| Submit latency | **p50 4 ms · p95 5 ms · max 94 ms** |
| Events created | 1 (all 101 reports merged into one event — 3 km spread is inside `DBSCAN_EPS_KM` 5.0) |
| Duplicates marked | 0 |
| `pg_stat_activity` | 2 → 3 (**Δ+1**) — no connection leak |
| Backend RSS | 137.6 → 139.5 MB (**Δ+1.9 MB**) — no memory leak |
| Boundary polygons | **1/1** populated |
| `factor_coverage` | 0.80 |
| Severity | **HIGH** — 101 reports crosses the count axis' 10-report cut |
| `verify_chain` after | **valid** |
| Audit rows | **1** — the trail records status *changes*, not traffic; it was QUARANTINED at 3 reports and stayed there |

Worth knowing for the demo: **confidence fell to 0.4555 with 101 reports**, lower than the 5-report
cluster's 0.4984. That is correct and follows from the design — 100 reports scattered over a 3 km
radius have a wide diameter, so spatial coherence drops (~0.34) and outweighs density saturating at
1.0. A tight cluster is stronger evidence of one incident than a diffuse one. **Do not present the
burst as a confidence-raising demo**; present it as throughput and leak evidence.

The leak checks were the point: `reports.py` builds a fresh `AIOKafkaProducer` per request and
`weather.py` a fresh `httpx.AsyncClient` per cache miss, so both were plausible leak sources. Neither
leaked at this volume.

## End-of-day summary

| | Count |
|---|---|
| Open at start of day | 15 (BUG-001 … BUG-015) |
| Found today | **13** (BUG-016 … BUG-028) |
| Fixed today | **17** — BUG-001, 002, 003, 004, 005, 006, 014, 016, 017, 018, 020, 021, 022, 023, 024, 026, 027 |
| `OPEN` S1/S2 at end of day | **0** |
| Carried into the demo | BUG-007, 008 (`WONT-FIX-TODAY`, both with a "Say:" line) · BUG-009, 012, 013, 025 (`WONT-FIX-TODAY`) · BUG-010, 011, 015, 019, 028 (`BY-DESIGN`) |

**Commits:** 12 across two branches — `aditya_20sep` (6, PR #22 → `main`) and `aditya_21sep`
(6, PR #23 → `aditya_20sep`). Suite **372 → 520 passed**, 2 skipped, 0 failed.

### The four that mattered most, and what found them

1. **BUG-024** (S1) — with `DEMO_MODE=true`, an empty database answered `GET /api/events` with a
   fabricated `0.94 / AUTO_PUBLISHED / CRITICAL` event, and the demo's opening seconds are exactly when
   the database is empty. **Found by running the demo, not by testing it.** 518 passing tests could not
   see it: every one either seeds rows or asserts the fallback *works*; none asked whether the fallback
   could be mistaken for a live result.
2. **BUG-006** (re-rated S3 → S1) — dedup's blocking `encode()` froze the **entire** event loop for
   ~13 s on the first report. Mis-rated for five days as "slow first event". **Found by the cold-start
   rehearsal**, when `GET /api/events` timed out completely.
3. **BUG-021 / BUG-023** (S2) — two live surfaces serving invented IMD/CWC/vision telemetry. **Found by
   taking T8's exit criterion literally** and grepping for the *other* places that invent numbers,
   rather than only fixing the one the plan named.
4. **BUG-027** (S2) — `/healthz` green against a schemaless database. **Found by a rehearsal mistake**
   (a silently-failed `alembic upgrade head`), which is the best kind of finding.

### The lesson worth carrying to Round 2

Every one of the four above was invisible to a green suite. Three were found by **running the thing
end to end**, and one by **disbelieving a metric** (a flat Hinglish marker list scored 100% on the
labelled split while misreading 5 of 7 plain English sentences — BUG-020). The suite grew from 372 to
520 tests today and would still have shipped a demo that opened with a fabricated 0.94
auto-published event. **Rehearse from a cold volume, and probe every number that looks too good.**

---

# Day 6 — 21 Sep 2026

The last build day. Two carried `WONT-FIX-TODAY` rows (BUG-007, BUG-008) were closed, and closing
them produced three new defects — **all three found by running the thing, none by the tests that
had just gone green.**

### BUG-029 — The station poller stored one hour of rain where the curve reads a day
**S2** · Layers 1, 6 · **`FIXED`** by `c4929c1` · Found by: comparing the first live poll against the live weather path · 21 Sep

Repro: start the backend with the poller enabled, then compare
`SELECT rainfall_mm FROM station_readings WHERE station_code='OM-PATNA'` against what
`weather.fetch_rainfall` reports for the same coordinates at the same moment.
Expected: the same quantity, since T3 had just made the stored row the *preferred* source.
Actual: **0.0 mm stored against 5.0 mm live.** Both numbers were correct and they measured
different things. The poller asked Open-Meteo for `current=precipitation` — millimetres in the
current hour — while `rainfall_to_score` maps IMD **daily** rainfall categories, and the live path
sums `hourly=precipitation&past_hours=24`.

Consequence had it shipped: a day of heavy rain read as no rain. For the Patna scene, the weather
factor scoring 0.0 instead of 0.1477, a confidence quietly lower than the evidence supports, and
**nothing in the receipt to show why** — the factor would have been `computed`, not `offline`.

Fix: the poller requests and sums the same 24-hour series, and `recorded_at` is the end of the
accumulation window rather than when the process happened to ask.
Test: `test_the_poll_asks_for_the_same_window_the_score_curve_reads` asserts the **request** —
`past_hours=24`, no `current` parameter — against `weather.LOOKBACK_HOURS`. The defect was in what
was asked for, so no assertion about the response could have caught it. That is why all 29 tests
passed over it.

**The lesson, and it is yesterday's lesson again:** two sources for one quantity must be compared
against each other, live, before one is preferred over the other. A plausible number and a green
suite are not evidence.

### BUG-030 — The freshness gate was set below Open-Meteo's publication lag
**S2** · Layers 1, 6 · **`FIXED`** by `28101ba` · Found by: reading the timestamps of the first successful poll · 21 Sep

Repro: `SELECT now() - max(recorded_at) FROM station_readings;` right after a poll.
Expected: the day plan set `STATION_READING_MAX_AGE_MINUTES = 30`, and the tests pinned 29 and 31
because those were the numbers in the plan.
Actual: **1 h 50 m.** A poll made at 19:50 UTC returned an hourly series ending 18:00 UTC. Age is
measured on the end of the accumulation window, so at a 30-minute gate **no genuine reading would
ever have qualified.** The stored path would have been dead code that every test exercised with
hand-written rows and no live run ever entered — a feature that silently does nothing, which is
worse than an absent one because it looks present in the ledger.

Fix: 180 minutes, with the reasoning written where the number is. The stored value answers "how
much rain fell here over the last day"; a window that closed two hours ago still answers it.
Test: `test_the_age_gate_clears_open_meteos_real_publication_lag` stores a reading at the measured
110-minute lag, so tightening this gate later fails a test that explains itself.

### BUG-031 — `station_readings.anomaly_score` defaulted to 0.0 for a model that does not run
**S3** · Layers 4, 7 · **`FIXED`** by `1b84bad` (migration `0006`) · Found by: a test asserting NULL and getting 0.0 · 21 Sep

Repro: insert a station reading with `anomaly_score=None`; read it back.
Expected: NULL — anomaly detection left the scope on 20 Sep and does not execute.
Actual: `0.0`, from a `server_default '0.0'` carried since migration `0001` plus a client-side
default in the model, both from a design in which layer 4 would fill the column.

Why it is a defect and not a cosmetic one: **0.0 reads as "computed, and normal".** Every row the
new poller wrote would have claimed a measured anomaly score from a model that never ran. It is
the same class of defect as the fabricated telemetry removed on Day 5 (BUG-021, BUG-023), in a
column rather than in a response, and it would have been harder to spot for being in the data.

Fix: migration `0006` drops the default; the model no longer sets one. No data is touched — the
table had never held a row outside a test. The receipt is unaffected: `anomaly_detection` has
always been `offline` there. This only stops the table disagreeing with the receipt.

### BUG-032 — The Day 5 register said `./start.sh bg` does not exist. It does.
**S4** · Docs · **`FIXED`** (this row is the correction) · Found by: writing the runbook against the script · 21 Sep

The Day 5 notes record a "correction to the day plan": that there is no `bg` subcommand and the
flag is `-b`/`--background`. Reading `start.sh`, both work — `bg|daemon)` is handled at line 1110,
and `-b|--background` sets `COMMAND="bg"` at line 1071.

Recorded because a wrong correction is worse than the original error: it is stated with the
confidence of something that was checked, and the runbook would have taught a presenter to avoid a
command that works.

## End of project — final tally

| | Count |
|---|---|
| Found across the sprint | **32** (BUG-001 … BUG-032) |
| Fixed | **25** |
| Carried, `WONT-FIX` with a prepared answer | BUG-009 (partial auth) · BUG-012 (degree-space DBSCAN) · BUG-013 (dedup threshold 0.88) · BUG-025 (every submit is CITIZEN_APP) |
| Carried, `BY-DESIGN` | BUG-010 (truncated audit tail) · BUG-011 (one backend process) · BUG-014 (verified-events topic) · BUG-015 (classifier below gate) · BUG-019 (losing a weak factor raises the score) · BUG-028 (`pg_isready` before `indra_db`) |
| `OPEN` S1/S2 at close | **0** |

Every carried row has a `Say:` line. None of them is a surprise, and none of them is hidden in a
document the team cannot read — the register ships in `INDRA/docs/bug-register.md`.

### What actually found the bugs

Across 32 defects, the ones that would have broken the demo were found by, in order:

1. **Running the system end to end from an empty volume** — BUG-024 (a fabricated 0.94 event on an
   empty database, invisible to 518 passing tests), BUG-006 (a 13-second freeze of the entire API,
   mis-rated S3 for five days), BUG-027 (`/healthz` green against a schemaless database).
2. **Comparing two sources for the same number** — BUG-029, BUG-030.
3. **Disbelieving a metric that looked too good** — BUG-020 (a Hinglish detector scoring 100% on
   the labelled split while misreading 5 of 7 plain English sentences).
4. **Taking an exit criterion literally and grepping for the other places it applied** — BUG-021,
   BUG-023.

The suite grew from 71 tests on Day 1 to **568** and remains necessary and insufficient. Rehearse
from cold, and probe every number that flatters you.

---

# Day 7 — 22 Sep 2026

The project was declared closed on 21 Sep. It reopened the same evening because the dashboard was
looked at rather than reasoned about: the single map pin read **"Unknown"** and the console showed
**9 reports against 1 event**. Nine defects came out of one screenshot. Seven of them were
invisible to the 520 green tests, and the two most serious are cases where the API states
something the database does not support.

### BUG-033 — Every event with GPS was served as `"city": "Unknown"`
**S2** · Layers 3, 8a · **`FIXED`** by `b9d1d0a`, `bf31b25`, `fbbddce`, `0996289`, `53bd41b` · Found by: looking at the live map · 22 Sep

Repro:
```bash
curl -s localhost:8000/api/events | jq '.[0] | {lat, lng, city, state}'
```
Expected: `Patna, Bihar` — the centroid `25.59428, 85.13746` is Kankarbagh, Patna.
Actual: `{"city": "Unknown", "state": ""}`, which the Recent Events panel renders as the literal
string `"Unknown, "`, trailing comma and all.

Three independent causes, each sufficient on its own:

- **There was no reverse geocoder anywhere in the repo.** `services/geocoding.py` was forward-only
  — name to coordinates — over a 56-entry hardcoded dict. Nothing could turn a point into a name.
- **`geocoding.py:143` returned the placeholder `"India Node"`** whenever coordinates were valid,
  which is the normal case, and never consulted the gazetteer at all.
- **Neither `raw_reports` nor `verified_events` had any place-name column**, and `api/events.py:278`
  read `receipt.get("city", "Unknown")` from a receipt key the live pipeline never writes. The
  *only* writer of that key in the whole repo is `scripts/seed_national_data.py:166` — which is
  precisely why demo data had names and real data did not, and why nobody caught it.

The last point is the one worth keeping: **the fallback string was doing the work of a schema.**
`"Unknown"` looked like a handled edge case and was actually a missing column, a missing resolver
and a missing write, wearing one word as a disguise.

Fix: a committed 737-row district gazetteer with in-polygon points and bounding boxes
(`b9d1d0a`), `reverse_geocode` / `district_by_name` over it, and the `"India Node"` placeholder
removed. It refuses rather than guesses: a point in the Bay of Bengal resolves to `None`.
Tests: `test_reverse_geocoding.py`, 31 cases weighted toward the refusals.

### BUG-034 — "Verified Events: 1" was counting a QUARANTINED event whose own quadrant is "Noise"
**S2** · Layer 8a · **`FIXED`** by `9c76db0` (API) and `9c7bd14` (tiles) · Found by: reading the KPI query against the row it counts · 22 Sep

Repro: `curl -s localhost:8000/api/dashboard/summary | jq .verified_events` → `1`, against a
database whose only event is `INDRA-20260920-001`, confidence **0.4984**, review status
**QUARANTINED**, quadrant **Noise**.

Expected: a tile labelled "Verified Events" counts events that were verified.
Actual: `dashboard.py:74` filters `WHERE review_status != 'REJECTED'`, so `QUARANTINED` and
`PENDING_HUMAN_REVIEW` are both counted as verified. The system's own scoring called this event
noise and the dashboard promoted it to verified on the way to the screen.

This is the Day 5 lesson in a new place. BUG-024 was a fabricated event; this is a real event with
a fabricated status, and it is worse in one respect: there is nothing in the response to disbelieve.

Fix: count only `AUTO_PUBLISHED` and `HUMAN_APPROVED` as verified, and publish the rest as a
separate `awaiting_review` figure so nothing is hidden by being corrected.

### BUG-035 — An event's merge window closes 2 h after creation no matter how recently it absorbed a report
**S2** · Layer 6 · **`FIXED`** by `fbbddce` (column) and `0996289` (window) · Found by: tracing why 4 of 9 reports produced nothing · 22 Sep

Repro: submit a report near an existing event more than `MERGE_WINDOW_MINUTES` after that event
was **created**, however recently it was last updated.
Expected: a report 50 m from a live event's centroid joins it.
Actual: dropped entirely. `_find_mergeable_event` (`pipeline.py:472`) gates on
`verified_at > NOW() - interval`, and the merge branch at `pipeline.py:917-932` updates the
receipt, the score and the severity but **never touches `verified_at`**. The column is an
insert-time default, so it means "created", not "last updated", and the merge window is keyed on
the wrong clock.

Observed consequence, from the live database: a report arrived 7 h 49 m after the event at a point
**50 m** from its centroid, against a spatial gate of 5.5 km. Alone among unassigned reports it
could not satisfy `DBSCAN_MIN_SAMPLES=2`, and the merge window had closed, so it was dropped. The
three later reports then deduped against *it* (`pipeline.py:749`) and were suppressed —
`duplicate_of` set, no event, no corroboration. **Four of the nine reports in the database
contribute nothing, and the dedup rule is what buried the evidence that they existed.**

Fix: an `updated_at` column, maintained on merge, with the window keyed on it.

### BUG-036 — The dashboard is a snapshot: it never refreshes, and `VERIFIED_EVENT` reaches nothing
**S2** · Layers 8a, 9 · **`FIXED`** by `e60db6d` (map) and `9c7bd14` (KPI strip) · Found by: submitting a report and watching the console not change · 22 Sep

Repro: with the dashboard open, `POST /api/reports/submit` enough corroborating reports to fuse an
event. Watch the screen.
Expected: a console labelled "Grid live" shows the event.
Actual: nothing changes until the page is reloaded by hand. The KPI row, the map and Recent Events
all fetch once on mount. The only WebSocket consumer in the entire frontend is `LiveFeed.tsx:61`
and it handles `NEW_REPORT` only — while the backend has been broadcasting `VERIFIED_EVENT` since
Day 1 (`report_consumer.py:88-96`) to nobody at all.

The Day 1 handover note for the `VERIFIED_EVENT` message type was written and the message was
never wired up on the other side. **A handover note is not a delivery.**

Fix: handle `VERIFIED_EVENT` and refetch the affected panels.

### BUG-037 — 112 live agency alerts are collected, stored, and shown on no map
**S3** · Layers 1, 8a · **`FIXED`** by `ac3beec` (coordinates), `0ef1464` (reports), `e60db6d` (layers) · Found by: counting what is in the database against what is on screen · 22 Sep

Repro: `SELECT count(*) FROM agency_alerts;` → **112** real CAP warnings from CWC, IMD and state
SDMAs, 23 of them unexpired. Then look at the dashboard, which shows one pin.

The SACHET poller works, the parser works, `GET /api/alerts/agency` serves them, and the only page
that consumes them is Early Warnings. The map and the situation overview — the two surfaces a
nodal officer actually looks at — show none of it. The most genuinely live data in the system was
the data least visible.

Fix: an agency-alert map layer, drawn distinctly from fused events, plus an active-alert count on
the dashboard.

### BUG-038 — `.env.example` re-introduces the throttling bug the code comment says cost 96 polygons
**S3** · Layer 1 · **`FIXED`** by `2a2e9c8` · Found by: diffing `.env.example` against `config.py` · 22 Sep

Repro: `cp .env.example .env` on a fresh machine, as `docs/setup.md` instructs.
Expected: the value the code settled on.
Actual: `.env.example:78` sets `SACHET_MAX_FETCHES_PER_TICK=25`; `config.py:134` defaults to
**10**, and the comment beside it records that it was lowered *because NDMA answered 403 and 96
stored polygons were wiped*. Anyone following the documented setup gets the old number back.

The reasoning was written down in the right place and the example file was not updated to match,
so the fix survives only for people who never follow the setup guide.

### BUG-039 — `auto_offset_reset="latest"` silently drops every report published before the backend boots
**S3** · Layer 2 · **`FIXED`** by `2a2e9c8` · Found by: reading the consumer while tracing the orphaned report · 22 Sep

Repro: on a fresh environment, publish to `indra.raw.reports` before the backend has ever started,
then start it.
Expected: the reports are processed.
Actual: `report_consumer.py:157` sets `auto_offset_reset="latest"`, so a brand-new consumer group
begins at the tail and everything already in the topic is skipped permanently. Not what happened
in the current database — the group's lag is 0 — but it is a guaranteed silent loss on any cold
start where the producer leads the consumer, and losing a report without a trace is exactly what
this system exists not to do.

### BUG-040 — The setup guide and the runbook both state the wrong migration head
**S4** · Docs · **`FIXED`** by `2a2e9c8` · Found by: running `alembic heads` against the documented value · 22 Sep

`docs/setup.md:73` and `docs/demo-runbook.md:53` both say `alembic upgrade head` lands on
`0006_anomaly_score_defaults_null`. The versions directory contains `0007_agency_alerts` and
`0008_seed_operator_profiles`; the real head is **`0008`**. Both documents were written on the day
`0007` and `0008` were added.

### BUG-041 — Two live API keys sit in `.env` that no code reads
**S4** · Layer 1 · **`FIXED`** by `2a2e9c8` · Found by: checking which `.env` keys are `Settings` fields · 22 Sep

`.env:54` holds a real `OPENWEATHER_API_KEY` and `.env:56` a real `FIRMS_MAP_KEY`. Neither is a
field on the `Settings` class, and `model_config` sets `extra: "ignore"`, so both are silently
discarded at load. `.env.example` declares `OPENWEATHER_API_KEY` **twice** (lines 69 and 103) with
a detailed comment describing an integration that was never written.

Rated S4 and not S3 because `README.md:187` and `docs/setup.md:43` both already say in writing that
these keys are unread. The defect is that the `.env` file still looks wired: a key with a real
value in it reads as a configured feed, and the next person to debug a missing weather signal will
start from the assumption that OpenWeather is in the loop. An inert key that looks live is the same
class of thing as a telemetry field that is always 0.0 (BUG-031) — it is a claim the code does not
honour.

### BUG-042 — A state hint was dropped precisely when the name looked unambiguous
**S3** · Layer 3 · **`FIXED`** by `ac3beec` · Found by: **a test written expecting it to pass** · 22 Sep

Recorded because of how it was found. Writing the CAP resolver, I added
`test_a_near_name_is_not_matched_across_the_country` as a formality — a guard I was
confident already held. It failed.

Repro: `district_by_name("Purulia", state_hint="Kerala")`
Expected: `None`. Purulia is in West Bengal; the hint contradicts it.
Actual: Purulia, West Bengal, returned cheerfully.

`district_by_name` applied its state hint only on the `len(matches) > 1` branch. A name
matching exactly one district was treated as unambiguous and the hint was discarded —
so the check was skipped in exactly the case where it was the only evidence of a
contradiction. The ambiguous names it was written for (Bilaspur, Aurangabad) all worked;
the unique ones silently did not.

Consequence had it shipped: a CAP alert whose `area_desc` names a district in one state
and mentions another is placed in the wrong state, on a national console, as an official
warning. Low frequency, high damage, and invisible — the answer looks perfectly ordinary.

Fix: a state hint constrains every lookup. A hint that contradicts the only match is a
contradiction, not a detail to discard. Measured on the 116 live SACHET descriptions
before and after: still 98 resolved, so the guard cost nothing.

## Day 7 tally

| | Count |
|---|---|
| Found | **10** (BUG-033 … BUG-042) |
| Fixed | **10** |
| `OPEN` S1/S2 at close | **0** |

Suite: **649 → 684** passed, 2 skipped. Frontend: 10/10 Playwright, `tsc --noEmit` and
`next build` clean.

### What found them, again

Nine of the ten came from **one screenshot of the running console**. Not from the tests —
520 were green over all of them — and not from reading the code, which had been read
repeatedly across six days. They came from looking at the thing a nodal officer would
look at and asking why it said what it said.

The tenth, BUG-042, came from writing a test expecting it to pass. That is the same
lesson as BUG-020 on Day 4, where a Hinglish detector scored 100% and misread five of
seven plain English sentences: **the checks worth writing are the ones you are sure will
pass, because the ones you doubt are already handled.**

Two shapes recurred often enough to name:

1. **A fallback string doing the work of a schema.** `"Unknown"` looked like a handled
   edge case and was in fact a missing column, a missing resolver and a missing write,
   wearing one word as a disguise. It survived six days because the synthetic seeder
   wrote the key the API read, so demo data looked right and only live data was wrong —
   the exact inverse of the failure mode this project had been guarding against.
2. **A number that does not mean its label.** "Verified Events: 1" counted an event the
   system's own engine had quarantined and called noise. BUG-024 was a fabricated event;
   this was a real event wearing a status nothing ever gave it, which is harder to catch
   because there is nothing in the response to disbelieve.

And one operational lesson, learned the expensive way: the stack's Docker lives on an
external SSD. It unmounted mid-run, every container vanished, and two Playwright tests
failed in ways that looked like application bugs. Check `docker ps` before believing a
failure.

---

# Day 8 — 21 Sep 2026, browser session

Both found the same way the Day 7 batch was: by opening the running console in a real
browser and looking at it, rather than by reading code or running the suite. The suite
was **684 passed, 2 skipped** before and after — neither defect is visible to it, because
both live in the gap between React state and what MapLibre and the DOM actually did with
that state.

### BUG-043 — The map draws no pins at all until the operator touches a control
**S1** · Layer 9 · **`FIXED`** by `7fa0f31` · Found by: first screenshot of the dashboard · 21 Sep

Repro: cold-load `http://localhost:3000/` and do nothing.
Expected: the map draws the pins its own badge is counting.
Actual: the badge reads **"42 Incidents"**, the roster behind it lists 42 real rows
(Patna, Bokaro, Bidar …), and the globe shows **zero** markers.
`document.querySelectorAll('.maplibregl-marker').length` → **0**. Click any view control
and all 42 appear at once.

This is the whole point of the console, and it was failing silently on every cold load.
Nothing errored, nothing logged, and the counts on screen were all correct — the map just
never drew. A nodal officer opening the dashboard would have seen an empty map of India
next to a badge insisting there were 42 incidents on it.

The cause is a race that `isStyleLoaded()` cannot referee. Instrumenting the real
sequence gave:

| t (ms) | what ran | `hasMap` | `isStyleLoaded()` | markers |
|---|---|---|---|---|
| 0 | pins effect | false | — | 0 |
| 20 | `onStyleReady` → `renderProminentPins` | true | — | **0** |
| 76 | pins effect | true | **false** | **42** |

The map's `load` fires at t=20, when the fetch has not returned and there is nothing to
draw. The markers land at t=76 — and MapLibre still reports `isStyleLoaded() === false`
there, because sprites, glyphs and the first tiles are in flight long after `load`. The
effect therefore bailed out, and the `load` it was implicitly waiting on had already
fired and never fires twice. No third chance existed.

Worth naming: the first fix attempted was to register `map.once('load', …)` from inside
the effect when the style looked unloaded. It typechecked, linted and was **wrong for the
same reason** — it waited on an event that was already in the past. The trace above is
what disproved it. A guard that reads `isStyleLoaded()` is unfixable in place; the
readiness has to become React state so that its arrival is itself a render.

Fix: a `styleReady` state flag, set in `onStyleReady` (outside the `try`, so a failed
projection cannot also cost every pin), with the pins effect and the layer-visibility
effect both gated on it instead of on `isStyleLoaded()`. Whichever finishes last — the
style or the markers — now triggers the draw.
Verified: cold load, no interaction → **42 markers**, matching the badge. Switching to
the India view (`setStyle`, a full style reload) → still 42.
Test: `the map draws the pins its own badge is counting` in
`frontend/e2e/dashboard-cold-load.spec.ts` (`3f49460`) — fails against the unfixed
component, passes with the fix.

### BUG-044 — Four of the six KPI readings showed a red downward arrow on a flat number
**S3** · Layer 9 · **`FIXED`** by `54ec0c6` · Found by: same screenshot · 21 Sep

Repro: load the dashboard with any period where a count has not moved.
Expected: a change of zero reads as no change.
Actual: **"Verified Events 0 ↓0%"**, **"Critical Events 0 ↓0%"**, **"Awaiting Review 2
↓0%"**, **"Active Alerts 46 ↓0%"** — a red `↓` on four of six tiles.

`KpiCard.tsx` computed `isPositive = item.delta > 0` and used a single ternary, so zero
fell into the "down" branch and got the decline colour and the decline arrow. Two of the
four are worse than a rounding artefact: `awaiting_review` and `active_alerts` have no
comparison window at all and carry a **hardcoded `delta: 0`** in `api.ts`, so the arrow
was rendering a trend that is not merely flat but nonexistent.

Small, but it is the class of defect this register exists for: a number that does not
mean its label. A commander glancing at the strip sees four falling indicators during a
flood.

Fix: a third `isFlat` state — muted grey, no arrow, plain `0%`.
Verified in the browser: the six deltas now read `↑100% · 0% · 0% · ↑100% · 0% · 0%`.
Test: `a flat KPI delta is not drawn as a decline` in
`frontend/e2e/dashboard-cold-load.spec.ts` (`3f49460`), which also rejects the
opposite mistake of rendering `↑0%`.

### Note, not a bug — `GET /api/reports/recent` returns `[]`

Checked because an empty field-reports layer looked like BUG-037 regressing. It is
correct: all 14 `raw_reports` rows are either fused into an event (11) or suppressed as
duplicates (3), and the endpoint's `unfused_only` default excludes both by design. The
layer is empty because there is nothing unfused to draw, which is the honest answer.
Worth knowing before the demo: **this layer will be empty on the demo database**, so it
is not something to point at on screen.

### Note, not a bug — 6 of 46 agency alerts have no coordinates

`lat`/`lng` are `null` for 6 active SACHET alerts, so they are listed but not mapped.
Their `area_desc` values are mandal- and locality-level (`MRTS`, `krs-unguturu Mandal`,
`elr-nuzvid, elr-agiripalle, krs-bapulapadu mandals`) — below the district granularity of
the 737-row gazetteer. 39 of 45 resolving is the gazetteer working as specified, not
failing. Say so plainly if asked.

---

# Day 9 — 22 Sep 2026, the team server

Found by checking the shared server (`15.252.50.176`) against the runbook before seeding it for a
rehearsal. Neither defect is in the backend code; both are in what is deployed.

### BUG-045 — The team server serves fabricated events: `DEMO_MODE=true` in the deployed `.env`
**S1** · Layer 8a / infra · `OPEN` → **`FIXED` 22 Sep on the server, impossible since 25 Sep** · Found by: comparing the server `.env` to the runbook before seeding · 22 Sep

Repro: `curl -s http://15.252.50.176:8000/api/events`
Expected: `[]` — the server database holds **0** verified events.
Actual: `ev-patna-01`, **`0.94 / AUTO_PUBLISHED / critical`**, `verified_at 2026-09-15T11:45:00Z`,
followed by a fabricated `0.88` Guwahati cloudburst.

This is BUG-024 again, not in the code (`config.py:164` defaults to `False`, `.env.example:58` says
`false`) but in the server's hand-written `.env`, which was never compared against `.env.example`.
The KPI endpoint is honest (`verified_events: 0`), so the map and the counter disagree on screen.
**If you tested against the server between 21 and 22 Sep, the Patna 0.94 and Guwahati 0.88 events
you saw were not real.**

Fix: `DEMO_MODE=false` in `/opt/indra/.env`, then `sudo systemctl restart indra-api`;
`/api/events` must return `[]`. The same edit should set `ENVIRONMENT=production` — its only
effect (`database.py:24`) is SQLAlchemy echoing every SQL statement into the API log.

**→ `FIXED`.** On 22 Sep, at the deploy, the server's `.env` was set to `DEMO_MODE=false` and
`ENVIRONMENT=production` (recorded in Aditya's server notes; not re-checked on the server since).
**Since 25 Sep it cannot recur:** `DEMO_MODE`, `core/demo.py` and every hardcoded payload
were deleted (BUG-100), so a `DEMO_MODE` line left in any `.env` is ignored.

### BUG-046 — `next build` fails on `main`, so the server cannot run a production frontend
**S2** · Layer 9 · **`FIXED`** by `1004d75` (events page) and `2f411d1` (alerts page) · Found by: building on the server, 21 Sep; `tsc --noEmit` on `main`, 22 Sep

Four type errors, all the same shape: `alerts/page.tsx:180` and `events/page.tsx:92-93` treat
`city` / `state` (`string | null`) as strings. Came in with `1725a84` through PR #26. `null` is
correct from the API since BUG-033. The server works around it with `next dev`.

Say: "The test server serves the dashboard in development mode because of a type error in two
pages, which is with the frontend owner. It does not change anything the API returns."

A correction that goes with it: the Day 7 tally says `next build` was clean. That was true on
`aditya_22sep_a`; it has not been true on `main` since PR #26 merged.

---

# Day 9, continued — the carried rows closed, and what reading every page found

Branch `aditya_22sep_c`. Backend suite **684 → 746** passed, 2 skipped (62 new tests); dashboard
**26/26** Playwright tests, 13 of them new. Every row below names its commits and its test.

## The carried rows

### BUG-009 → `FIXED` — every write requires a token
`32e6135` (teams), `fc51a39` (profile), `7e89ca0` (dashboard sends the token) · Test:
`test_mutation_auth.py`, 21 tests, **15 of which fail against the previous routers**

The reason it was carried — the dashboard had no login flow — turned out not to hold: the
dashboard already fetched a JWT for its selected persona for review and provenance. Team creation
and dispatch now need COMMANDER/ADMIN; profile and preference edits need a token and change only
the token's own operator. `PATCH /api/profile/me?user=admin` used to let anyone rewrite anyone.
The test walks the OpenAPI schema, not `app.routes` — FastAPI 0.141 hides included routers there,
which the test's own guard caught — so a mutation added later without a guard fails the suite.
Say: "Every write is role-checked and attributed. The demo accounts' passwords ship with the
dashboard's persona switcher, so this shows roles, not secrecy; a deployment needs a real login."
**25 Sep:** no password ships with the dashboard any more (BUG-093). Say instead: "Every write is
role-checked and attributed to the operator who signed in. There is no MFA."

### BUG-012 → `FIXED` — DBSCAN uses a great-circle radius
`05da3fa` · Test: `test_dbscan_great_circle.py` (15, boundaries at 4.99/5.01 km both ways, at
8.5°, 25.6° and 34°N) and `test_geo_clustering.py::test_two_reports_4_8_km_apart_east_west_cluster_at_patna`,
which fails against the degree-based code

PostGIS has no geography DBSCAN, so the candidates are read from SQL and clustered with
scikit-learn's haversine DBSCAN in a worker thread; same core/border rule, same return shape. The
old note had the direction backwards: the neighbourhood was **narrower** east-west (4.5 km), not
wider. The Patna demo cluster was unchanged — same five reports, same 39-vertex boundary.

### BUG-013 → `BY-DESIGN`, measured — the expectation was wrong
`d592c25`, `5242364` · Test: `test_dedup_corroboration.py`, 9 tests that pin the threshold from
both sides (0.85 fails a witness case, 0.93 fails two resubmission cases)

A duplicate is never counted as corroboration, so "catch paraphrases" means "discard witnesses".
Measured with the production MiniLM: resubmissions (punctuation, case, `URGENT:`, `Fwd:`)
0.91–0.99; independent witnesses 0.81–0.91. 0.88 catches every resubmission measured and keeps
four witness pairs of five. The fifth (0.909) is suppressed today — the real limit, which needs a
reporter identity the anonymous channel does not collect.
Say: "Dedup exists to catch the same message sent again. A second person in their own words is a
witness, and we measured that the threshold keeps them."

### BUG-025 → `FIXED` — a trusted source can reach the pipeline, through a token
`028a87e` (migration `0010`, `submitted_by`), `169c614` (route), `4a77c68` (provenance),
`4bf0c32` (demo `--official`), `9055d22` (dashboard option) · Test: `test_official_ingest.py`, 9

`POST /api/reports/official`, COMMANDER/ADMIN, stores `OFFICIAL_DISPATCH` with who filed it. The
public route still cannot claim a source. Live, cold start: five citizen reports scored 0.5146
`QUARANTINED`; with one dispatch, **0.6065 `PENDING_HUMAN_REVIEW`**, source reliability 1.00 — the
narrative step this row said could not be shown.

### BUG-028 → `FIXED` — healthy means `indra_db` exists
`30e49c8` (TCP healthcheck), `89b7b75` (`./start.sh infra up` waits) · Verified by a throwaway
container: socket `pg_isready` green at 1.1 s on the temporary init server, TCP green at 3.5 s after
"init process complete". No automated test; it is compose configuration.

### BUG-046 → `FIXED` — `npm run build` passes on the branch

### BUG-045 — still `OPEN` here, `FIXED` at the deploy the same day
The fix is a line in the server's `.env` and a restart; it needs a write on the server, which was
not made from this session. Commands are in the PR.
**25 Sep:** made at the 22 Sep deploy, and impossible since the demo mode was deleted; see the row
above.

## Found 22 Sep by reading every page of the dashboard

None of these was visible to a test, because none of them came from a fallback: they were
constants written into the pages.

### BUG-047 — The warnings page showed invented government bulletins
**S1** · Layer 9 · **`FIXED`** by `ae7366e` · Test: `e2e/no-invented-data.spec.ts`

Four hardcoded bulletins credited to IMD, the Cyclone Warning Division, GSI and CWC — a fictional
"Cyclone Marut", "port signal 8 hoisted", "2,85,000 cusecs" — on every load; any HIGH/CRITICAL
INDRA event, quarantined ones included, presented as an NDMA "CRITICAL WARNING" with a canned
evacuation directive; a pulsing "CAP-INDIA BROADCAST ONLINE". Worse than BUG-024: it impersonated
agencies. The page now shows real SACHET warnings in their issuers' words, and INDRA events
labelled "not an official warning".

### BUG-048 — The map drew a fictional cyclone track and invented sensor readings
**S1** · Layer 9 · **`FIXED`** by `bba49c8`

A "Cyclone DANA — Forecast Track" across the Bay of Bengal, on by default; six static "NDRF
Operational Bases" (Patna labelled 10th Bn — it is the 9th); and, on every pin, "AI Verified",
"Rainfall 86 mm/h", "Wind Gusts 68 km/h", "Water Level +1.9m Danger", chosen by severity alone.

### BUG-049 — The admin console was entirely static
**S2** · Layer 9 · **`FIXED`** by `40b14a3` (page), `47f46c3` (`GET /api/audit/recent`) · Test:
`test_audit_api.py` (7), the e2e health check

"99.98% Uptime · 4 Nodes Active", "BigQuery 14ms · GCP asia-south1", "Zero Breaches · MFA",
"CLEARANCE: LEVEL 5", ALL SYSTEMS OPERATIONAL whatever the state, and an invented audit trail
including a CAP broadcast "pushed to Puri district civil authorities".

### BUG-050 — Other pages' invented figures and claims
**S2** · Layer 9 · **`FIXED`** by `ce4b062` (datasets), `4646eae` (analytics), `c1b67e7` (live map
header), `0c3363c` (settings), `cb8c6e8`, `ae953d8`, `380ccd6`, `71dccee` (badges, copy, nav)

A dataset catalogue of feeds INDRA does not read, "BIGQUERY ML ENGINE" figures, "Tracking: Cyclone
DANA", overlay toggles and a data saver nothing read, hardcoded diagnostics, "IMD • NDRF Synced".

### BUG-051 — Team dispatch was fake end to end
**S2** · Layers 8a, 9 · **`FIXED`** by `32e6135` (backend), `472a972` (dashboard) · Test:
`test_mutation_auth.py` dispatch cases

The page sent every team to `WX-EV-28231827-A`, the code of a fabricated demo event; the backend
failed to parse it and answered 200 "Updated in demo store" from an in-memory list, whatever
`DEMO_MODE` said. A missing team also answered 200 "successfully dispatched". The roster fell back to
four invented officers.

### BUG-052 — A refused profile or duty save was shown as saved
**S3** · Layer 9 · **`FIXED`** by `a111d3b`

### BUG-053 — The live feed mislabelled its messages
**S3** · Layers 8a, 9 · **`FIXED`** by `493a706`, `5a73309`

Every report read "Citizen report"; every event was tagged IMD and "Verified Event", quarantined
ones included, with a missing confidence defaulting to 85%; every review was credited to
"Commander".

### BUG-054 — ADVISORY events were labelled Moderate
**S3** · Layer 9 · **`FIXED`** by `3788016`

### BUG-055 — The demo printed a partial event as final on a cold backend
**S3** · Demo tooling · **`FIXED`** by `e8b6246` · Found by: running `--official` right after a restart

The model finished warming mid-dedup, the last three reports merged seconds later, and the script
printed "steady at 3", 0.4748 `QUARANTINED` for an event the database held at 6 reports, 0.6065.
BUG-026 again. It now waits for every report it sent.
**25 Sep:** `run_patna_demo.py` was deleted (BUG-100).

### BUG-056 — A late map `load` wiped every pin
**S1** · Layer 9 · **`FIXED`** by `38c6785` · Found by: the BUG-043 cold-load e2e test, the moment
BUG-048's layers were removed

`onStyleReady` fires twice and called the renderer captured at mount, whose marker list was empty.
Instrumented: 20 pins drawn at t=1720 ms, all wiped at t=1874 ms. The removed layers had delayed
`load` past the data, hiding it; any slow network could have exposed it.

## Day 9 tally

| | Count |
|---|---|
| Carried rows closed | **6** — BUG-009, 012, 025, 028, 046 `FIXED`; BUG-013 `BY-DESIGN`, measured |
| Found | **12** — BUG-045 … 056 |
| Fixed | **11** |
| `OPEN` | **1** — BUG-045, a server config line |
| Still carried, by design | BUG-010 (truncated tail), BUG-011 (single process), BUG-015 (layer 4), BUG-019 |

### What found them

Reading the pages. The 21 Sep suite asserted the absence of mock-data markers, so it could only
see invented data that arrived through a fallback; a constant typed into JSX went straight past
it. And one more time, the rehearsal: BUG-055 appeared only on a backend started seconds earlier,
and BUG-056 only once a change shifted an event by 150 ms.

---

# Day 9, the deploy — 22 Sep 2026

Found while deploying PRs #28 and #29 to the team server. The full rows, with repro commands, are in
the live register (`aditya/bug.md`).

### BUG-057 — The server `.env` still had the pre-20 Sep review threshold, 0.70
**S2** · Layer 6 / infra · **`FIXED`** on the server, 22 Sep 19:56 IST · Found by: comparing the
server's `.env` key by key against `.env.example`

`.env` beats the code default, so on the server an event scoring 0.60–0.69 was `QUARANTINED`
instead of `PENDING_HUMAN_REVIEW`, and the official-dispatch scene (0.6065) could not reach a human.
The rule since: **compare `.env` with `.env.example` on every deploy.**

### BUG-058 — The team dashboard answered HTTP 500 on every page
**S1** · Infra + layer 9 · **`FIXED`** on the server, 22 Sep 20:00 IST — production build

`next dev` had its `.next/` deleted underneath it by a second frontend started from `start.sh`,
whose `predev` runs `rm -rf .next`. The unit now runs `next start` on a production build. Until
`start.sh` learns to skip the frontend: **never run plain `./start.sh` or `npm run dev` on the
server.**

### BUG-059 — The test suite reads the machine's `.env`
**S3** · Tests · **`OPEN`**

On the server one test compares `CORS_ORIGINS` with the code default and fails, because the server
correctly adds its public origin. New tests pin the settings they depend on.

---

# Phase 1 — 23 Sep 2026

Found while mapping the code for Phase 1 (`aditya/development/phase-1-foundation.md`), each reproduced
on the local stack before it was fixed. Suite **746 → 948** passed, 2 skipped.

### BUG-060 — A report stored while Kafka was down was never published
**S1** · Layer 2 · **`FIXED`** by `59ce1eb`, `75bb2ef`, `c2dcc43`, `d9e7bfe`

Submit stored the report, tried once to publish it, and answered 202 `queued: false`; nothing ever
tried again, so the report was never deduplicated, clustered or scored. The 20 Sep failure drill
recorded exactly that as a pass. The report and its message are now one transaction (an outbox), and
a relay publishes whatever is waiting. Drilled live with Redpanda stopped: ten reports kept, all
published 1.0 s after it restarted, one event, nothing lost (`demo-runbook.md`, Scene 5). The same
drill found two follow-ups, fixed that day: every submit during the outage waited out the 2 s
publish cap, and only one of ten linked reports was stamped `processed_at`.

### BUG-061 — `GET /api/events?severity=foo` answered 503 "Database unavailable"
**S2** · Layer 8a · **`FIXED`** by `92e4f54`

The value went straight to Postgres, failed as an enum cast, and the handler reported the database
error as an outage. Every filter value is now checked first; a bad one is a 422 naming the parameter.

### BUG-062 — `/api/events/distribution` drew live events as a grey, raw `URBAN_FLOOD`
**S3** · Layer 8a · **`FIXED`** by `90aadc4`

Slices were named from a receipt key only the seeder writes. They are now named from the hazard
taxonomy (`"Flood"`).

### BUG-063 — One router that failed to import unmounted every route, and `/healthz` stayed green
**S2** · Layer 8a · **`FIXED`** by `ba4358d`

The ten routers were mounted inside one `try/except` that logged a warning. The app then ran with no
`/api` routes at all while `/healthz`, defined in `main.py`, answered `healthy`. An import error now
stops the app.

---

# 24 Sep 2026 — the frontend team's backend report, checked

`Saba/reports/2026-09-23_backend_issues.md` reported four backend "root causes" behind symptoms seen
on the dashboard. Each claim was checked against the code on `main` @ `c6b8354` before it was written
here, and every item's resolution is now marked in the report itself. Both of its example events are
`WX-EV-…`, a code only the synthetic seeder writes (the pipeline writes `INDRA-YYYYMMDD-NNN`), so two
of the defects were in the seeder. Suite **948 → 963** passed. Fixes merged in PR #31.

### BUG-064 — The synthetic seeder gave events a random review status
**S2** · `scripts/` · **`FIXED`** by `da63990`

Half the seeded events read `AUTO_PUBLISHED` at 0.55–0.89, a value this engine cannot produce, and the
seeder's own quadrant still used the pre-20 Sep 0.70 gate. Status and quadrant now come from
`FusionEngine`, as in the pipeline: 0 of 37 seeded events off the engine's rule (was 11
`AUTO_PUBLISHED` below 0.90).
**25 Sep:** the seeder, `scripts/seed_national_data.py`, was deleted (BUG-100).

### BUG-065 — The seeder linked each report to a random event anywhere in India
**S2** · `scripts/` → layer 6 · **`FIXED`** by `e55ea41`

A seeded Bhojpur event owned reports in Chennai and Delhi. Once the live pipeline merged one real
report into such an event, it recomputed the footprint over every linked report and the radius
spanned the country: the mechanism behind the report's 1,564 km radius. A seeded report now links only
to an event in its own city: farthest 11.7 km, median 4.7 km (was 2,096 km).
**25 Sep:** the seeder was deleted (BUG-100).

### BUG-066 — The merge catchment grows with the event, without a ceiling
**S3** · Layer 6 · **`OPEN`** — Phase 3

A report merges into an event within `impact_radius_km + eps`, and the radius has no upper bound, so
every merge that widens the radius widens the next catchment. With honest data DBSCAN's 5 km chaining
and the 120-minute merge window bound the growth, but nothing caps it. Phase 3's per-family radii
(`services/hazards.py`) are where the catchment and the radius get their ceiling; not patched on its
own because it changes scores.

### BUG-067 — The docs said a high-severity, low-confidence event is never ignored; the code quarantined it
**S2** · Layer 6 + docs · **`FIXED`** by `6083572` (code), `5d0a7e1` (docs) · Aditya chose
severity-aware routing

Routing used confidence alone, so a `HIGH` event at 0.47 was `QUARANTINED`, off the review queue.
Below 0.60 a `HIGH` or `CRITICAL` event now goes to `PENDING_HUMAN_REVIEW`, never quarantine, and still
needs 0.90 to publish; the receipt's `routing.basis` reads `severity` when that is why. Tests:
`test_fusion_engine.py::test_review_routing_with_severity`, `test_severity_rules.py`,
`test_pipeline_audit.py::test_an_override_to_high_keeps_a_weak_event_in_front_of_a_human`.
**Not adopted from the report:** auto-publishing Advisory and Moderate events at ≥ 0.70.

### BUG-068 — README and ARCHITECTURE still stated `HUMAN_REVIEW_THRESHOLD=0.70`
**S3** · Docs · **`FIXED`** by `a1cfe84`

Both now say 0.60, the value since 20 Sep. The same commit removed ARCHITECTURE's claim that
auto-publishing sounds sirens, sends SMS and dispatches teams, which was the cancelled alert engine's
job.

### BUG-069 — The demo KPIs had more citizen reports than reports
**S4** · Layer 8a · **`FIXED`** by `a89d948`

`DEMO_KPIS` had `total_reports` 1,248 and `citizen_reports` 8,421. They are served only with
`DEMO_MODE=true`, which stays false, but an impossible pair should not exist even there.
**25 Sep:** `DEMO_KPIS` was deleted with the demo mode (BUG-100).

### BUG-070 — The dashboard shows its own review status, never the API's
**S2** · Layer 9 · **`FIXED`** by `44f2486` (branch `aditya_24sept_frontend`) · Found by: marking up
the report, 24 Sep

`frontend/src/lib/eventState.ts::safeEventState()` derives the status and the quadrant from severity
and confidence with a 0.90 / 0.70 matrix, and discards the API's `review_status`. `HUMAN_APPROVED` and
`REJECTED` are never shown, so an approved event keeps its machine pill and its Approve button, and
Moderate events in human review show as "Quarantined" (0.60–0.69, the Patna scene on 24 Sep) or
"Auto-Published" (0.70–0.89).

Fix: `safeEventState` returns the API's `review_status` and `quadrant` whenever present and derives
only for a response without them. Aditya made the frontend edit on 24 Sep with his own go-ahead for
that day; handover §16 lists it for the frontend team. Not yet exercised against an approved event.

## 24 Sep — the frontend repair (BUG-071 … BUG-080)

Aditya reported every dashboard page as not working. On the team server the database held **one
report and no events**, so most panels were honestly empty; beside that, these defects were real.
All fixed on `aditya_24sept_frontend`; written and built, the backend parts' SQL run read-only on the
team database, pytest cases written and not yet run.

### BUG-071 — The live feed printed UTC clock times as local, and carried reports only
**S2** · Layer 8a · **`FIXED`** by `5434f51`

`GET /api/feed/recent` formatted `created_at` (UTC) with `strftime("%H:%M")`: a report filed at 20:27
IST showed as "14:57", with no date, three days later. It read `raw_reports` alone, so with no citizen
reports the feed sat still while SACHET stored 107 warnings in 24 h. Now three streams (report, event,
warning in force), each with `at` and an IST `time`. Tests: `tests/test_feed_api.py`.

### BUG-072 — Reports per day bucketed by UTC date, and 7d returned eight days
**S3** · Layer 8a · **`FIXED`** by `bfa9350`

A report between 00:00 and 05:30 IST was counted on the previous day. Now IST days, exactly N rows.

### BUG-073 — Incident Events' ADVISORY filter could never match
**S2** · Layer 9 · **`FIXED`** by `068203c`

The page compared the button name with `severity.toUpperCase()`, and the list API calls ADVISORY
`low`. The same page swallowed request errors and then said "No events match the current filters".

### BUG-074 — Field Reports had no place, status or date
**S2** · Layer 9 · **`FIXED`** by `6f20b66`

Built on the feed endpoint: no district, no fused/duplicate status, a UTC clock time, and a location
search that could not match. Now reads `/api/reports/recent?unfused_only=false` for 30 days.

### BUG-075 — A refetch after VERIFIED_EVENT could get the pre-event list
**S3** · Layer 9 · **`FIXED`** by `6a88062`

`fetchEvents` kept resolved requests 15 s for deduplication; a live update inside that window was
answered from the cache. Window now 2 s.

### BUG-076 — One tab opened five WebSockets to `/ws/events`
**S3** · Layer 9 · **`FIXED`** by `55fe2ab`

Each `useIndraWebSocket()` call opened its own socket and two components opened raw ones. Now one
module-level connection per tab.

### BUG-077 — The KPI strip was a four-column grid holding six readings
**S3** · Layer 9 · **`FIXED`** by `1fbb5d1`, `96cbf35`

It wrapped 4 + 2 with two empty cells, and two readings with no comparison window printed "0%".

### BUG-078 — The map dropped field reports after 72 h and never refreshed warnings
**S3** · Layer 9 · **`FIXED`** by `2ff657b`

The one Patna report was hours from vanishing; expired warnings kept their pins until a reload.
Reports now 7 days like events; the map refetches every 2 min.

### BUG-079 — Dashboard frame: fixed-height maps, a short Recent Events card, a dead "View all"
**S3** · Layer 9 · **`FIXED`** by `e3b21ff`, `6fcd548`, `e6c80d1`, `fb445b0`, `fefbada`

Viewport-relative map heights, the map sets the row's height, India framed for the canvas it has,
"View all" links to `/events`.

### BUG-080 — Reports Trend drew one report as a bell curve, with a 0.5 tick
**S3** · Layer 9 · **`FIXED`** by `5ee85a9`

A monotone spline over 0-0-1-0-0; now linear with dots, whole-number axis, a total, live refresh.

### Not defects

- **"Total Reports" (all time) vs the 7-day trend** (report item 3A): both numbers are right; if the
  card should say "all time", that is its label on the dashboard.
- **The map's default view** (report item 4): frontend only; no backend endpoint serves map defaults.

# Phase 2 — 24 Sep 2026 (branch `aditya_24sep_c`; found while written, since tested and merged)

### BUG-081 — The consumer silently dropped a report the pipeline failed on
**S1** · Layer 2 · **`IN-PROGRESS`** — fix written, not yet run (Phase 2 T8)

`process_report` fails soft and returns `None`, and the consumer auto-committed its offset, so a
report the pipeline crashed on was logged once and never processed again: no retry, no record, and
its docket said `received` for ever. Now offsets are committed by hand after each message; a failure
is retried by seeking back to it, and the third failure publishes it with its error to
`indra.raw.reports.dlq` and moves on. `GET /api/meta/sources` shows the dead-letter count;
`scripts/replay_dlq.py` sends them back once the cause is fixed. `pipeline.take_failure()` tells a
crash from "no event" without making `process_report` raise, which every caller relies on.
Commits: `b40b7d0`, `87c5c5d`, `f73f5c8`, `6e97592`, `84e33d1`. To be marked `FIXED` when the T8
tests in the phase file pass.
**24 Sep: `FIXED`.** The T8 consumer tests pass (retry twice, dead-letter on the third, commit only
after, nothing committed when the dead-letter topic is unreachable), PR #35.

# Phase 3 — 25 Sep 2026 (branch `aditya_25sept`; found while written, since tested and merged)

### BUG-090 — Clustering ran DBSCAN over every unassigned report ever stored
**S2** · Layer 5 · **`IN-PROGRESS`** — fix written, not yet run (Phase 3 T5)

No time window, no locality, no hazard: a week-old report could cluster with today's, a heatwave
with a flood, and the candidate set grew with the table. `cluster_around(report)` pre-filters in
SQL (unassigned, clusterable, same family or untagged, inside the family's window, within 3 × eps)
and runs DBSCAN over that set. Commits `b1d4e52`, `c8e8025`. `FIXED` when T5's cases pass,
including the 10,000-row timing.
**26 Sep: `FIXED`.** T5's table passes (`test_hazard_clustering.py`). With 10,000 old unassigned
reports in the table, `cluster_around` takes a median **7.2 ms** (worst 7.7 ms of 7 runs); the old
whole-table method took **296 ms** on the same rows.

### BUG-091 — Every report's credibility was computed at ingest and read by nothing
**S2** · Layer 6 · **`IN-PROGRESS`** — fix written, not yet run (Phase 3 T8)

Report Density counted reports, so five from one device were five witnesses. It now scores
`n_eff = Σ_distinct reporters min(1, best credibility / 0.60)`, the misleading-text flags lower
credibility, and a news publisher counts once. Commits `2b0131e`, `9a4c91d`, `eefdf69`, `778e301`,
`c8e8025`.
**26 Sep: `FIXED`.** `test_report_flags.py` and the `coordinated` cases pass: five clean citizen
reports count 4.75 witnesses, five from one device 1.0, three devices sending one text 1.5.

### BUG-092 — Every event was stored as `URBAN_FLOOD`
**S2** · Layer 6 · **`IN-PROGRESS`** — fix written, not yet run (Phase 3 T6)

The type was hard-coded at insert. It is now the majority of the reports' tagged hazards, ties by
precedence, UNCLASSIFIED (never auto-published) with no votes; a commander can override it on the
record. Commits `ddeef6e`, `c8e8025`, `36d231b`.
**26 Sep: `FIXED`.** Each of the PS's seven categories makes one event of its own type by a 5–0
vote (`test_hazard_scenarios.py`); UNCLASSIFIED and posts-only events stay with a human even at
0.99 (`test_event_typing.py`).

# Demo-data removal — 25 Sep 2026 (branch `aditya_remove_demo_data`)

Aditya asked for every demo, invented, placeholder and synthetic value to be **removed** from the
application, not switched off, keeping the real feeds, the real datasets and the honestly labelled
test fixtures. A read-only audit of every layer, the dashboard included, found the rows below. Each
is fixed on the branch, one commit per change, unless its status says otherwise; the dashboard's
share is written up for its owners in [`frontend-handover.md`](frontend-handover.md) §19. The tests
are named per row; the whole backend suite and the browser suite are re-run in the testing pass that
follows the code.

### BUG-093 — The dashboard shipped four passwords and signed every visitor in as the commander
**S1** · Layers 8a, 9 · **`FIXED`** by `891b95a`, `252033b`, `b262ec5`, `7da3156` (backend, scripts),
`ee34caa`, `f773acb` (dashboard) · Found by: the 25 Sep audit

`lib/api.ts` carried `DEMO_CREDENTIALS`, the four accounts' passwords, in the browser bundle, and
fetched a token for whichever persona the switcher showed, `commander` by default: anyone who opened
the dashboard could approve or reject events, dispatch teams and file official dispatches. The same
passwords were a dict in `core/security.py`, were printed in `api-contract.md`, the handover and the
smoke test, and `GET /api/profile/me` without a token answered with the commander's profile.
Fix: accounts are `user_profiles` rows with a bcrypt `password_hash` (migration `0019`, nothing
seeded), set per environment with `scripts/set_operator_password.py`; the dashboard signs in and keeps
only the token. `/api/profile/me` is a 401 without one. The old passwords stay in git history, so
every deployed account needs a new one. Tests: `test_login.py`, `test_set_operator_password.py`,
`test_mutation_auth.py`.

### BUG-094 — Invented operators stood in for the real accounts
**S2** · Layers 7, 9 · **`FIXED`** by `9337a65` (migration `0018`), `f773acb`, `217749e`,
`6b48f84`, `3b838fa` (dashboard)

The topbar, sidebar and Profile page showed four invented officers (the commander was "Rajesh K.
Verma") with badges, callsigns, `gov.in` e-mails, a phone number, a bio and a unit, whatever the
account's record said; migration `0008` had seeded invented badge numbers, callsigns and a team role
into the four profiles, and a team with no headcount counted as 12. Fix: the dashboard renders the
signed-in account's own `/api/profile/me` and shows an absent field as absent; `0018` nulls the
seeded placeholders and gives the citizen account agency `PUBLIC`; `POST /api/teams` requires
`members_count`.

### BUG-095 — A constant "Patna Station #04" block shown as live telemetry
**S2** · Layer 9 · **`FIXED`** by `e7810cf`

The settings page and drawer showed 32.4 °C, 68 km/h and 85.5 mm at Patna's coordinates as a
station's output. No such station exists and nothing computed the numbers. Removed; real
observations are the METAR and rainfall layers, and the settings say they live only in this browser.

### BUG-096 — A coordinate that failed validation was moved instead of refused
**S2** · Layers 3, 9 · **`FIXED`** by `1ee01b0` (backend), `4692a47` (dashboard) · Test:
`test_geocoding.py`

With `SNAP_OUT_OF_BOUNDS_COORDINATES=true` the backend moved an out-of-India report to a gazetteer
match or to (22, 82), and a report with no coordinates and no known place in its text was always
answered with (22, 82) as "National Command Grid"; two such reports could cluster there into an event.
The dashboard moved a pin without a usable point to a gazetteer city with jitter, or to (22, 82) as
"National Grid", and drew every citizen report as a Flood of advisory severity. Fix: the setting, the
snap and the fixed point are gone, so such a report is a 422, and the map plots only the coordinates
the API sent, labelling reports as unrated citizen reports.

### BUG-097 — The browser suite wrote "E2E probe" reports into the live `indra_db`
**S2** · Test infrastructure · **`FIXED`** by `6390492` (E2E mode), `4016a72` (`make e2e-backend`),
`8b839ee` (Playwright's guard), `2cb7dbb` · Test: `test_e2e_identity.py`

`e2e/dashboard-live-data.spec.ts` posted its probe to whatever `E2E_API_URL` named, `:8000` by
default, so the probes were stored, published and clustered in the development database; four of
them reached the committed `data/live` snapshot (BUG-099). Fix: `make e2e-backend` runs a backend with
`ENVIRONMENT=e2e` on `indra_e2e`, its own topics, consumer group and Redis db, which refuses to start
otherwise, and Playwright refuses any backend whose `/api/e2e/identity` does not name an `_e2e`
database.

### BUG-098 — AI-generated photographs shown beside real events
**S3** · Layer 9 · **`FIXED`** by `a4817df`

Recent Events illustrated each event with one of seven photos whose C2PA manifests read "Created by
Google Generative AI", with alt text saying they showed the event at its place. Replaced by a hazard
tile (colour and icon) that makes no claim about the place; the photos are deleted.

### BUG-099 — Demo and test rows committed in `data/live/`
**S3** · Layer 7 · **`IN-PROGRESS`** — the exporter is fixed by `047c1e3`, `5f3aa85`; the rows are
not yet deleted from the snapshot

The snapshot held the five Patna reports `run_patna_demo.py` posted on 20 Sep, four Playwright
probes, the event `INDRA-20260920-001` the five formed and its audit row, none marked as test data.
Fix: the exporter no longer claims nothing is seeded and never writes password hashes. Deleting those
rows from the CSVs and `indra_live.db` is the remaining step; this row is `FIXED` with that commit.

### BUG-100 — `DEMO_MODE`, the `DEMO_*` payloads and the demo scripts removed, not switched off
**S3** · Layers 8a, 9, `scripts/` · **`FIXED`** by `2c20b97`, `a32c995`, `ae45bd5`, `02bec4b`,
`a0eac46`, `7351243` · Test: `test_empty_and_unavailable.py`

Off by default since 20 Sep (BUG-024), the fallback still sat one `.env` line away (BUG-045). Deleted:
`DEMO_MODE`, `core/demo.py` and every hardcoded payload behind it (events, distribution, feed, trend,
KPIs, teams), the dashboard's `DEMO_PULSE` type, `run_hazard_demo.py`, `run_patna_demo.py`,
`burst_reports.py`, `seed_national_data.py`, `./start.sh demo` and `make demo`. Every read now answers
no rows with the empty result, an unknown id with 404 and a database error with 503, through
`core/empty.py::empty_or_503()`; a `DEMO_MODE` line left in an old `.env` is ignored.
# Phase 3 testing pass — 26 Sep 2026 (branch `aditya_26sep`)

Numbered from BUG-101, because the unmerged 25 Sep demo-data branch already uses BUG-093 … BUG-100.

### BUG-101 — Merging main dropped PR #39's ML block from a re-typed event's receipt
**S3** · Layer 6 · **`FIXED`** `9919f48`

Phase 3 re-scores an event under a commander's type and rebuilds the receipt; PR #39 added
`ml_event_grouping` only after the first score, so every re-typed event lost it. Now set on both.
Test: `test_a_commanders_type_survives_later_reports`.

### BUG-102 — The tagger missed "bhishan garmi" and "shitlahar", the plan's own spellings
**S3** · Layer 3 · **`FIXED`** `924496d`

The Hinglish regexes matched "bheshan" and "sheet lehar" but not the lexicon's own words. Found
on the fixture; the first measurement (gate passed, macro-F1 0.9913) is kept in `89e66fe`.

### BUG-103 — A rain reading with no depth left the receipt's severity axis blank
**S3** · Layer 6 · **`FIXED`** `758568a`

A RAINFALL event quoting "64.4 mm" showed `axis: water_depth, value: null`. The rain reading is now
the axis shown when no depth is quoted.

### BUG-104 — A commander's type override split the incident into two events
**S2** · Layer 6 · **`FIXED`** `f81cb63`

After a commander re-typed a flood event as FOG, the next flood reports at the same place made a
second URBAN_FLOOD event, because the merge matched only the event's (now visibility) family. The
merge also accepts the family the reports voted (`override.machine_vote`); a heatwave cluster still
never joins a flood event. Tests in `test_hazard_clustering.py`.

### BUG-105 — `sample_real_posts.py` had never run
**S3** · scripts · **`FIXED`** `0349a75`

asyncpg refused `--since` as a string. Parsed to a datetime; the sample was then drawn (100 rows of
2,198, 38 in Hindi).

### BUG-106 — Two of PR #39's tests fail on every Mac and Linux checkout
**S3** · Layer 4 · **`OPEN`**, handed to the ML owner

`test_datasheet_hash_matches_the_file` and `test_committed_metrics_match_the_dataset_file` compare the
raw file's SHA-256 with a CRLF checkout's hash; git stores `data/labelled/reports_v1.csv` as LF. The
only 2 failures in the 1,475-test suite. Fix: hash the LF form, or pin the file's line endings.

### BUG-107 — Phase 2's 24-hour collection had never run
**S2** · infra · **`FIXED`** 27 Sep

The server was stopped at 19:59 on 24 Sep, 18 minutes after the Phase 2 deploy, and stayed off
until 26 Sep. It then ran from 26 Sep 11:38 to 27 Sep 12:08, which collected the first full day:
26 Sep 11:40 → 27 Sep 11:40, 745 headlines, 41 posts, 3,015 METAR observations from 113 stations,
every feed `ok`, and all 786 stream messages in the lake.


# Phase 3 real-post measurement — 27 Sep 2026

Found by measuring the tagger on 100 real posts and headlines (labelled by Claude, see
`backend/tests/fixtures/hazards_real_v1.md`). All `OPEN`: fixing them on the sample they were found
on would make its figure dishonest, so they are to be fixed on the fixture's `dev` rows and measured
on a fresh real sample. BUG-088 (the Vietnamese "लू") is **fixed**: all 5 such items came out untagged.

### BUG-108 — Hindi "आंधी-बारिश" (a rain squall) is tagged a dust storm
**S2** · Layer 3 · **`OPEN`**

The lexicon maps आंधी to DUST_STORM; with rain in a monsoon headline it is a squall (thunderstorm,
strong wind). 8 of the 100 posts; DUST_STORM precision 0.18 on real text.

### BUG-109 — Hindi negation reads "टला नहीं" (hasn't gone) and "में भी नहीं डिगा" as denials
**S3** · Layer 3 · **`OPEN`**

### BUG-110 — "चलेगी लू" (verb first) is not recognised as a heatwave
**S3** · Layer 3 · **`OPEN`**

### BUG-111 — "कोहरे में डूबेगा" (drowned in fog) is tagged a flood
**S3** · Layer 3 · **`OPEN`**

### BUG-112 — Humour posts that only carry #ChennaiRains are tagged rain
**S3** · Layer 3 · **`OPEN`**

7 of the 100 posts. Once posts cluster they can make a posts-only event, which is capped at
`PENDING_HUMAN_REVIEW` and never published, but is noise in the review queue.

**27 Sep, after the fixes:** BUG-108 … BUG-111 are **`FIXED`** (`4c40ed2`) and BUG-112 is fixed
for posts tagged as jokes. Measured on a second, independent 100 real posts (`hazards_real_v2.csv`,
labelled by Claude before measuring): micro-F1 **0.913**, Hindi **0.914** (0.729 on the first sample
before the fixes), DUST_STORM F1 0.95 (0.31 before). What is left:

### BUG-113 — Hashtags name a hazard on posts that are not reports
**S3** · Layer 3 · **`OPEN`**

A haiku tagged #fog, a satire tagged #Heatwave, a motorbike called "Cyclone RX600", a painting tagged
#DelhiRains: 8 of the 100. Most of the 28% of non-hazard posts that get tagged. Bounded: a
posts-only event is never published without a human.

### BUG-114 — More Hindi forms the tagger misses
**S3** · Layer 3 · **`OPEN`**

"लू का वार", "लू की स्थिति" (heatwave); "आंधी-पानी" (पानी as rain); "सड़कों पर भरा पानी" (the verb
before पानी); "80 KM की रफ्तार से चलेंगी हवाएं" (a wind speed in Hindi). 5 of the 100. Also
"flood threat" / "flood concerns" read as a flood (2), and 7 tense misses.

**27 Sep, afternoon (branch `aditya_27sep_b`):** BUG-113 and BUG-114 **`FIXED`** (`d086fee`,
`2ac3d91`, `759cb33`, `221bc07`; tests `d80aaf2`). A hashtag counts only as a word in a sentence or
beside weather words, a reading or a named hazard; a photo's tags and an all-tag post still count;
creative writing names nothing; "Cyclone" before a model code is a product. The Hindi forms above
are read, a threat is a forecast (kept in a forecast, dropped beside something happening now), and
plural colour alerts, "now through" and "caused" set the tense correctly. The fixture is unchanged
(macro-F1 0.9952). On a **third, independent sample** (`hazards_real_v3.csv`, labelled by Claude
before measuring): micro-F1 **0.954**, the same as `main` scores on it, with non-hazard posts tagged
down from 15.4% to 12.8% and Hindi up from 0.940 to 0.949. v3's 16 wrong rows are below, not tuned on.

# Phase 3 third real-post sample — 27 Sep 2026

### BUG-115 — Hindi heat warnings with a word between लू and the alert
**S3** · Layer 3 · **`OPEN`**

"लू का ऑरेंज अलर्ट" and "लू और उमस भरे मौसम की चेतावनी" name no heatwave: the लू companions are word
pairs, so a colour between का and अलर्ट, or "लू और …", is not one. 2 of v3's 100 (both forecasts).

### BUG-116 — A rainfall figure beside only hashtags names nothing (a regression of BUG-113's fix)
**S3** · Layer 3 · **`OPEN`**

"Colaba logged 222mm in just 48 hours … #MumbaiRains #IMDUpdate": "mm" with no rain word within five
tokens is not read as a rainfall reading, so the post has no weather word of its own and the tag
list is dropped. Before the fix it was RAINFALL through the hashtag. 1 of v3's 100.

### BUG-117 — Tense: a year in a hashtag, a date earlier this year, a Hindi future
**S3** · Layer 3 · **`OPEN`**

"#ChennaiFloods2025" makes "Chennai braces for heavy rainfall" a past story; "on April 1st 2026 we
had a huge storm" (September 2026) is read as happening; "जारी रहेगा बारिश का दौर?" (will the rain
go on?) is not a forecast; "IMD warns of … till Tuesday" beside a cyclone that "swirls" now reads as
a forecast. 4 of v3's 100; tense right on 85% of rows.

### BUG-118 — Hazard words that are not the hazard happening
**S3** · Layer 3 · **`OPEN`**

"respite from the sweltering heat" → HEATWAVE; "a 15% rain deficit" → RAINFALL; "cyclonic
circulation" → CYCLONE; "Is rain coming?" → RAINFALL; "नदी में डूबने से मौतें" (drowned in a river)
→ URBAN_FLOOD; preparing "to deal with flash floods" → URBAN_FLOOD; and wind damage written verb
first ("तेज आंधी से गिरा … होर्डिंग", "आंधी से बिजली का तार गिरा") is missed as STRONG_WIND. 8 of v3's
100. Like BUG-113, these reach only a commander's review queue: a posts-only event is never
published without a human.

### BUG-120 — The team server signed its tokens with the key published in the source
**S1** · Layers 8a, infra · **`FIXED`**: in code, and the server's key rotated 27 Sep, 18:30 IST · Found by:
checking the server before deploying the sign-in (27 Sep, read-only: the value was compared, never
printed)

The server's `.env` had `SECRET_KEY` equal to the default in `core/config.py` and `.env.example`, so
anyone who had read the repository could sign a commander's or an admin's token and use the public
API without a password. Operator passwords (BUG-093) do not help while the signing key is public.
Fix: `Settings` refuses, with `ENVIRONMENT=production`, the published key or any key under 32
characters, and the backend does not start (`test_secret_key.py`). **Before deploying this, rotate
the server's key**; rotating it ends every session, and the dashboard fetches a new token.

### BUG-121 — SACHET warnings were collected and read by no scoring code
**S2** · Layer 6 · **`FIXED`** on `aditya_27sep_phase4`, tested 27 Sep, merged to `main` (PR #47)
(`test_official_warnings.py`, `test_late_corroboration.py`)

Every IMD, CWC and SDMA warning has been stored with its polygon since 21 Sep, and the confidence
receipt never read one: a flood inside an IMD warning scored exactly as one outside it. Phase 4
adds the `official_warning` factor (receipt v2, 10%): warnings in force that cover the event and
match its hazard family, scored on the agency's own CAP severity, offline when SACHET is stale. A
warning stored after an event re-scores it (`LATE_CORROBORATION`).

### BUG-122 — The weather factor read only rainfall, so nothing could contradict a fabricated claim
**S2** · Layers 1, 6 · **`FIXED`** on `aditya_27sep_phase4`, tested 27 Sep, merged to `main` (PR #47)
(`test_evidence.py`, `test_verification_pipeline.py`, the verification demo live and `--frozen`)

A heatwave, fog, dust-storm or gale event had no weather evidence for or against it, and the
airport observations collected since Phase 2 were read by nothing. Phase 4 reads each hazard's own
variable (Open-Meteo, and an airport's METAR within 50 km where it measured) and records a
contradiction, from a published table, only when the evidence affirmatively says the opposite:
the event is then CONTRADICTED and held for a human, never rejected automatically.

# Phase 5 code phase — 28 Sep 2026

### BUG-123 — A withdrawn report's text stays in the lake's raw copy of the report stream
**S3** · Layer 7 · **`OPEN`** · Found by: writing the withdrawal (Phase 5 T5), 28 Sep

`DELETE /api/reports/{docket}` redacts the report's row and the outbox copy of its message, deletes
its media, and takes it out of its event. The lake archiver (Phase 2 T9) has already written the
message as published, text and coordinates included, into a batched gzipped object in `indra-lake`,
and nothing rewrites those. Expected: a withdrawal removes the text everywhere INDRA keeps it.
Fix options: rewrite the affected lake objects from a withdrawal queue, or keep the lake's report
stream for a bounded time. Until then the withdrawal's own docstring and the privacy notes say so.

### BUG-124 — `GET /api/reports/recent` is open and returns citizen report text and exact coordinates
**S2** · Layer 8a · **`OPEN`** · Found by: the citizen website plan (`webpage.MD` §13), 27 Sep; recorded 28 Sep

The Field Reports layer is fed by an unauthenticated route that returns each citizen report's text
(first 300 characters) and GPS position. Tolerable while the only reports were the team's own test
submissions; not once real citizens report from the public site. Phase 5 keeps media URLs out of it
(ids only) but does not change the text or the coordinates, because the dashboard reads them without
a token. Needs a decision with the frontend owner before the citizen site goes live: put the route
behind sign-in (the dashboard already has a session) or coarsen what it returns to anyone.
