# INDRA Backend — Daily Report, 18 Sep 2026

18 Sep 2026 · Aditya

Day 4 of the backend sprint is mostly done: verified events now publish to Kafka, and PR #20 (12 commits, 372 tests passing) is open and mergeable. The reprocess endpoint and the external-feeds scope decision remain.

## Done today

The outbound half of layer 2 (ingestion) now exists: every event the pipeline creates or updates is published to `indra.verified.events`.

| Item | Result | Evidence |
| --- | --- | --- |
| Publish verified events to Kafka | New `services/event_publisher.py`, called by the report consumer right after the `VERIFIED_EVENT` WebSocket broadcast. Same payload as the WebSocket message, keyed by event id so an event and its merges stay in order. | Commit `426dc6d` |
| Failure handling | A broker error or a hang past 5 s is logged and skipped; the event is already stored in Postgres, so the consumer never stalls. | 6 new unit tests with a fake broker |
| Full test suite | 372 passed, 2 skipped (was 366 + 2 skipped). No regressions. | `pytest -q` from `backend/` |
| Live check on Redpanda | Test event published and read back with `rpk` in 0.25 s (target: under 5 s). Topic auto-created on first write. | `rpk topic consume indra.verified.events` |
| PR #20 opened | All Day 4 work in one PR against `main`. | [PR #20](https://github.com/SabaSaiid/INDRA/pull/20) |
| Server tooling | GitHub CLI installed and signed in; shortcuts for running tests, restarting the API, status checks and syncing with `main`. | — |

No frontend files were touched and no API or WebSocket message changed shape, so no frontend handover is needed.

## Day 4 checklist

Five of eight Day 4 tasks are done; the reprocess endpoint, the scope decision and the docs update remain.

| Task | Status | Note |
| --- | --- | --- |
| Suppressed duplicates never count as corroboration | Done | Commit `861f4cd`. The Day 3 bug (6 reports shown as 7) is fixed; its strict xfail test now passes. |
| `/healthz` checks dependencies for real | Done | Commit `dfa3eb9`. Postgres or Kafka down → 503; Redis or Open-Meteo down → 200 `degraded`. |
| Publish to `indra.verified.events` | Done | Done today, commit `426dc6d`. |
| Separate test database | Done | Commit `96bcb69`. The suite runs against `indra_test` and can no longer wipe dev data. |
| `make test` / `make test-integration` | Done | Targets exist, but on the EC2 server they look for `backend/.venv` while the venv is `/opt/indra/.venv`. |
| `POST /api/events/reprocess` (admin only) | Not started | Will reuse the new event publisher. |
| Scope of OpenWeather, IMD and Twitter feeds | Decision needed | Their keys are in `.env` but no code reads them. Open-Meteo is the only live feed. |
| Update `backend-todo.md` and `backend-architecture.md` | Not started | Checkboxes and two warnings (duplicates, submit 202) are out of date. |

Also in this sprint day, beyond the plan: submit returns 503 when a report is not stored, no `NEW_REPORT` re-broadcast on Kafka re-delivery, a labelled dataset (300 reports), an offline event-type classifier, and text cleaning with metadata extraction.

## PR #20

[PR #20](https://github.com/SabaSaiid/INDRA/pull/20) is open against `main`, merges cleanly, and needs one teammate review.

| Field | Value |
| --- | --- |
| Branch | `aditya_19sep_b` → `main` |
| Size | 12 commits, 37 files, +2627 / −177 |
| Merge state | Mergeable, no conflicts |
| Reviews | None yet |
| CI checks | None configured on the repo; tests were run locally (372 passed, 2 skipped) |
| Migration | `0004_report_duplicate_of` — run `alembic upgrade head` from `backend/` after merging |
| Frontend impact | None; the submit response only gains an additive `queued` field |

## Risks and open questions

The biggest risk is a double merge: PR #18 is still open, and all of its commits are also in PR #20.

| Risk | Impact | Proposed action |
| --- | --- | --- |
| PR #18 duplicates PR #20 | A reviewer could merge #18 first or review the same work twice. | Close #18 as superseded by #20. |
| No CI on the repo | A PR with failing tests can be merged without anyone noticing. | Run `pytest` before every merge until CI exists. |
| Test message on `indra.verified.events` | Anything reading the topic from the start sees one `WX-EV-LIVECHECK` test event. | Delete the topic before the demo; it is recreated on the next real event. |
| Event publishing not yet run with real reports | Only a direct test publish was checked live. | Covered by the Day 5 rehearsal from empty volumes. |
| Classifier below its acceptance gate | `NOT_RELEVANT` recall 0.667 (gate 0.80), so it stays switched off. | A v2 needs a fresh, unseen test set. |
| Alert Engine (layer 8b) not built | The architecture diagram and README Scene 10 show it. | State the gap openly in the demo; the WebSocket push is the real version. |

**Open question:** are OpenWeather, IMD and Twitter feeds in scope for the demo? If not, the README should say so.

## Plan for 19 Sep

Finish Day 4 by 19 Sep 2026 so 20 Sep is free for hardening and the demo rehearsal.

- [ ] Build `POST /api/events/reprocess` (admin only); test: 10 unlinked reports → events created, no duplicates on a second call
- [ ] Decide the scope of OpenWeather, IMD and Twitter feeds and note it in the README
- [ ] Get PR #20 reviewed and merged; close PR #18
- [ ] Tick the Day 4 checkboxes and fix the stale warnings in `backend-architecture.md`
- [ ] Write the Day 5 plan (hardening, failure drills, rehearsal)
