# Backend TODO — `INDRA/backend`

Aditya's actionable backlog, backend-only, organised as a **5-day sprint: 16–20 Sep 2026**, at the end of which the backend has to be demo-complete.

Each day has its own detailed file with per-task test parameters. This file is the map; the day files are the work.

> ### Where the code is (16 Sep evening, end of Day 3)
>
> Day 1 is merged to `main` (PRs #4–#9, 71 tests). Day 2 is on `aditya_17sep`, **PR #14 open**
> (219 passed, 2 skipped). Day 3 is on `aditya_18sep`, stacked on Day 2, **PR #15 open**
> (287 passed, 2 skipped, 1 xfailed; needs `alembic upgrade head` for migration `0003`).
> Merge #14 before #15.

## How the sprint maps onto the 9-layer architecture

The team's canonical SIH26069 diagram has nine layers (full status ledger in
`backend-architecture.md`). Each sprint day targets specific layers — useful when deciding
what to cut if a day runs short, since cutting a day leaves a visible hole in a named layer.

| Day | Layers touched | What changes in the architecture |
|---|---|---|
| 1 ✅ | 2, 5, 6 | Ingestion → geo-analytics → fusion becomes one connected spine. **The layer-6 box stops being aspirational.** |
| 2 ✅ | 1, 3, 4, 6 | Layer 6's confidence numbers are real measurements; layer 3's coordinate defect is closed. Layer 1 gains its first external read (Open-Meteo). Layer 4 stays ⬜ **by choice**: vision/anomaly are explicitly offline. |
| 3 ✅ | 6, 7, 8a | Audit writers make layer 7's `audit_logs` real; the review endpoint and RBAC make layer 8a's human-in-the-loop claim true. |
| 4 | 2, 3, 7, 8a | Duplicate-absorption fix (layer 3), real `/healthz`, the `KAFKA_EVENTS_TOPIC` producer (completing layer 2's outbound half), reprocess endpoint. |
| 5 | all | Hardening and rehearsal; no new layer work. |
| — | **8b Alert Engine** | **Not scheduled in this sprint at all.** It is entirely unbuilt and stays that way — say so plainly rather than implying otherwise. |
| — | **1 external feeds** | Open-Meteo is live since Day 2 (fetched per event, not polled). The rest wait on a Day 4 in/out-of-scope decision. |

| Day | Date | Theme | Detail file | Status |
|---|---|---|---|---|
| 1 | 16 Sep | Verify the stack, build the test net, **wire the pipeline** | `aditya_16-sep.md` | ✅ complete |
| 2 | 17 Sep | Replace random scores with real signals | `aditya_17-sep.md` | ✅ complete (PR #14 open) |
| 3 | 18 Sep | Audit trail, human-review endpoint, enforce RBAC | `aditya_18-sep.md` | ✅ complete, done early on 16 Sep (PR #15 open) |
| 4 | 19 Sep | Duplicate-absorption fix, real `/healthz`, events topic, ops endpoints | `aditya_19-sep.md` | next |
| 5 | 20 Sep | Hardening, demo rehearsal, failure drills, docs sync | `aditya_20-sep.md` | planned |

Writing tomorrow's day file is the last task of each day, so it's informed by what actually happened rather than by this plan's guesses.

---

## Day 1 — 16 Sep · Wire the real pipeline

Full task list with test parameters: **`aditya_16-sep.md`**. Summary:

- [x] T1 Docker infra up (postgres/redis/redpanda), PostGIS confirmed. *(Blocker was an unmounted external SSD, not a missing install.)*
- [x] T2 venv + deps + add `pytest`, `pytest-asyncio` to `requirements.txt`. *(sentence-transformers loads — embedding path is live.)*
- [x] T3 `alembic upgrade head`; verify tables, 3 GIST indexes, 6 enum types, audit trigger. *(Trigger exists and was verified to block UPDATE/DELETE.)*
- [x] T4 Smoke-test every read endpoint. *(All clean; found and fixed a real bug in `GET /api/events/{id}`.)*
- [x] T5 Prove `POST /api/reports/submit` writes to Postgres *and* Kafka. *(Both, no warnings.)*
- [x] T6 Create `tests/` + `conftest.py` + `integration` marker.
- [x] T7 Unit-test `FusionEngine` — 26 tests.
- [x] T8 Unit-test `DedupService` — 17 tests. *(Found the 0.88 cosine threshold misses paraphrases.)*
- [x] T9 Make `GeoClusteringService` return and persist cluster assignments; add `get_cluster_stats()`. — 9 tests.
- [x] T10 Build `app/services/pipeline.py::process_report()`. — 15 tests. *(Added event merging.)*
- [x] T11 Wire `report_consumer.py` to call it; broadcast `VERIFIED_EVENT`.
- [x] T12 **End-to-end: 6 seeded reports → 1 verified event → WebSocket.** ✅
- [x] T13 Update these notes to match reality.

**Exit criterion: MET.** A report submitted over HTTP produces a real `verified_events` row
with a computed 6-factor receipt, visible in `GET /api/events` and broadcast over
`/ws/events`. 71 tests passing (43 unit, 28 integration).

---

## Day 2 — 17 Sep · Replace random scoring with real signals ✅

Full task list, test parameters and the end-of-day report: **`aditya_17-sep.md`**. Summary:

- [x] T0 Day 1 branches merged (already done via PRs #4–#9); 71 passed on `main`.
- [x] T1 **Out-of-India coordinates → 422, never stored.** Worse than recorded: snapping also
  used any gazetteer city named in the text (Paris coords + "Patna" were stored in Patna).
- [x] T2 Kafka message publishes the stored coordinates, `raw_text`, `h3_res8`, `credibility_score`.
- [x] T3 `DEMO_MODE` gate (`core/demo.py`): demo data only when enabled, `[]`/404 on no rows,
  503 on DB error, always a WARNING.
- [x] T4 Density curve saturating at **25** (0.80 at 10); coherence as a raised cosine over 2·eps.
- [x] T5 `SOURCE_RELIABILITY` table, max over the cluster.
- [x] T6 **Real Open-Meteo fetch** mapped onto IMD rainfall categories, cached per H3 cell;
  any failure → offline.
- [x] T7 Vision and anomaly explicitly offline; `generate_heuristic_scores()` deleted.
  `grep -rn random app/services/` is clean.
- [x] T8 `credibility_score` computed (source prior × text quality), not 0.5.
- [x] T9 Determinism: identical receipt twice, in-process and through the pipeline against Postgres.
- [x] T10 Notes updated; `aditya_18-sep.md` written.
- [x] *Found and fixed:* **`.env` was never read.** `env_file` resolved against the working
  directory (`backend/`); `.env` is at the repo root.

**Exit criteria: all 4 met.** 219 passed, 2 skipped. Live e2e: Paris 422 ×2, 6 reports → 1
event, 5 linked, confidence **0.4336 → `QUARANTINED`**.

**Carried forward, deliberately not done on Day 2:**
- [ ] Lower `COSINE_THRESHOLD` from 0.88 (paraphrase 0.815, distinct 0.519). Change it on its
  own day so a dedup change isn't confused with a scoring change. → Day 5.
- [ ] Move `dedup.py`'s `GPS_DELTA_KM` / `TIME_DELTA_MINUTES` to settings. → Day 5.
- [ ] DBSCAN eps in degrees (`eps_km * 0.009`, ~10% off at Patna) → geography. → Day 5.
- [ ] `GET /api/dashboard/summary` still serves demo KPIs on DB error regardless of `DEMO_MODE`. → Day 5.

**The decision Day 2 surfaced:** the maximum possible confidence is now **0.80** (vision and
anomaly offline), so nothing auto-publishes and citizen-only events mostly land in
`QUARANTINED`. That is honest. The demo story becomes "quarantined → a human reviews it", which is
exactly what Day 3 builds. Re-normalising over online factors stays a Day 5 option.

---

## Day 3 — 18 Sep · Audit trail, human review, RBAC enforcement

**✅ Done (16 Sep evening). Report in `aditya_18-sep.md`.** All four exit criteria met; live
e2e: quarantined → approved → still `HUMAN_APPROVED` after a new corroborating report.
Deviations from the list below: the review writes `HUMAN_APPROVE`/`HUMAN_REJECT` (not
`MANUAL_OVERRIDE`, which is kept for severity overrides); provenance requires
analyst/commander/admin (not "any authenticated role" — citizens can't read others' raw
reports). Found: suppressed duplicates are later counted as corroboration → Day 4.

Full task list with test parameters: **`aditya_18-sep.md`**. Re-checked against the code at
the end of Day 2; several items changed shape:

- [x] **Decide the status/action vocabulary first (T1).** `ReviewStatus` has no human-approved
  value. Approving to `AUTO_PUBLISHED` would claim a machine decided. `AuditAction` is
  `AUTO_VERIFY / MANUAL_OVERRIDE / QUARANTINE / ESCALATE`, with no approve or reject. Likely a
  migration `0003` adding `HUMAN_APPROVED` (Postgres 16: `ALTER TYPE … ADD VALUE` is fine
  inside a migration, but the new value can't be used in the same transaction).
- [x] **`AuditService` with a real hash chain.** `sha256(prev_hash ‖ canonical row fields)`,
  appended under `pg_advisory_xact_lock` so two concurrent writers can't fork the chain.
  `logged_at` must be set by the app (not `NOW()` server default), or the hash can't be
  recomputed. The immutability trigger already exists (verified Day 1).
- [x] **Pipeline writes audit rows**: on event creation (`AUTO_VERIFY` / `ESCALATE` /
  `QUARANTINE` by status) and on a merge that *changes* status. **Not** one row per ingested
  report: that would flood the chain with no decision in it.
- [x] **Stop merges overwriting human decisions.** Today the merge `UPDATE` recomputes
  `review_status`. Once reviews exist, a human-approved or human-rejected event must keep its
  status; the score and receipt may still update. **Must ship with the review endpoint.**
- [x] **`PATCH /api/events/{id}/review`**: `approve` / `reject` / `override_severity` + required
  `reason`. Reviewable from `QUARANTINED` *and* `PENDING_HUMAN_REVIEW` (Day 2's scores put
  nearly everything in `QUARANTINED`). Writes `MANUAL_OVERRIDE` audit, broadcasts a new
  `EVENT_REVIEWED` WebSocket message.
- [x] **`GET /api/events/{id}/provenance`**: contributing reports + the event's audit chain +
  a chain-verification result.
- [x] **Enforce auth on the new endpoints only.** The frontend never calls `/api/auth/token`, so
  it holds no token. Gating anything it already calls (events, feed, teams, profile, dashboard)
  would break the dashboard. Review: `COMMANDER`/`ADMIN`. Provenance: any authenticated role.
  Write the handover proposing which existing endpoints to gate later.
- [x] Reconcile `security.py::ROLES` (4) with `OperatorRole` (5, adds `FIELD_RESPONDER`).

**Testing parameters**: see `aditya_18-sep.md`. The headline ones:
- approve a `QUARANTINED` event as `commander` → 200, status `HUMAN_APPROVED`, exactly 1 new
  audit row, 1 `EVENT_REVIEWED` WebSocket message.
- no token → 401; `analyst` → 403; `commander` → 200.
- approve, then merge a new corroborating report into the event → status **stays**
  `HUMAN_APPROVED`, `confidence_score` rises.
- tamper with a copied row → chain verification fails at exactly that row.

---

## Day 4 — 19 Sep · Ops honesty and the integration suite

- [ ] **Fix first: suppressed duplicates are counted later (found Day 3 e2e).** Dedup leaves
  the duplicate unassigned, DBSCAN clusters it with the next report, and it's merged into the
  event (live: 6 distinct reports → `report_count` 7). Remove the strict xfail on
  `test_pipeline.py::test_suppressed_duplicate_is_not_absorbed_by_a_later_report` when fixed.
- [ ] **Make `/healthz` real.** It currently returns hardcoded `"connected"`/`"active"` for database/redis/streaming_bus regardless of truth. Ping Postgres (`SELECT 1`), ping Redis, and reuse the existing `check_kafka_connection()` from `report_consumer.py`. Return `503` when a dependency is down.
- [ ] **Produce to `KAFKA_EVENTS_TOPIC`** (`indra.verified.events`) when the pipeline creates an event — it's configured in `.env` and nothing writes to it, so the documented "Kafka in and out" flow is currently half-true.
- [ ] **Add `POST /api/events/reprocess`** (admin-gated) to re-run the pipeline over reports in a time window — needed for ops and for recovering a demo if something goes wrong live.
- [x] ~~Build out the integration suite~~ — effectively done: `pytest -m integration` runs 97 + 1 xfail green in one command (Day 3). Remaining: a separate test database so the suite stops wiping the dev DB and its audit ledger.
- [ ] Add a `make test` / `make test-integration` target so the team can run it without knowing the incantation.
- [ ] Decide and write down whether OpenWeather / IMD / Twitter integrations are in scope. **Open-Meteo is decided and live since Day 2** (per-event fetch in `services/weather.py`); the other three keys are read by nothing. If out of scope, say so somewhere visible so the README stops implying they're live.

**Testing parameters**
- `/healthz` with all services up → `200`, three `"connected"` values that were actually checked.
- `/healthz` with Postgres stopped (`docker compose stop postgres`) → `503`, `"database": "down"`, and **the endpoint still answers within 5s** (a health check that hangs is worse than one that lies).
- Same drill for Redis and Redpanda individually.
- Events topic: `rpk topic consume indra.verified.events` receives a message within 5s of the pipeline creating an event.
- Reprocess: seed 10 reports with `event_id IS NULL`, call the endpoint, assert events are created and no duplicates appear on a second call.
- Full suite: `pytest` green, and note the total runtime — if it exceeds ~2 min it won't get run.

---

## Day 5 — 20 Sep · Hardening and demo rehearsal

- [ ] **Full rehearsal, twice**, from `docker compose down -v` (empty volumes) to a verified event on screen. Time it. Anything that needs a manual fix mid-run is a bug, not a quirk.
- [ ] **Failure drills:** kill Postgres mid-demo, kill Redpanda mid-demo, submit garbage input, submit 100 reports at once. The system should degrade visibly and recover, not crash.
- [ ] Warm the sentence-transformers model at startup if first-call latency is bad (Day 1 T12 measures this).
- [ ] Verify `/api/demo/trigger` still works as the explicit network-failure fallback, and be able to explain in one sentence how it differs from the live path. Now that the live path works, the canned scenario is a legitimate failsafe rather than the only thing that works.
- [ ] Tighten `CORS allow_origins=["*"]` in `main.py` if the demo setup allows it.
- [ ] Final sync of `backend-status.md`, `backend-architecture.md`, `api-requirements.md` against the shipped code.
- [ ] Write the "what a judge will ask, and the answer" list: how is confidence computed, what stops a false alarm, what happens if a source lies, what's real vs. deferred. **Be straightforwardly honest about what's deferred** — a clear "vision analysis is not wired, the receipt says so explicitly" is stronger than a vague claim that collapses under one follow-up question.
- [ ] Buffer for the Day 1–4 items that inevitably slip.

**Testing parameters**
- Cold start to verified event: **under 5 minutes**, zero manual intervention.
- 100-report burst: all ingested, consumer stays alive, no connection-pool exhaustion (`pg_stat_activity` stable), memory flat.
- Kill-Postgres drill: API returns degraded responses rather than 500s; recovers within 30s of restart without a backend restart.
- Every endpoint in `api-requirements.md` responds as documented — walk the list literally.

---

## Standing constraints

- **Frontend is off-limits.** Day 1 introduced the `VERIFIED_EVENT` WebSocket message type; Day 3 added the gated review/provenance endpoints and `EVENT_REVIEWED`. Both need a written handover to the frontend owner, not an edit to `frontend/`.
- **MinIO/S3 in `docker-compose.yml`** is an infra decision — raise it, don't add it unilaterally.
- **Out of scope for the whole sprint:** ClickHouse, Iceberg, Kubernetes, real CV/NLP models. A wired pipeline with honest heuristics and a real audit trail beats an unwired pipeline with one impressive disconnected model.
- **The Alert Engine (architecture layer 8b) is not being built.** No SMS, email, or dispatch
  integration is scheduled on any day. It appears in the canonical diagram and in the README's
  Scene 10, so **the gap has to be stated out loud** rather than left to be discovered — the
  WebSocket push to the dashboard is real and is the honest version of that scene.
- **No external feed is polled on a schedule (architecture layer 1).** Since Day 2,
  Open-Meteo rainfall is fetched per event for the weather factor (`services/weather.py`).
  OpenWeather, IMD and Twitter keys sit unread in `.env`. Day 4 carries the in/out-of-scope
  decision; until then, do not let a doc or a slide imply those are live.
- **Redis is running but unused.** Until something connects to it, the backend must run
  single-process — WebSocket fan-out is an in-process list, so a second worker silently drops
  events for half the clients.
