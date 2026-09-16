# Backend TODO — `INDRA/backend`

Aditya's actionable backlog, backend-only, organised as a **5-day sprint: 16–20 Sep 2026**, at the end of which the backend has to be demo-complete.

Each day has its own detailed file with per-task test parameters. This file is the map; the day files are the work.

> ### ⚠ Blocking: Day 1 is written but unmerged
>
> Day 1's work sits on **six pushed, unmerged branches** — `aditya_16sep-test-harness`,
> `aditya_16sep-fix-event-detail`, `aditya_16sep-geo-clustering`, `aditya_16sep-service-tests`,
> `aditya_16sep-pipeline`, `aditya_16sep-consumer-wiring`. Neither `aditya_16sep` nor `main`
> has any of it.
>
> **Everything below assumes the merged state.** Day 2 cannot start against a checkout that
> lacks `pipeline.py`, so merging is Day 2's first task (T0). Merge order:
> `test-harness` → (`fix-event-detail`, `service-tests` in any order) → `geo-clustering` →
> `pipeline` → `consumer-wiring`. The order is not cosmetic: pipeline calls clustering's new
> `get_cluster_stats()` / `assign_reports_to_event()`, the consumer imports pipeline, and every
> test branch needs the harness's `conftest.py`.

## How the sprint maps onto the 9-layer architecture

The team's canonical SIH26069 diagram has nine layers (full status ledger in
`backend-architecture.md`). Each sprint day targets specific layers — useful when deciding
what to cut if a day runs short, since cutting a day leaves a visible hole in a named layer.

| Day | Layers touched | What changes in the architecture |
|---|---|---|
| 1 ✅ | 2, 5, 6 | Ingestion → geo-analytics → fusion becomes one connected spine. **The layer-6 box stops being aspirational.** |
| 2 | 3, 4, 6 | Layer 6's confidence numbers become real measurements; layer 3's coordinate defect is closed. Layer 4 stays mostly ⬜ **by choice** — honest "offline" markers beat invented scores. |
| 3 | 6, 7, 8a | Audit writers make layer 7's `audit_logs` real; the review endpoint and RBAC make layer 8a's human-in-the-loop claim true. |
| 4 | 2, 7, 8a | Real `/healthz`, the `KAFKA_EVENTS_TOPIC` producer (completing layer 2's outbound half), reprocess endpoint. |
| 5 | all | Hardening and rehearsal; no new layer work. |
| — | **8b Alert Engine** | **Not scheduled in this sprint at all.** It is entirely unbuilt and stays that way — say so plainly rather than implying otherwise. |
| — | **1 external feeds** | Not scheduled beyond a Day 4 in/out-of-scope decision. No API is polled today. |

| Day | Date | Theme | Detail file | Status |
|---|---|---|---|---|
| 1 | 16 Sep | Verify the stack, build the test net, **wire the pipeline** | `aditya_16-sep.md` | ✅ complete |
| 2 | 17 Sep | Replace random scores with real signals | `aditya_17-sep.md` (write at end of Day 1) | planned |
| 3 | 18 Sep | Audit trail, human-review endpoint, enforce RBAC | `aditya_18-sep.md` | planned |
| 4 | 19 Sep | Real `/healthz`, events topic, ops endpoints, integration suite | `aditya_19-sep.md` | planned |
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

## Day 2 — 17 Sep · Replace random scoring with real signals

The pipeline existing is worth little if the number it produces is `random.uniform(0.70, 0.95)`. This is the day the confidence score becomes defensible.

> **T0 — Merge the six Day-1 branches before anything else.** Nothing in this day's list is
> possible against a checkout without `pipeline.py`. Merge in dependency order
> (`test-harness` → `fix-event-detail` / `service-tests` → `geo-clustering` → `pipeline` →
> `consumer-wiring`), then confirm the baseline: `.venv/bin/pytest -q` must report **71
> passed** before any Day 2 edit. If the count differs, stop and reconcile — a merge that
> silently drops tests is worse than an unmerged branch.

> **Carried in from Day 1 — do these first, they are correctness issues, not tuning:**
>
> - [ ] **Reject out-of-India coordinates instead of snapping them to `(22, 82)`.**
>   `sanitize_coordinates()` currently stores Paris as India's centroid. With
>   `DBSCAN_MIN_SAMPLES=2`, two junk or GPS-glitched reports cluster there and manufacture a
>   fake event. **Highest demo risk on the board.**
> - [ ] **Decide what the empty-result demo fallbacks should do.** `events.py:259`,
>   `feed.py:90`, `teams.py:307` use `if rows:` and fall through to demo data with no
>   warning, so an empty database looks fully populated. Gate behind an explicit
>   `DEMO_MODE` setting, or log loudly — but make it a deliberate choice.
> - [ ] **Make `reports.py` publish the same coordinates it stores.** It stores sanitised
>   `valid_lat`/`valid_lng` but publishes raw `report.latitude`/`longitude`, and keys the
>   text as `text` rather than `raw_text`. `pipeline.py` re-reads from Postgres to work
>   around this; fix it at source and simplify the pipeline.
> - [ ] **Lower `COSINE_THRESHOLD` from 0.88.** Measured: same-event paraphrase 0.815,
>   distinct reports 0.519, unrelated 0.136 — so 0.88 catches only near-identical text.
>   ~0.75–0.80 separates them properly. Evidence lives in
>   `tests/test_dedup.py::test_embeddings_separate_paraphrase_from_unrelated`, and
>   `test_paraphrase_is_NOT_caught_at_the_current_088_threshold` will flip when you change it.

- [ ] `report_density` — from the real count of deduplicated reports in the cluster (`get_cluster_stats().count`), normalised on a documented curve (e.g. saturating at 25 reports). Write down the curve; a judge will ask why 25. **Partly done Day 1** — `pipeline._density_score()` saturates at 10; decide whether 10 or 25 is the defensible number and document it.
- [ ] `spatial_coherence` — from real DBSCAN cluster tightness (`max_pairwise_km` vs `DBSCAN_EPS_KM`). Tighter cluster → higher score. **Partly done Day 1** — `pipeline._coherence_score()` scores against the `2*eps` span; review the curve.
- [ ] `source_reliability` — from `SourceType`: official (CWC/IMD gauge, dispatch) > verified app user > anonymous > social. A static lookup table is fine and honest; document it.
- [ ] `weather_station` — read from `station_readings`; if the table is empty, decide between (a) a real Open-Meteo fetch or (b) passing `None` so `compute_receipt()` marks it "Telemetry factor offline". **(b) is an acceptable answer** and is better than faking it.
- [ ] `vision_analysis` — pass `None` (→ "Telemetry factor offline") unless a real classifier ships. **Do not fake this one**; it's the factor a technical judge is most likely to probe.
- [ ] `anomaly_detection` — same call: real signal or explicit offline.
- [ ] Replace the hardcoded `credibility_score = 0.5` in `reports.py:121` with something computed (source type + text length/quality heuristics), or make it explicitly a documented default.
- [ ] Delete `generate_heuristic_scores()` once nothing calls it, or rename it to something honest and confine it to the demo path.
- [ ] Align dedup constants: `GPS_DELTA_KM` / `TIME_DELTA_MINUTES` are hardcoded in `dedup.py` while clustering reads its constants from `get_settings()`. Move dedup's to settings for consistency.
- [ ] Consider switching the DBSCAN eps conversion from `eps_km * 0.009` (degrees-at-equator, ~10% off at Patna's latitude) to a `geography`-based distance.

**Testing parameters**
- Each factor gets a unit test with a known input → known output, no randomness anywhere.
- Determinism test: run the pipeline twice over an identical seeded fixture → **byte-identical `confidence_score`.** This single test is what proves the scoring stopped being random, and it's the one to show a judge.
- Monotonicity tests: 10 reports must score higher `report_density` than 3; a 1 km-wide cluster must score higher `spatial_coherence` than a 4 km-wide one.
- Offline-factor test: with `vision_analysis=None`, the receipt shows `score: 0.0` / `"Telemetry factor offline"` and the confidence drops by exactly 0.15 relative to the same event with `vision_analysis=1.0`.

---

## Day 3 — 18 Sep · Audit trail, human review, RBAC enforcement

Three claims the docs make that the code currently doesn't back.

- [ ] **Write audit logs.** `audit_logs` has zero writers today. Add an `AuditService.record(event_id, operator_id, action, reason)` that computes the `sha256_hash` — decide and document what the hash covers (a chain over the previous row's hash is the claim the docs make; a hash of the row's own content is weaker but honest). Call it on: report ingested, event auto-published, event manually reviewed.
- [x] ~~Confirm the BEFORE UPDATE OR DELETE immutability trigger actually exists.~~ **Done Day 1 (T3)** — `trg_audit_immutable` exists (`0001_initial.py:93-107`) and was verified live to reject both UPDATE and DELETE while allowing INSERT. No migration needed.
- [ ] **Add `PATCH /api/events/{event_id}/review`** — accepts `action` (`approve` / `reject` / `override_severity`), optional `new_severity`, and `reason`. Updates `review_status`, writes an audit log, broadcasts the change over `/ws/events`.
- [ ] **Add `GET /api/events/{event_id}/provenance`** — returns the audit chain plus the contributing raw reports, matching the "click to see where this came from" UX the docs describe.
- [ ] **Enforce auth.** `require_roles()` and `get_current_operator()` exist in `core/security.py` and guard **nothing**. Put `require_roles("COMMANDER", "ADMIN")` on the review endpoint at minimum. Decide per-endpoint what else needs gating — and **check with the frontend owner before gating any endpoint the dashboard already calls unauthenticated**, since that would break their fetches.

**Testing parameters**
- Review endpoint: approve a `PENDING_HUMAN_REVIEW` event → status becomes `AUTO_PUBLISHED`(or a distinct `HUMAN_APPROVED`), exactly 1 new `audit_logs` row, WebSocket message emitted.
- Reject → status `REJECTED`, and the event disappears from `GET /api/events` (that router already excludes `REJECTED`).
- Auth: no token → **401**; `analyst` token on a commander-only endpoint → **403**; `commander` token → **200**. All three asserted.
- Audit immutability: attempt `UPDATE audit_logs SET reason='x'` → must raise. Attempt `DELETE` → must raise.
- Hash chain: insert 3 audit rows, verify each row's hash recomputes correctly from its inputs; tamper with row 2's content in a copy and verify the chain check detects it.
- Provenance: an event built from 5 reports returns all 5 report IDs plus its audit entries.

---

## Day 4 — 19 Sep · Ops honesty and the integration suite

- [ ] **Make `/healthz` real.** It currently returns hardcoded `"connected"`/`"active"` for database/redis/streaming_bus regardless of truth. Ping Postgres (`SELECT 1`), ping Redis, and reuse the existing `check_kafka_connection()` from `report_consumer.py`. Return `503` when a dependency is down.
- [ ] **Produce to `KAFKA_EVENTS_TOPIC`** (`indra.verified.events`) when the pipeline creates an event — it's configured in `.env` and nothing writes to it, so the documented "Kafka in and out" flow is currently half-true.
- [ ] **Add `POST /api/events/reprocess`** (admin-gated) to re-run the pipeline over reports in a time window — needed for ops and for recovering a demo if something goes wrong live.
- [ ] Build out the integration suite: everything marked `@pytest.mark.integration` runs green against the real stack in one command.
- [ ] Add a `make test` / `make test-integration` target so the team can run it without knowing the incantation.
- [ ] Decide and write down whether Open-Meteo / OpenWeather / IMD / Twitter integrations are in scope. All four keys are blank in `.env` and nothing consumes them. If out of scope, say so somewhere visible so the README stops implying they're live.

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

- **Frontend is off-limits.** Day 1 introduces a new `VERIFIED_EVENT` WebSocket message type; Day 3 may add gated endpoints. Both need a written handover to the frontend owner, not an edit to `frontend/`.
- **MinIO/S3 in `docker-compose.yml`** is an infra decision — raise it, don't add it unilaterally.
- **Out of scope for the whole sprint:** ClickHouse, Iceberg, Kubernetes, real CV/NLP models. A wired pipeline with honest heuristics and a real audit trail beats an unwired pipeline with one impressive disconnected model.
- **The Alert Engine (architecture layer 8b) is not being built.** No SMS, email, or dispatch
  integration is scheduled on any day. It appears in the canonical diagram and in the README's
  Scene 10, so **the gap has to be stated out loud** rather than left to be discovered — the
  WebSocket push to the dashboard is real and is the honest version of that scene.
- **No external feed is polled (architecture layer 1).** Open-Meteo, OpenWeather, IMD and
  Twitter keys all sit unread in `.env`, and there is no HTTP client in `app/` at all. Day 4
  carries the in/out-of-scope decision; until then, do not let a doc or a slide imply these
  are live.
- **Redis is running but unused.** Until something connects to it, the backend must run
  single-process — WebSocket fan-out is an in-process list, so a second worker silently drops
  events for half the clients.
