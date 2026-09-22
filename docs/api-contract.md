# INDRA — Backend API Contract

**What this is:** every endpoint the backend actually serves, its request shape, its response
shape and every status code it can return. Written for whoever is calling this API — the
dashboard, a teammate's script, or a judge with `curl`.

**Last verified against the code and a running stack: 22 Sep 2026.** Every endpoint below was
read out of its router, not out of an older document. If this file and the code disagree, the
code is right and this file is a bug.

Base URL in development: `http://localhost:8000`. Interactive docs: `/docs`.

---

## The shape of the whole API

| Group | Endpoints | Auth |
|---|---|---|
| `/api/dashboard` | KPI summary | open |
| `/api/events` | list, distribution, detail, **review**, **provenance** | review and provenance require a token |
| `/api/reports` | submit, **official**, trend, recent | `official` requires a token |
| `/api/feed` | recent activity | open |
| `/api/geo` | heatmap | open |
| `/api/alerts` | official SACHET warnings (IMD, CWC, SDMAs) | open |
| `/api/audit` | the newest ledger rows, chain verified | requires a token |
| `/api/auth` | token | — |
| `/api/teams`, `/api/profile` | team and operator records | reads open; **every write requires a token** |
| top level | `/healthz`, `/api/info`, `/ws/events` | open |

**Every endpoint that changes state requires a token**, except logging in and a citizen filing a
report, which are anonymous by design. `tests/test_mutation_auth.py` walks the whole API and fails
if a new mutation is added without a guard (BUG-009, closed 22 Sep). Reads stay open for the
dashboard, except provenance and the audit ledger, which carry operator ids and reasons.

---

## `/api/reports`

### `POST /api/reports/submit` → `202`

The one write path into the platform.

```json
{ "latitude": 25.5941, "longitude": 85.1376,
  "text": "Knee deep water outside my house, drain overflowing",
  "media_url": null }
```

| Field | Rule |
|---|---|
| `latitude`, `longitude` | Must be inside India's bounding box (lat 6.5–37.6, lng 68.0–97.5) |
| `text` | 5–2000 characters |
| `media_url` | Optional string. **Nothing opens it** — there is no image analysis |

**Responses**

| Code | When |
|---|---|
| `202 {id, status: "accepted", queued: true\|false, source_type}` | Stored. `queued: false` means it is in the database but the Kafka publish failed, so it will not be processed until replayed. `source_type` is always `CITIZEN_APP` here |
| `422` | Validation failed, including **coordinates outside India** — nothing is stored |
| `503` | The database write failed. **Nothing is stored and nothing is published** |

On the way in, the report is given an H3 res-8 cell, a computed `credibility_score`
(source prior × text quality — a 60-character citizen report scores 0.60, the bare word
`"flood"` 0.325) and an `analysis` object from rule-based extraction:

```json
{ "cleaned_text": "...", "language": "en|hi|hinglish", "depth_cm": 50,
  "depth_basis": "body:knee", "keywords": [...], "places": ["Patna"],
  "url_count": 0, "phone_count": 0, "extracted_at": "..." }
```

Two things to be precise about: `places` resolves against a 56-city gazetteer, so it yields
**cities, never landmarks** — `"Patna"`, not `"Gandhi Maidan"`. And extraction is regex and
dictionaries, **not a model**; if it fails the report is still stored with `analysis: null`.

A swapped lat/lng pair that lands inside India is corrected rather than rejected.

The route is anonymous and **always stores `CITIZEN_APP`**, whatever the body says. A client that
could name its own source could claim `OFFICIAL_DISPATCH` and hand itself the highest reliability
in the model; extra fields are ignored, not obeyed.

### `POST /api/reports/official` → `202` — **requires a token**

Auth: `COMMANDER` or `ADMIN`. The same body and the same checks as `/submit` (422 outside India,
503 when the write fails), for a report from a trusted field source — a district control room, an
SDRF team. Stored as **`OFFICIAL_DISPATCH`** with `submitted_by` set to the operator's token
subject (migration `0010`), then processed exactly like a citizen report: dedup, clustering,
scoring, review.

One official report in a cluster lifts the **Source Reliability** factor to 1.00, because that
factor is the maximum over the cluster's sources. It does not bypass corroboration, weather or
human review. Measured 22 Sep: five Patna citizen reports scored 0.5146 `QUARANTINED`; the same
five plus one dispatch scored **0.6065 `PENDING_HUMAN_REVIEW`**.

| Code | When |
|---|---|
| `202 {id, status, queued, source_type: "OFFICIAL_DISPATCH"}` | Stored |
| `401` | No token, or an invalid one — nothing stored |
| `403` | A citizen or analyst token — nothing stored |
| `422`, `503` | As `/submit` |

The route is only as trusted as the account behind it. The demo accounts' passwords are part of
the dashboard's persona switcher, so in this build it shows the mechanism — role-gated and
attributed — not a secret.

### `GET /api/reports/trend?range=7d|14d|30d`

Daily report counts. Always returns a row per day, including zeros.

---

## `/api/events`

### `GET /api/events`

| Query param | Values |
|---|---|
| `severity` | `ADVISORY` · `MODERATE` · `HIGH` · `CRITICAL` |
| `time_range` | `24h` · `48h` · `7d` |
| `bbox` | `min_lng,min_lat,max_lng,max_lat` |

Up to 50, newest first. `REJECTED` events are always excluded.

> **`ADVISORY` is reachable and common.** Most fresh clusters are two to four reports with no
> depth quoted, which grades `ADVISORY`. A severity filter offering only
> `ALL / CRITICAL / HIGH / MODERATE` will show these under ALL and be unable to filter them.

### `GET /api/events/distribution`

Event counts grouped by type, for the donut chart.

### `GET /api/events/{event_id}`

Accepts the UUID **or** the `event_code`. Returns the full event, including:

| Field | Note |
|---|---|
| `confidence_score` | 0–1, re-normalised over the factors that reported |
| `verification_receipt` | see below |
| `boundary_geojson` | **always populated** — a `Polygon` containing every contributing report |
| `review_status` | `AUTO_PUBLISHED` · `PENDING_HUMAN_REVIEW` · `QUARANTINED` · `REJECTED` · `HUMAN_APPROVED` |
| `verification` (display label) | `verified` for `AUTO_PUBLISHED` **and** `HUMAN_APPROVED` · `under-review` for pending/quarantined · `rejected` |

Unknown id → `404` (or the demo event if `DEMO_MODE=true`, which it is not by default).

### The Verification Receipt

The receipt is the product. It explains every number it states.

```json
{
  "confidence": 0.4984,
  "factor_coverage": 0.80,
  "total_weighted": 0.3987,
  "factors": [
    {"factor": "Weather Station Corroboration", "weight": 0.25, "score": 0.0080,
     "points": 0.0020, "state": "computed",
     "evidence": "0.2 mm rainfall in past 24 h (polled station reading)"},
    {"factor": "Computer Vision Analysis", "weight": 0.15, "score": null,
     "points": 0.0, "state": "offline",
     "evidence": "Telemetry factor offline"}
  ],
  "weather": {"rainfall_24h_mm": 0.2, "provider": "open-meteo",
              "source": "station_reading"},
  "severity_basis": {"rule": "max(depth_axis, count_axis)", "max_depth_cm": 50,
                     "depth_basis": "body:knee", "depth_axis": "MODERATE",
                     "count_axis": "MODERATE"},
  "human_review": {"action": "approve", "operator_id": "...", "reason": "...", "at": "..."}
}
```

**`confidence = total_weighted / factor_coverage`**, and the numbers are printed so you can check
it. `factor_coverage` is the share of the designed model that actually reported: **0.80**, because
`vision_analysis` (0.15) and `anomaly_detection` (0.05) are **permanently offline** — the AI/ML
layer left this project's scope on 20 Sep. **Never display the score without the coverage.**

`weather.source` is `station_reading` when the rainfall came from this platform's own polled
table, `open_meteo_live` when it was fetched while scoring.

### `PATCH /api/events/{event_id}/review` — **requires a token**

Auth: `COMMANDER` or `ADMIN`.

```json
{ "action": "approve" | "reject" | "override_severity",
  "reason": "5 to 1000 characters",
  "new_severity": "ADVISORY|MODERATE|HIGH|CRITICAL" }
```

| Action | Effect |
|---|---|
| `approve` | From `QUARANTINED`/`PENDING_HUMAN_REVIEW` → `HUMAN_APPROVED`. Quadrant becomes `Critical Verified Event` if HIGH/CRITICAL, else `Confirmed Minor Event`. Audit `HUMAN_APPROVE` |
| `reject` | From anything but `REJECTED` → `REJECTED`. Drops out of the list, still served by detail. Audit `HUMAN_REJECT` |
| `override_severity` | Status unchanged, quadrant recomputed. `new_severity` required. Audit `MANUAL_OVERRIDE` |

**`confidence_score` is never changed by a review.** The machine's reading and the human's
decision are recorded separately, on purpose.

`200` the updated event · `401` no/invalid/expired token · `403` analyst or citizen · `404`
unknown id · `409` transition not allowed, nothing written · `422` bad body · `503` database
error. Row-locked, so two concurrent approvals give one `200` and one `409`. Broadcasts
`EVENT_REVIEWED` after the commit.

### `GET /api/events/{event_id}/provenance` — **requires a token**

Auth: `ANALYST`, `COMMANDER` or `ADMIN`.

```json
{ "event": {...},
  "reports": [{id, source_type, raw_text, latitude, longitude, credibility_score, created_at,
               submitted_by}],
  "audit":   [{seq, action_taken, operator_id, reason, details, logged_at, sha256_hash, prev_hash}],
  "chain":   {"valid": true, "checked": 12, "broken_at_seq": null} }
```

Reports oldest first; audit rows in chain order. **`chain` verifies the whole ledger from
genesis**, so `checked` is the total row count, not this event's. `submitted_by` names the operator
who filed an `OFFICIAL_DISPATCH`; it is `null` for a citizen report.

> **Honest limit:** the chain detects an edited, deleted or reordered row. It **cannot** detect
> rows cut off the end, or a `TRUNCATE` — that needs an external anchor for the head hash, which
> is not built. Say so if asked; do not claim otherwise.

### Auth matrix — pinned by `test_auth_enforcement.py`, `test_mutation_auth.py`, `test_official_ingest.py`, `test_audit_api.py`

| Endpoint | none | expired/wrong key | citizen | analyst | commander | admin |
|---|---|---|---|---|---|---|
| `PATCH /api/events/{id}/review` | 401 | 401 | 403 | 403 | 200 | 200 |
| `GET /api/events/{id}/provenance` | 401 | 401 | 403 | 200 | 200 | 200 |
| `GET /api/audit/recent` | 401 | 401 | 403 | 200 | 200 | 200 |
| `POST /api/reports/official` | 401 | 401 | 403 | 403 | 202 | 202 |
| `POST /api/teams` | 401 | 401 | 403 | 403 | 201 | 201 |
| `PATCH /api/teams/{id}/assign` | 401 | 401 | 403 | 403 | 200 | 200 |
| `PATCH /api/profile/me`, `/preferences` | 401 | 401 | 200 | 200 | 200 | 200 |
| `POST /api/reports/submit` | 202 | 202 | 202 | 202 | 202 | 202 |
| `GET /api/events` | 200 | 200 | 200 | 200 | 200 | 200 |

A profile edit changes **the token's own operator only**; a `?user=` parameter is ignored.

---

## `/api/geo`

### `GET /api/geo/heatmap?window=24h|48h|7d&resolution=6|7|8`

```json
{ "resolution": 8, "window": "24h", "generated_at": "...",
  "cells": [{"h3": "883c138ca3fffff", "lat": 25.594, "lng": 85.137,
             "report_count": 3, "linked_report_count": 3}] }
```

- **Duplicates are excluded.** A suppressed repost is not a second piece of evidence, and a map
  that counted it would show a brighter spot for a more viral report rather than a wetter street.
- **Aggregation, never interpolation.** A res-6 or res-7 count is the exact sum of the stored
  res-8 counts beneath it. Nothing is smoothed or spread.
- `linked_report_count` is how many of the cell's reports have been fused into a verified event —
  the difference between "people are reporting here" and "this is an incident".

`422` for a resolution finer than 8 or an unrecognised window — it will not quietly serve you a
different window than you asked for. `200` with `cells: []` when nothing is in range. `503` on a
database error.

---

## `/api/dashboard`

### `GET /api/dashboard/summary`

KPI counts for the dashboard cards: total reports, verified events, critical events and citizen
reports, each with a 24-hour delta percentage, plus `awaiting_review` (escalated or quarantined)
and `active_alerts` (unexpired SACHET warnings). `verified_events` counts only `AUTO_PUBLISHED` and
`HUMAN_APPROVED` (BUG-034). Every number comes from the database.

---

## `/api/feed`

### `GET /api/feed/recent`

Recent reports for the live feed panel, newest first, each with a `source` key and label:
`citizen` for `CITIZEN_APP`, `official` for `OFFICIAL_DISPATCH` (it was `news` until 22 Sep).

---

## `/api/alerts`

### `GET /api/alerts/agency?limit=20&severity=&include_expired=false`

Official CAP warnings from NDMA's SACHET feed — IMD, CWC and state SDMAs — stored by the SACHET
poller every 5 minutes, newest first. `limit` 1–200. `severity` is `ADVISORY | MODERATE | HIGH |
CRITICAL` (422 otherwise) and excludes unrated alerts; `raw_severity` keeps the issuer's own word
(`Extreme`, `Severe`, `Moderate`…). `lat`/`lng` come from resolving `area_desc` against the district
gazetteer and are `null` when the alert is below district level. `[]` when nothing is in force.

`GET /api/alerts/agency/{id}/polygon` — the alert's footprint as GeoJSON (`thinned: true` when the
ring was decimated to bound its size), or `404` when none was stored. NDMA's polygon endpoint
sometimes answers 403, so coverage varies: 130 of 263 alerts in the local database had one on
22 Sep, and none of the 27 fetched during that morning's rehearsal.

These are **real government warnings**. INDRA itself issues none: the alert engine was cancelled.

---

## `/api/audit`

### `GET /api/audit/recent?limit=20` — **requires a token**

Auth: `ANALYST`, `COMMANDER` or `ADMIN`. The newest `limit` (1–200) ledger rows, newest first, and
a verification of the **whole** chain from genesis:

```json
{ "chain": {"valid": true, "checked": 2, "broken_at_seq": null},
  "total": 2,
  "rows": [{seq, action_taken, operator_id, event_id, reason, logged_at, sha256_hash}] }
```

`503` on a database error. The same limit as provenance applies: rows cut off the end are not
detected (BUG-010).

---

## `/api/auth`

### `POST /api/auth/token`

**Form-encoded**, not JSON (OAuth2 password flow): `username`, `password`.

Returns `200 {access_token, token_type: "bearer", role, agency}` — a real HS256 JWT, 8 h expiry.
`401` on bad credentials.

Demo users: `admin`/`admin123`, `commander`/`commander123`, `analyst`/`analyst123`,
`citizen`/`citizen123`.

---

## `/api/teams` and `/api/profile`

`GET /api/teams` · `GET /api/teams/{id}` · `POST /api/teams` (201) ·
`PATCH /api/teams/{id}/assign` · `GET /api/teams/hackathon/sixth-sense`

`GET|PATCH /api/profile/me` · `GET /api/profile/activity` · `GET /api/profile/operators` ·
`GET|PATCH /api/profile/preferences`

Reads are open. Writes need a token (matrix above):

| Endpoint | Codes |
|---|---|
| `POST /api/teams` | `201` · `409` duplicate `team_code` · `422` unknown agency or status · `503` |
| `PATCH /api/teams/{id}/assign` `{event_id: uuid \| null}` | `200 {team_id, assigned_event_id, status, assigned_by}` · `404` team or event not found · `422` malformed `event_id` · `503` |
| `PATCH /api/profile/me` | `200` the saved profile · `422` unknown `duty_status` · `503` when the write fails |

Until 22 Sep a failed dispatch answered `200 "Updated in demo store"` from an in-memory list, and a
failed profile edit answered `200` after `except: pass`. Both now fail loudly.

---

## Top level

| Endpoint | Behaviour |
|---|---|
| `GET /` | Redirects to the dashboard on :3000 |
| `GET /api/info` | Platform metadata |
| `GET /healthz` | Real dependency check — see below |
| `WS /ws/events` | The live stream |

### `GET /healthz`

Checks Postgres (**including whether the schema exists**), Kafka/Redpanda, Redis and Open-Meteo
concurrently, each capped at 2 s.

| Status | HTTP | When |
|---|---|---|
| `healthy` | 200 | everything up |
| `degraded` | 200 | Redis or Open-Meteo is down — neither is load-bearing |
| `unhealthy` | 503 | Postgres or Kafka is down — a report would be lost or unprocessed |

```json
{"status":"healthy","checks":{"database":{"status":"up","latency_ms":50.7,"critical":true}, ...}}
```

### `WS /ws/events`

| Message | Payload | When |
|---|---|---|
| `NEW_REPORT` | `{type, report}` | A report was accepted. Once per report id, now across a restart |
| `VERIFIED_EVENT` | `{type, event}` | The pipeline created or updated an event |
| `EVENT_REVIEWED` | `{type, event}` | A commander approved, rejected or re-graded one |

`report` carries `raw_text`, `h3_res8`, `credibility_score` and `source_type`. The key is
`raw_text`, **not** `text`.

> Fan-out is in-process by design, so **run one backend process**. Two backends against one broker
> will re-deliver reports (BUG-011).

---

## Demo data and `DEMO_MODE`

`DEMO_MODE` defaults to **`false`** and must stay false for any demonstration.

| `DEMO_MODE` | No rows | Database error |
|---|---|---|
| `false` (default) | `[]`, or **404** on a detail endpoint | **503 `{"detail": "Database unavailable"}`** |
| `true` | demo data, WARNING logged | demo data, WARNING logged |

With it **true**, an empty database answers `GET /api/events` with a fabricated
`0.94 / AUTO_PUBLISHED / CRITICAL` event — a value the real engine cannot produce. The first
seconds of a live run are exactly when the database is empty, so the dashboard would open on a
confident auto-published disaster that no code computed. An empty dashboard that fills as reports
arrive is both honest and the better demonstration. This was BUG-024, found by running the demo
rather than by testing it.

`/api/dashboard/summary`, `/api/events*`, `/api/feed/recent`, `/api/reports/trend` and
`/api/teams*` all route through the same gate. `/api/geo/heatmap` and the provenance and review
endpoints have **no** demo fallback at all.

---

## When you add an endpoint

1. Put the contract here in the same shape, before merging.
2. If the dashboard must change, write it into [`frontend-handover.md`](frontend-handover.md).
3. If it can serve a number the database did not produce, it needs `demo_fallback()` and a test
   that asserts the `DEMO_MODE=false` behaviour.
