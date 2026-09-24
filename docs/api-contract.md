# INDRA — Backend API Contract

**What this is:** every endpoint the backend actually serves, its request shape, its response
shape and every status code it can return. Written for whoever is calling this API — the
dashboard, a teammate's script, or a judge with `curl`.

**Last verified against the code and a running stack: 23 Sep 2026 (Phase 1).** Every endpoint below
was read out of its router, not out of an older document, and every example response marked
*captured* was copied from `curl` against a running stack. If this file and the code disagree, the
code is right and this file is a bug.

Base URL in development: `http://localhost:8000`. On the team server, since 24 Sep:
**`https://indra-sixthsense.duckdns.org`**, one name for the dashboard, the API and the WebSocket
(`wss://indra-sixthsense.duckdns.org/ws/events`), with a Let's Encrypt certificate. The old
`http://15.252.50.176:8000` still answers until the whole team has switched, and will then be closed.
Interactive docs: `/docs`.

---

## The shape of the whole API

| Group | Endpoints | Auth |
|---|---|---|
| `/api/dashboard` | KPI summary | open |
| `/api/events` | list (**with the PS's filters**), distribution, detail, **review**, **provenance** | review and provenance require a token |
| `/api/reports` | submit, **official**, **track**, trend, recent | `official` requires a token |
| `/api/meta` | **filters**: the values the event filters can take | open |
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
  "media_url": null,
  "observed_at": "2026-09-23T19:40:00+05:30",
  "hazard": "URBAN_FLOOD" }
```

| Field | Rule |
|---|---|
| `latitude`, `longitude` | Must be inside India's bounding box (lat 6.5–37.6, lng 68.0–97.5) |
| `text` | 5–2000 characters |
| `media_url` | Optional string. **Nothing opens it** — there is no image analysis |
| `observed_at` | Optional. **When it happened**, ISO 8601 **with a timezone**. No more than 5 minutes ahead or 7 days back, otherwise 422. Omitted, it is stored equal to the time the report was received |
| `hazard` | Optional. The category the citizen picked: one of the 16 event types below, upper case. Stored as the citizen's claim; the event's type is still the platform's decision |

| Header | Rule |
|---|---|
| `X-Reporter-Id` | Optional, at most 200 characters. A random id the client generates once and keeps (a UUID in `localStorage`). **Only an HMAC of it is stored**, so reports from one device can be linked to each other and never to the device. Missing or blank means "unknown", never a shared identity |

**Responses**

| Code | When |
|---|---|
| `202 {id, docket, status: "accepted", queued, will_retry, source_type}` | Stored. `docket` is what the citizen keeps to follow the report (see `/track` below). `queued: true` means it was published to Kafka at once. `queued: false, will_retry: true` means **it is stored with its message and will be processed as soon as Kafka answers** — nothing is lost (BUG-060, fixed 23 Sep). `source_type` is always `CITIZEN_APP` here |
| `422` | Validation failed, including **coordinates outside India**, an implausible `observed_at` and an unknown `hazard` — nothing is stored |
| `503` | The database write failed. **Nothing is stored and nothing is published** |

Captured 23 Sep:

```json
{"id":"52478975-5fe2-4964-a65c-f555a256db72","docket":"R-24H48YNK","status":"accepted",
 "queued":true,"will_retry":false,"source_type":"CITIZEN_APP"}
```

```json
{"detail":[{"type":"value_error","loc":["body","observed_at"],
  "msg":"Value error, observed_at is more than 5 minutes in the future",
  "input":"2030-01-01T00:00:00+05:30","ctx":{"error":{}}}]}
```

**Why a report cannot be lost.** The report and its Kafka message (a row in `outbox`) are written in
one database transaction. The request publishes the message straight away if it can, for at most
2 s; if it cannot, a relay publishes it within seconds of Kafka coming back. Measured with Redpanda
stopped: ten reports kept, all published 1.0 s after it restarted (`demo-runbook.md`, Scene 5).

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
| `202 {id, docket, status, queued, will_retry, source_type: "OFFICIAL_DISPATCH"}` | Stored |
| `401` | No token, or an invalid one — nothing stored |
| `403` | A citizen or analyst token — nothing stored |
| `422`, `503` | As `/submit` |

The route is only as trusted as the account behind it. The demo accounts' passwords are part of
the dashboard's persona switcher, so in this build it shows the mechanism — role-gated and
attributed — not a secret.

### `GET /api/reports/track/{docket}`

Where a report is now, for the person holding its docket. **Open**, like `/submit`: the docket is
the credential. So it answers only what that person is entitled to know, and **never the text, the
coordinates or anything about who sent it**.

A docket is `R-` and 8 characters of Crockford base32, e.g. `R-7K3M9QX2`. The alphabet has no I, L, O
or U, so nothing read aloud or copied off a screen is mistaken for another character. It is random,
not a counter: nobody can guess one or walk through other people's reports. Case, spaces, hyphens
and the `R` prefix are forgiven, and O/I/L are read as 0/1/1.

| `status` | Meaning |
|---|---|
| `received` | Stored; the pipeline has not finished with it yet |
| `duplicate` | Suppressed as a copy of an earlier report |
| `not_yet_an_event` | Processed, but alone: nothing corroborates it yet. A later report nearby can still turn it into an event |
| `part_of_event` | Linked to an event that is in review or quarantine |
| `event_approved` | Linked to an event a commander approved, or that was published automatically |
| `event_rejected` | Linked to an event a commander rejected |

Captured 23 Sep:

```json
{"docket":"R-24H48YNK","received_at":"2026-09-23T14:35:49.914494+00:00","status":"part_of_event",
 "event_code":"INDRA-20260923-001","review_status":"QUARANTINED","district":"Patna","state":"Bihar"}
```

`event_code` and `review_status` are `null` until the report is part of an event. `404
{"detail": "No report with that docket"}` for an unknown docket **and** for one that cannot exist,
so the answer never helps anyone guess. `503` on a database error; there is no demo answer.

### `GET /api/reports/trend?range=7d|14d|30d`

Daily report counts. Always returns a row per day, including zeros.

---

## `/api/events`

### `GET /api/events`

The PS's *"Date-wise filtering • Event-wise filtering • Location-wise filtering • Verification status
tracking"*. Every parameter is optional and they combine with AND. Lists are comma-separated.

| Query param | Values |
|---|---|
| `from`, `to` | `YYYY-MM-DD` — a whole day **in IST**, both ends inclusive — or an ISO 8601 timestamp (one without an offset is read as IST). An event at 23:30 IST on the 20th is on the 20th, though it is 18:00 UTC. **Encode `+` as `%2B`** in a query string, or it arrives as a space |
| `event_type` | one or more of the 16 types below |
| `family` | `water` · `convective` · `thermal` · `visibility` |
| `review_status` | one or more statuses. **`REJECTED` appears only when named** |
| `severity` | one or more of `ADVISORY` · `MODERATE` · `HIGH` · `CRITICAL`. The old single value still works |
| `state`, `district` | exact name, any case (`bihar` matches `Bihar`) |
| `source_type` | events with at least one report from these sources, e.g. `OFFICIAL_DISPATCH` |
| `min_confidence` | 0–1 |
| `q` | text in the event code, district or state; `%` and `_` match only themselves |
| `bbox` | `min_lng,min_lat,max_lng,max_lat` (unchanged) |
| `time_range` | `24h` · `48h` · `7d` (unchanged; the dashboard sends `7d`) |
| `include` | `boundary` adds `boundary_geojson` (a GeoJSON string, as on the detail route) to each item |
| `sort` | `verified_at`, `confidence` or `severity`, then `:asc` or `:desc`. Default `verified_at:desc`. Severity sorts by meaning, not alphabetically |
| `limit`, `offset` | `limit` 1–200, default 50 |

**The body is still a list**, newest first. **The number of matching events is in the
`X-Total-Count` header**, which CORS exposes to the dashboard's origin. Each item has the keys it
always had, plus `event_type` (the enum — key icons on this, not on the display label `eventType`)
and `family`.

Captured 23 Sep:

```
GET /api/events?state=bihar&event_type=URBAN_FLOOD&from=2026-09-23&to=2026-09-23&limit=1
HTTP/1.1 200 OK
x-total-count: 1

[{"id":"3e57d37f-a703-42a2-93e8-d780ee4f2604","event_code":"INDRA-20260923-001","eventType":"Flood",
  "event_type":"URBAN_FLOOD","family":"water","severity":"moderate","confidence_score":0.5464,
  "verification":"under-review","review_status":"QUARANTINED","quadrant":"Noise",
  "impact_radius_km":0.5,"lat":25.594399999999997,"lng":85.13763333333333,"city":"Patna","state":"Bihar",
  "place_precision":"district","imageGradient":"linear-gradient(135deg, #2563EB, #1E3A8A)",
  "verified_at":"2026-09-23T14:21:38.845208+00:00","timestamp":"2026-09-23T14:21:38.845208+00:00"}]
```

A bad value is a **422 naming the parameter**, in the same shape FastAPI uses for its own checks
(`limit=500` and `event_type=TORNADO` look alike):

```json
{"detail":[{"type":"value_error","loc":["query","event_type"],
  "msg":"unknown value 'TORNADO'; expected any of ['CLOUDBURST', 'COLD_WAVE', 'CYCLONE', 'CYCLONE_INUNDATION', 'DUST_STORM', 'FOG', 'HAILSTORM', 'HEATWAVE', 'LANDSLIDE', 'LIGHTNING', 'RAINFALL', 'RIVER_BREACH', 'STRONG_WIND', 'THUNDERSTORM', 'UNCLASSIFIED', 'URBAN_FLOOD']",
  "input":"TORNADO"}]}
```

Also 422: `from` after `to`, a range longer than 366 days, an unknown `sort` or `include`. Until
23 Sep an unknown severity answered **503 "Database unavailable"** (BUG-061). A filter that matches
nothing is `200 []` with `X-Total-Count: 0` — never demo data.

> **`ADVISORY` is reachable and common.** Most fresh clusters are two to four reports with no
> depth quoted, which grades `ADVISORY`. A severity filter offering only
> `ALL / CRITICAL / HIGH / MODERATE` will show these under ALL and be unable to filter them.

### `GET /api/events/distribution`

Event counts grouped by type, for the donut chart. Each slice is named with the type's label from
the table below (`"Flood"`); until 23 Sep an event the pipeline made was drawn as a grey
`"URBAN_FLOOD"` slice (BUG-062).

### Event types

Sixteen since 23 Sep (migration `0011`), described in one place: `app/services/hazards.py`. The
pipeline still names every event `URBAN_FLOOD`; tagging reports with the other types is Phase 3.

| `event_type` | Label | Family | Precedence |
|---|---|---|---|
| `CLOUDBURST` | Cloudburst | water | 1 |
| `CYCLONE_INUNDATION` | Storm surge | water | 1 |
| `URBAN_FLOOD` | Flood | water | 1 |
| `RIVER_BREACH` | River flood | water | 2 |
| `CYCLONE` | Cyclone | convective | 3 |
| `LANDSLIDE` | Landslide | water | 3 |
| `DUST_STORM` | Dust storm | convective | 4 |
| `HAILSTORM` | Hailstorm | convective | 5 |
| `LIGHTNING` | Lightning | convective | 5 |
| `THUNDERSTORM` | Thunderstorm | convective | 5 |
| `STRONG_WIND` | Strong Winds | convective | 6 |
| `COLD_WAVE` | Cold wave | thermal | 7 |
| `HEATWAVE` | Heatwave | thermal | 7 |
| `FOG` | Fog | visibility | 8 |
| `RAINFALL` | Heavy Rainfall | water | 9 |
| `UNCLASSIFIED` | Unclassified | — | 99 |

A **family** decides which reports may cluster together (Phase 3); **precedence** names a mixed
cluster for its impact rather than its cause (a flood beats the rain). The labels the dashboard
already keys on are unchanged: `Flood`, `Thunderstorm`, `Strong Winds`, `Fog`, `Heavy Rainfall`.

Source types: `CITIZEN_APP`, `OFFICIAL_DISPATCH`, `AWS_SENSOR`, `CWC_GAUGE`, `TWITTER_IMD`, and since
23 Sep `SOCIAL_MEDIA` and `NEWS_MEDIA` (for Phase 2's Mastodon and news feeds).

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

`routing` (since 24 Sep) says why the event has its `review_status`:

```json
"routing": {"review_status": "PENDING_HUMAN_REVIEW", "basis": "severity",
            "auto_publish_threshold": 0.9, "human_review_threshold": 0.6}
```

Confidence ≥ 0.90 publishes; ≥ 0.60 goes to review; below that the event is quarantined —
**unless it is `HIGH` or `CRITICAL`, which goes to review instead**, and `basis` is `severity`
(BUG-067). Nothing is published without a human below 0.90, whatever its severity.

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

## `/api/meta`

### `GET /api/meta/filters`

The values the event filters can take, each with how many events have it, so the filter bar never
hard-codes an option or offers one with nothing behind it. Counts are over non-rejected events, as
the list shows them by default — except `review_statuses`, which includes `REJECTED` so the dropdown
can offer what `?review_status=REJECTED` returns. A `NULL` district counts for its state and is
never listed as a district. Dates are IST.

Captured 23 Sep (one event in the database):

```json
{"event_types":[{"value":"URBAN_FLOOD","label":"Flood","family":"water","count":1}],
 "families":[{"value":"water","count":1}],
 "review_statuses":[{"value":"QUARANTINED","count":1}],
 "severities":[{"value":"MODERATE","count":1}],
 "source_types":[{"value":"CITIZEN_APP","count":1}],
 "states":[{"name":"Bihar","count":1,"districts":[{"name":"Patna","count":1}]}],
 "date_min":"2026-09-23","date_max":"2026-09-23",
 "generated_at":"2026-09-23T14:35:54.192358+00:00"}
```

Empty database: every list `[]` and both dates `null`. Cached for **60 s** (Redis key
`meta:filters`, with an in-memory fallback), so a new event can take up to a minute to appear in the
options; it appears in the list at once. `503` on a database error, never invented options.

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

Checks Postgres (**including whether the schema exists**), Kafka/Redpanda, Redis, Open-Meteo and
the outbox backlog concurrently, each capped at 2 s.

| Status | HTTP | When |
|---|---|---|
| `healthy` | 200 | everything up |
| `degraded` | 200 | Redis or Open-Meteo is down, or a report has waited more than 60 s for Kafka — none of these loses anything |
| `unhealthy` | 503 | Postgres or Kafka is down. Postgres: reports are refused. Kafka: reports wait in the outbox, but nothing new is processed until it is back |

`outbox_backlog` carries `count` (reports stored but not yet published to Kafka) and `oldest_s` (how
long the oldest has waited). Captured 23 Sep:

```json
{"status":"healthy","checks":{
  "database":{"status":"up","latency_ms":9.0,"critical":true},
  "streaming_bus":{"status":"up","latency_ms":4.6,"critical":true},
  "redis":{"status":"up","latency_ms":6.7,"critical":false},
  "weather_api":{"status":"up","latency_ms":1228.5,"critical":false},
  "outbox_backlog":{"status":"up","count":0,"oldest_s":0.0,"latency_ms":3.5,"critical":false}}}
```

### `WS /ws/events`

| Message | Payload | When |
|---|---|---|
| `NEW_REPORT` | `{type, report}` | A report was accepted. Once per report id, now across a restart |
| `VERIFIED_EVENT` | `{type, event}` | The pipeline created or updated an event |
| `EVENT_REVIEWED` | `{type, event}` | A commander approved, rejected or re-graded one |

`report` carries `raw_text`, `h3_res8`, `credibility_score` and `source_type`. The key is
`raw_text`, **not** `text`. Its keys are exactly the nine the Kafka message has always had; the
docket, the reporter hash and feed metadata are never added, because this message goes to every
connected browser.

> Fan-out is in-process by design, so **run one backend process**. Two backends against one broker
> will re-deliver reports (BUG-011).

---

## Proposed — Phase 2, 4, 5 and 6

**Not built yet.** These are the names later phases will use, published now so the dashboard can be
built against them. Shapes will be fixed in this file when each one lands; until then treat
everything but the path as provisional.

| Phase | Endpoint | For |
|---|---|---|
| 2 | `GET /api/reports/search` | Search and filter reports, with `X-Total-Count` like `/api/events` |
| 2 | `GET /api/reports/export`, `GET /api/events/export` | CSV and GeoJSON downloads of a filtered set |
| 2 | `GET /api/meta/sources` | Each feed's status: last success, last error, items collected |
| 2 | `GET /api/stations/latest?feed=metar` | The latest airport weather observations |
| 4 | `GET /api/review/queue` | The review queue's tabs |
| 4 | `POST /api/events/{id}/claim`, `DELETE /api/events/{id}/claim` | Claiming an event for review |
| 4 | `GET /api/events/{id}/history` | An event's score and status over time |
| 4 | `GET /api/events?verdict=` | Corroborated / contradicted / no official match |
| 5 | `POST /api/reports/submit` as multipart | Photo and video upload |
| 5 | `GET /api/media/{id}` | A report's media |
| 5 | `DELETE /api/reports/{docket}` | A citizen withdrawing their own report |
| 5 | `GET /api/admin/sources` | Per-source credibility |
| 6 | `GET /api/analytics/kpis`, `/timeseries`, `/by-state`, `/latency`, `/verification-funnel` | The analytics page |
| 6 | `POST /api/ingest/batch` | Bulk ingest for the load test and the replay |

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
