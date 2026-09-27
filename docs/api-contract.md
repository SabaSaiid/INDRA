# INDRA — Backend API Contract

**What this is:** every endpoint the backend actually serves, its request shape, its response
shape and every status code it can return. Written for whoever is calling this API — the
dashboard, a teammate's script, or a judge with `curl`.

**Last verified against the code and a running stack: 23 Sep 2026 (Phase 1).** The 24 Sep additions
(feed streams, IST trend, `/api/reports/recent` fields, `/api/meta/sources`, `/api/geo/stations`) were
checked by running their SQL on the team database; their pytest cases are written and not yet run.
**Phase 2's additions (24 Sep, branch `aditya_24sep_c`) are written and not yet tested:** their
shapes below are read from the code, none is *captured*, and each is marked "Phase 2". Every endpoint below
was read out of its router, not out of an older document, and every example response marked
*captured* was copied from `curl` against a running stack. If this file and the code disagree, the
code is right and this file is a bug.

**Every citizen report and event in the examples is a test submission** on a development database
(21–23 Sep, mostly Patna, several of them posted by demo scripts deleted on 25 Sep). They never
happened and are no longer stored; only their shape is the point. The official warnings, posts and
airport observations quoted are real feed data.

**25 Sep, the demo-data removal (branch `aditya_remove_demo_data`):** accounts and their bcrypt
hashes live in `user_profiles` (`/api/auth`), `GET /api/profile/me` needs a token,
`/api/profile/preferences` is gone, `GET /api/info` has no `status`, `POST /api/teams` needs
`members_count`, and every read answers an empty database with an empty result (*Empty and
unavailable*, at the end). These sections are read from the code and the migration; none is
captured yet.

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
| `/api/events` | **export** (Phase 2) | requires an **analyst** token |
| `/api/reports` | submit, **official**, **track**, trend, recent | `official` requires a token |
| `/api/reports` | **search**, **export** (Phase 2) | require an **analyst** token |
| `/api/meta` | **filters**: the values the event filters can take; **sources**: whether each feed is alive | open |
| `/api/feed` | recent activity | open |
| `/api/geo` | heatmap, rainfall stations | open |
| `/api/stations` | **latest** airport observations (Phase 2) | open |
| `/api/alerts` | official SACHET warnings (IMD, CWC, SDMAs) | open |
| `/api/audit` | the newest ledger rows, chain verified | requires a token |
| `/api/auth` | token: sign in with an account's username and password | — |
| `/api/teams`, `/api/profile` | team and operator records | reads open except `/api/profile/me`; **every write requires a token** |
| top level | `/healthz`, `/api/info`, `/ws/events` | open |
| `/api/e2e` | **identity**, only on a backend started for the browser tests | open; **404 in every other mode** |

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
2 s; if it cannot, a relay publishes it within seconds of Kafka coming back. Measured 23 Sep on a
development stack with Redpanda stopped: ten reports kept, all published 1.0 s after it restarted.
The drill in `demo-runbook.md` now runs against the isolated E2E backend (`make e2e-backend`).

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

The rule-based extraction above is distinct from the frozen local AI/ML advisory path. When the
pipeline processes a clusterable stored report, its typed six-component `UnifiedMLResult` is
persisted under `raw_reports.analysis.ml`; missing image or station history is `NOT_RUN`, not a
zero or negative prediction. A stored media URL is never fetched by model inference. This internal
evidence does not change the public submit response or authorize automatic confirmation.

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
human review. Measured 22 Sep on a test cluster of five scripted Patna reports: 0.5146
`QUARANTINED`; with one dispatch added, **0.6065 `PENDING_HUMAN_REVIEW`**.

| Code | When |
|---|---|
| `202 {id, docket, status, queued, will_retry, source_type: "OFFICIAL_DISPATCH"}` | Stored |
| `401` | No token, or an invalid one — nothing stored |
| `403` | A citizen or analyst token — nothing stored |
| `422`, `503` | As `/submit` |

The route is exactly as trusted as the account behind it (see `/api/auth` for how accounts get
their passwords).

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
so the answer never helps anyone guess. `503` on a database error.

### `GET /api/reports/trend?range=7d|14d|30d`

Reports per **IST day**, oldest first, exactly N rows ending today, zeros included (24 Sep, BUG-072:
it bucketed by UTC date and `7d` returned eight rows).

```json
[{"date": "18 Sep", "day": "2026-09-18", "reports": 0}, … {"date": "24 Sep", "day": "2026-09-24", "reports": 0}]
```

### `GET /api/reports/recent?limit=100&hours=72&unfused_only=true`

Stored reports, newest first, for the map's field-report layer (`unfused_only=true`: not yet in an
event, not a suppressed duplicate) and the Field Reports page (`unfused_only=false`: everything).
`hours` up to 720.

```json
[{"id": "…", "source_type": "CITIZEN_APP", "text": "Water rising fast near Gandhi Maidan, knee deep on the road.",
  "lat": 25.5941, "lng": 85.1376, "district": "Patna", "state": "Bihar",
  "created_at": "2026-09-21T14:57:17.653497+00:00", "fused": false, "duplicate": false, "depth_cm": 50,
  "event_id": null, "event_code": null, "observed_at": "2026-09-21T14:57:17.653497+00:00",
  "credibility_score": 0.6}]
```

`event_id`, `event_code`, `observed_at` and `credibility_score` since 24 Sep. The docket is never
included: it is the citizen's credential for `/track`, and this list is open.

**Phase 2:** each item adds `place_precision` (`gps`, `district`, `state`, `none`) and `platform`
(`null`, `mastodon`, `google_news`). `raw_reports` now also holds collected posts and headlines,
most placed only at a district's or state's centroid or not at all; they are **left out unless
`include_feeds=true`**, so the map layer draws exactly what it drew before. With
`include_feeds=true`, `lat` and `lng` are `null` for a post that names no place.

### `GET /api/reports/search` — **requires an analyst token** (Phase 2 T10)

Every report INDRA holds — citizen reports, official dispatches, Mastodon posts, news headlines —
filtered. The body is a list; the number of matches is in `X-Total-Count`. ANALYST, COMMANDER or
ADMIN: unlike the open routes this returns exact coordinates and full text, which are personal data
under the DPDP Act.

| Parameter | Meaning |
|---|---|
| `from`, `to` | an IST day (`YYYY-MM-DD`, `to` inclusive) or an ISO 8601 timestamp, on `observed_at`; `time_field=created` switches to the time INDRA received it |
| `source_type` | comma list: `CITIZEN_APP`, `OFFICIAL_DISPATCH`, `SOCIAL_MEDIA`, `NEWS_MEDIA`, … |
| `platform` | comma list: `mastodon`, `google_news` |
| `publisher` | a news publisher's name, any case |
| `state`, `district` | exact name, any case |
| `precision` | comma list: `gps`, `district`, `state`, `none` |
| `status` | comma list: `duplicate` (suppressed copy), `fused` (in an event), `stale` (a headline already 48 h old when collected), `held` (a post or headline that cannot cluster: social clustering is off, it names no district, or it is a forecast or warning — **Phase 3**), `unfused` (anything else not in an event) — one per report, in that order of precedence |
| `has_media` | `true` / `false` |
| `language` | comma list of codes: `en`, `hi`, `hinglish`, or a post's own |
| `hazard` | comma list of event types: a hazard the report's text is tagged with (any of them, not only the primary — **Phase 3**), or the category a citizen picked |
| `flag` | comma list of misleading-text flags (**Phase 3 T8**): `promotional`, `not_an_observation`, `past_event`, `implausible_value`, `exaggeration`, `shouting`, `forward_marker`, `coordinated` |
| `q` | text contains, any case; `%` and `_` match only themselves |
| `sort` | `observed_at`, `created_at` or `credibility`, then `:asc` or `:desc` (default `observed_at:desc`) |
| `limit`, `offset` | 1–200 (default 50), ≥ 0 |

```json
[{"id": "…", "docket": null, "source_type": "SOCIAL_MEDIA", "platform": "mastodon",
  "publisher": null, "url": "https://mastodon.social/web/statuses/117317830212677931",
  "text": "Yellow alert in …", "language": "en", "district": null, "state": "Kerala",
  "precision": "state", "lat": 10.3528, "lng": 76.5122, "observed_at": "2026-09-23T01:47:04.487000+00:00",
  "created_at": "…", "status": "held", "event_code": null, "duplicate_of": null,
  "credibility": 0.5, "media_count": 1, "hazard": null,
  "hazard_primary": "RAINFALL", "hazards": ["RAINFALL"], "flags": ["not_an_observation"]}]
```

**Phase 3 (written, not yet tested):** `hazard_primary` is the hazard the text is about (`null`
when it names none), `hazards` every hazard it is tagged with, in precedence order, and `flags` its
misleading-text flags (`[]` when clean). `hazard` is still the category the citizen picked. In the
CSV export the two lists are JSON arrays.

`docket` is filled for citizen reports only. `text` is at most 500 characters; `lat`/`lng` are
rounded to 4 decimals. `401` without a token, `403` for a citizen token, `422` for an unknown
value in any list parameter, `503` on a database error.

### `GET /api/reports/export?format=csv|geojson` — **requires an analyst token** (Phase 2 T10)

The search's selection, with the same filters and `sort`, as a download: `text/csv` (a header row,
then one line per report, the columns of the search item) or `application/geo+json` (a
FeatureCollection; a report with no place is a feature with a `null` geometry, as GeoJSON allows).
Streamed from a server-side cursor, so memory stays flat; **capped at 100,000 rows**. A GeoJSON
export ends with an `indra` member, `{"features": n, "truncated": bool, "row_cap": 100000}`; a
truncated CSV ends with a `# truncated at 100000 rows` line. The file name is in
`Content-Disposition`, which CORS exposes.

**Every export appends one `DATA_EXPORT` row to the audit ledger before the first byte is sent**:
who, which kind, which format, which filters. An export the ledger cannot record is refused with
`503`.

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
| `verdict` | **Phase 4 (tested 27 Sep).** one or more of `CORROBORATED` · `CONTRADICTED` · `UNCONFIRMED`. An event scored before receipt v2 has no verdict and matches none |
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
and `family`, and since Phase 4 `verdict` (`null` for an event last scored before receipt v2).

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
nothing is `200 []` with `X-Total-Count: 0`.

> **`ADVISORY` is reachable and common.** Most fresh clusters are two to four reports with no
> depth quoted, which grades `ADVISORY`. A severity filter offering only
> `ALL / CRITICAL / HIGH / MODERATE` will show these under ALL and be unable to filter them.

### `GET /api/events/export?format=csv|geojson` — **requires an analyst token** (Phase 2 T10)

Every event `GET /api/events` would list for the same filters and `sort` (no `limit`/`offset`),
as CSV or GeoJSON, capped and audited exactly like the report export. Columns and properties:
`id, event_code, event_type, family, label, severity, confidence_score, factor_coverage,
review_status, quadrant, impact_radius_km, lat, lng, district, state, place_precision,
report_count, verified_at, updated_at`. The GeoJSON geometry is the event's footprint polygon, or
its centre point when it has none.

### `GET /api/events/distribution`

Event counts grouped by type, for the donut chart. Each slice is named with the type's label from
the table below (`"Flood"`); until 23 Sep an event the pipeline made was drawn as a grey
`"URBAN_FLOOD"` slice (BUG-062).

### Event types

Sixteen since 23 Sep (migration `0011`), described in one place: `app/services/hazards.py`.
**Since Phase 3 (written, not yet tested) an event's type is the majority of its reports' tagged
hazards** (`services/hazard_tagger.py`, rules in English, Hindi and Hinglish), ties by precedence;
with no votes it is `UNCLASSIFIED`, which is never auto-published. Until Phase 3 is deployed every
event the pipeline makes is still `URBAN_FLOOD`.

Two types with the same precedence are ordered as listed: the specific one first (lightning and hail
before the thunderstorm that brings them, a cloudburst or storm surge before the flood it causes).

| `event_type` | Label | Family | Precedence |
|---|---|---|---|
| `CLOUDBURST` | Cloudburst | water | 1 |
| `CYCLONE_INUNDATION` | Storm surge | water | 1 |
| `URBAN_FLOOD` | Flood | water | 1 |
| `RIVER_BREACH` | River flood | water | 2 |
| `LANDSLIDE` | Landslide | water | 3 |
| `CYCLONE` | Cyclone | convective | 3 |
| `DUST_STORM` | Dust storm | convective | 4 |
| `LIGHTNING` | Lightning | convective | 5 |
| `HAILSTORM` | Hailstorm | convective | 5 |
| `THUNDERSTORM` | Thunderstorm | convective | 5 |
| `STRONG_WIND` | Strong Winds | convective | 6 |
| `HEATWAVE` | Heatwave | thermal | 7 |
| `COLD_WAVE` | Cold wave | thermal | 7 |
| `FOG` | Fog | visibility | 8 |
| `RAINFALL` | Heavy Rainfall | water | 9 |
| `UNCLASSIFIED` | Unclassified | — | 99 |

A **family** decides which reports may cluster together (Phase 3); **precedence** names a mixed
cluster for its impact rather than its cause (a flood beats the rain). The labels the dashboard
already keys on are unchanged: `Flood`, `Thunderstorm`, `Strong Winds`, `Fog`, `Heavy Rainfall`.

Source types: `CITIZEN_APP`, `OFFICIAL_DISPATCH`, `AWS_SENSOR`, `CWC_GAUGE`, `TWITTER_IMD`, and since
23 Sep `SOCIAL_MEDIA` and `NEWS_MEDIA` (for Phase 2's Mastodon and news feeds). `AWS_SENSOR`,
`CWC_GAUGE` and `TWITTER_IMD` are declared only: nothing produces them.

### `GET /api/events/{event_id}`

Accepts the UUID **or** the `event_code`. Returns the full event, including:

| Field | Note |
|---|---|
| `confidence_score` | 0–1, re-normalised over the factors that reported |
| `verification_receipt` | see below |
| `boundary_geojson` | **always populated** — a `Polygon` containing every contributing report |
| `review_status` | `AUTO_PUBLISHED` · `PENDING_HUMAN_REVIEW` · `QUARANTINED` · `REJECTED` · `HUMAN_APPROVED` |
| `verification` (display label) | `verified` for `AUTO_PUBLISHED` **and** `HUMAN_APPROVED` · `under-review` for pending/quarantined · `rejected` |

Unknown id or code → `404 {"detail": "Event not found"}`; database error → `503`.

### The Verification Receipt

The receipt is the product. It explains every number it states.

A worked example: the engine's output for five scripted test reports on 20 Sep. The script, the
reports and the event have since been deleted; the arithmetic is the point.

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
`vision_analysis` (0.15) and `anomaly_detection` (0.05) did not contribute to this historical
fusion receipt. The later frozen image and anomaly components produce separate advisory results,
not calibrated replacements for these fusion factors. **Never display the score without the coverage.**

`verification_receipt.ml_event_grouping`, when present, contains advisory candidate grouping from
the frozen deterministic event component. It does not change `review_status` or confirm an event.

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

#### Phase 3 additions to the receipt (written, not yet tested)

```json
"event_type_basis": {"rule": "majority of report hazards, ties by precedence",
                     "votes": {"URBAN_FLOOD": 4, "RAINFALL": 1}, "reports_voting": 5,
                     "reports_untagged": 0, "citizen_choice_used": 0,
                     "override": {"event_type": "FOG", "machine_vote": "URBAN_FLOOD",
                                  "operator_id": "…"}},
"severity_basis": {"rule": "max(content_axis, count_axis, impact_floor)",
                   "axis": "thermal_heat", "value": 46.0, "phrase": "46 degree",
                   "content_axis": "HIGH", "count_axis": "MODERATE",
                   "impact_floor": {"severity": "HIGH", "phrase": "heatstroke"},
                   "event_type": "HEATWAVE", "report_count": 5,
                   "max_depth_cm": null, "depth_basis": null, "reports_with_depth": 0,
                   "depth_axis": "ADVISORY"},
"density_basis": {"reports": 5, "distinct_reporters": 5, "n_eff": 4.79, "excluded": 0,
                  "unverified_reporters": 0, "publishers": 0, "baseline": 0.6, "rule": "…"},
"routing": {"review_status": "PENDING_HUMAN_REVIEW", "basis": "cap", "caps": ["posts_only"], …},
"cluster": {…, "eps_km": 25.0,
            "clustering": {"family": "thermal", "eps_km": 25.0, "window_hours": 24,
                           "search_m": 75000.0, "candidates": 7, "context_attached": 0,
                           "elapsed_ms": 4.2}},
"weather": {"note": "rainfall does not corroborate this hazard; per-hazard weather evidence arrives in Phase 4"}
```

* **`event_type_basis`**: the vote that typed the event. `override` appears only once a commander
  has set the type; the event keeps it through later merges.
* **`severity_basis.axis`** is the measure that graded it: `water_depth`, `water_rain`,
  `thermal_heat`, `thermal_cold`, `visibility`, `convective_wind`, or `none` (UNCLASSIFIED). `value`
  and `phrase` are the reading and the words it came from; `impact_floor` is set when words like
  "stranded" (HIGH) or "died" (CRITICAL) raised the grade. The depth keys are kept for existing
  readers.
* **`density_basis`**: Report Density now scores `n_eff`, the effective independent reporters
  (one device counts once; a news publisher counts once; forecasts are excluded; a flagged report
  counts less). Show it as "5 reports, 4.8 independent witnesses".
* **`routing.caps`**: `unclassified` or `posts_only` hold an event for a human whatever its
  confidence; `basis` is `cap` when that is why it is pending.
* **`weather.note`** (Phase 3 only, **gone in receipt v2**): for a hazard rainfall cannot
  corroborate the weather factor was `offline`, with this note. Since Phase 4 every hazard reads its
  own variable instead; an older stored receipt may still carry the note.

#### Phase 4: receipt v2 (tested 27 Sep)

`receipt_version: 2`. Seven factors, weights still summing to 1.00:

| `key` | `factor` label | v1 | v2 |
|---|---|---|---|
| `weather_station` | Weather Station Corroboration | 0.25 | **0.20** |
| `official_warning` | Official Warning (IMD/SDMA via SACHET) | — | **0.10** |
| `report_density` | Report Density Analysis | 0.20 | 0.20 |
| `spatial_coherence` | Spatial Coherence Score | 0.20 | **0.15** |
| `vision_analysis` | Computer Vision Analysis (offline, layer 4) | 0.15 | 0.15 |
| `source_reliability` | Source Reliability Index | 0.15 | 0.15 |
| `anomaly_detection` | Anomaly Detection Signal (offline, layer 4) | 0.05 | 0.05 |

With vision and anomaly offline, **`factor_coverage` is still 0.80**; with SACHET stale as well,
0.70. `total_weighted / factor_coverage = confidence_score` still holds exactly. Each factor row
gains `key`, and the two independent factors gain `source`:

```json
{"key": "weather_station", "factor": "Weather Station Corroboration", "weight_pct": 20.0,
 "state": "computed", "score": 0.85, "weighted_points": 0.17, "source": "airport_metar",
 "evidence": "IMD airport observation VIDP (Indira Gandhi Intl, 14 km): FG, visibility 150 m at 11:00 IST; Open-Meteo model: minimum visibility 400 m at 05:00 UTC in 03:00–09:00 UTC (08:30–14:30 IST)"}
```

New top-level blocks:

```json
"evidence": {
  "weather_station": {"score": 0.85, "state": "computed", "variable": "minimum visibility",
                      "value": 150, "window": "03:00–09:00 UTC (08:30–14:30 IST)",
                      "source": "airport_metar", "contradiction": false, "reason": "…",
                      "detail": {"station": {…}, "model": {…}, "lines": ["…", "…"]}},
  "official_warning": {"score": 0.85, "source": "sachet_cap",
                       "reason": "IMD Patna: Severe Heavy Rainfall warning in force until 28 Sep 08:30 IST (SACHET CAP, matched by polygon)",
                       "detail": {"in_force_covering": [{"identifier": "…", "sender": "…", "event": "…",
                                  "raw_severity": "Severe", "score": 0.85, "families": ["water"],
                                  "matches_hazard": true, …}]}}},
"evidence_window": {"start": "…", "end": "…", "rule": "the observed span ± 3 h", "label": "…"},
"contradictions": [{"factor": "weather_station", "rule": "maximum below 35 °C (plains)",
                    "reason": "airport VIDP (…, 14 km) measured a maximum of 26.7 °C in …"}],
"verdict": {"value": "CONTRADICTED", "rule": "…", "reason": "…", "official_warning": 0.0,
            "weather": 0.0, "contradictions": 1},
"news_basis": {"score": 0.75, "count": 3, "publishers": ["Telangana Today", "The Hindu", "Times of India"],
               "line": "reported by 3 independent publishers: …", …},
"late_corroboration": {"trigger": "sachet:<identifier>@<sent>", "at": "…", "before": {…}}
```

* **`evidence.*.source`**: `airport_metar` (an aerodrome's METAR within 50 km; "IMD" is said only
  for civil airports), `open_meteo_model`, `sachet_cap`, or `none` (offline).
* **Every hazard reads its own variable** — temperature for heat and cold, visibility for fog,
  gusts for wind, weather code and CAPE for thunderstorms, dust for a dust storm, the peak hour for a
  cloudburst, 24 h rainfall for floods (unchanged). `weather.note` is gone: no hazard is
  `offline` merely because rainfall cannot speak to it.
* **`contradictions`**: non-empty only when the evidence affirmatively says the opposite (the
  published table is in `backend/app/services/evidence.py`). The weather factor then scores 0.0,
  online, and `routing.caps` gains `contradicted`. **Never an automatic rejection.**
* **`verdict`**: `CONTRADICTED` if any contradiction; else `CORROBORATED` if `official_warning` or
  the weather evidence is ≥ 0.6; else `UNCONFIRMED`. Also stored as the event's `verdict` column.
* **`news_basis`**: news counts as corroborated (0.75 in Source Reliability) only from two or more
  independent publishers; one publisher is 0.55.
* **`late_corroboration`**: present when the event was re-scored because a warning or an airport
  observation arrived after it; `before` is the confidence, verdict, status and severity it had.

### `PATCH /api/events/{event_id}/review` — **requires a token**

Auth: `COMMANDER` or `ADMIN`.

```json
{ "action": "approve" | "reject" | "override_severity" | "override_event_type",
  "reason": "5 to 1000 characters",
  "new_severity": "ADVISORY|MODERATE|HIGH|CRITICAL",
  "event_type": "one of the 16 event types" }
```

| Action | Effect |
|---|---|
| `approve` | From `QUARANTINED`/`PENDING_HUMAN_REVIEW` → `HUMAN_APPROVED`. Quadrant becomes `Critical Verified Event` if HIGH/CRITICAL, else `Confirmed Minor Event`. Audit `HUMAN_APPROVE` |
| `reject` | From anything but `REJECTED` → `REJECTED`. Drops out of the list, still served by detail. Audit `HUMAN_REJECT` |
| `override_severity` | Status unchanged, quadrant recomputed. `new_severity` required. Audit `MANUAL_OVERRIDE` |
| `override_event_type` | **Phase 3.** Status and severity unchanged; `event_type` required. Audit `MANUAL_OVERRIDE` with `details` `{field: "event_type", from, to}`. The type survives later merges; the receipt keeps the machine's vote beside it. `EVENT_REVIEWED` carries `event.event_type` |

**`confidence_score` is never changed by a review.** The machine's reading and the human's
decision are recorded separately, on purpose.

`200` the updated event · `401` no/invalid/expired token · `403` analyst or citizen · `404`
unknown id · `409` transition not allowed, nothing written · `422` bad body · `503` database
error. Row-locked, so two concurrent approvals give one `200` and one `409`. Broadcasts
`EVENT_REVIEWED` after the commit.

**Phase 4 (tested 27 Sep):** a decision releases the event's review claim
(`EVENT_REVIEWED` gains `claim_released: true`). While **another** commander holds an unexpired
claim, a commander's decision is a `409` naming the holder; an `ADMIN` may still decide.

### `POST /api/events/{event_id}/claim`, `DELETE /api/events/{event_id}/claim` — **requires a token** (Phase 4)

Auth: `COMMANDER` or `ADMIN`. Tested 27 Sep (`test_review_queue.py`).

`POST` takes the event for review for **15 minutes**:

```json
{"event_id": "…", "event_code": "INDRA-20260927-004",
 "claim": {"operator_id": "OP-CMD-001", "claimed_at": "…", "expires_at": "…"}}
```

* Someone else holds an unexpired claim → **`409`**, `detail: {"message": "Claimed by OP-CMD-001
  until …", "claim": {…}}`. The holder claiming again renews it. After 15 minutes anyone may claim.
* A `REJECTED` event → `409`. Unknown id → `404`.
* `DELETE` releases it: the holder or an `ADMIN`; another commander gets the `409`. Releasing an
  event nobody holds is a `200` with `claim: null`.
* Both broadcast **`EVENT_CLAIMED`** (below). `GET /api/events/{id}` shows the current `claim`
  (`null` when nobody holds an unexpired one).

### `GET /api/events/{event_id}/history` — **requires a token** (Phase 4)

Auth: `ANALYST`, `COMMANDER` or `ADMIN`. Tested 27 Sep. One timeline, oldest first:

```json
{"event": {"id": "…", "event_code": "…", "confidence_score": 0.71, "verdict": "CORROBORATED",
           "review_status": "PENDING_HUMAN_REVIEW", "severity": "HIGH", "verified_at": "…"},
 "snapshots": 4, "audit_rows": 3,
 "timeline": [
   {"kind": "snapshot", "at": "…", "confidence_score": 0.52, "factor_coverage": 0.8,
    "report_count": 3, "verdict": "UNCONFIRMED", "review_status": "QUARANTINED",
    "severity": "MODERATE", "trigger": "created", "receipt_version": 2, "details": {…}},
   {"kind": "audit", "at": "…", "seq": 812, "action_taken": "QUARANTINE",
    "operator_id": "SYSTEM-PIPELINE", "reason": "…", "details": {…}},
   {"kind": "snapshot", "trigger": "late:sachet:<identifier>@<sent>", …},
   {"kind": "audit", "action_taken": "LATE_CORROBORATION", "details": {"trigger": "…", "before": {…}, "after": {…}}, …}
 ]}
```

A snapshot is written on every score write: `created`, each `merge`, each `late:…` re-score, and
`late:backfill:receipt_v2`. A review is not a score change, so it appears as its audit row only.
Draw "confidence over time" from the snapshots; the status history from both.

### `GET /api/events/{event_id}/provenance` — **requires a token**

Auth: `ANALYST`, `COMMANDER` or `ADMIN`.

```json
{ "event": {...},
  "reports": [{id, source_type, raw_text, latitude, longitude, credibility_score, created_at,
               submitted_by, platform, publisher, url, place_precision, hazard_primary, flags,
               flag_basis}],
  "audit":   [{seq, action_taken, operator_id, reason, details, logged_at, sha256_hash, prev_hash}],
  "chain":   {"valid": true, "checked": 12, "broken_at_seq": null} }
```

Reports oldest first; audit rows in chain order. **Phase 3:** a post or headline that joined the
event shows its `platform`, `publisher` and `url` (null for a citizen report); every report shows
its `hazard_primary`, its `flags` and why each was set (`flag_basis`), and its `place_precision`.
A forecast linked as context carries `not_an_observation` and is not counted as a witness. **`chain` verifies the whole ledger from
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
| `GET /api/profile/me`, `PATCH /api/profile/me` | 401 | 401 | 200 | 200 | 200 | 200 |
| `GET /api/reports/search`, `/export` (Phase 2) | 401 | 401 | 403 | 200 | 200 | 200 |
| `GET /api/events/export` (Phase 2) | 401 | 401 | 403 | 200 | 200 | 200 |
| `POST`/`DELETE /api/events/{id}/claim` (Phase 4, `test_review_queue.py`; the expired-key column is not pinned) | 401 | 401 | 403 | 403 | 200 | 200 |
| `GET /api/events/{id}/history` (Phase 4, `test_review_queue.py`; the expired-key column is not pinned) | 401 | 401 | 403 | 200 | 200 | 200 |
| `GET /api/review/queue` (Phase 4, `test_review_queue.py`; the expired-key column is not pinned) | 401 | 401 | 403 | 200 | 200 | 200 |
| `POST /api/reports/submit` | 202 | 202 | 202 | 202 | 202 | 202 |
| `GET /api/events` | 200 | 200 | 200 | 200 | 200 | 200 |

`/api/profile/me`, read or edited, is **the token's own operator only**; there is no `?user=`
parameter.

---

## `/api/review` (Phase 4)

### `GET /api/review/queue?tab=pending&limit=50&offset=0` — **requires a token**

Auth: `ANALYST`, `COMMANDER` or `ADMIN` (claiming and deciding need `COMMANDER` or `ADMIN`).
Tested 27 Sep (`test_review_queue.py`).

| `tab` | Contents |
|---|---|
| `pending` | `PENDING_HUMAN_REVIEW` or `QUARANTINED`, never reviewed |
| `contradicted` | verdict `CONTRADICTED`, never reviewed |
| `suspicious` | at least one contributing report flagged (`promotional`, `past_event`, `implausible_value`, `exaggeration`, `shouting`, `forward_marker`, `coordinated`; a forecast's `not_an_observation` is not suspicious) |
| `high_impact` | severity `HIGH` or `CRITICAL`, never reviewed |
| `recent` | created in the last 2 hours |
| `claimed` | someone holds an unexpired claim |

"Never reviewed" means no commander has acted on it. `REJECTED` events are in no tab. **Order,
published:** severity (critical first), then verdict (`CORROBORATED`, `UNCONFIRMED`,
`CONTRADICTED`), then age, oldest first.

```json
{"tab": "pending", "total": 7, "limit": 50, "offset": 0, "order": "…",
 "items": [{"id": "…", "event_code": "…", "event_type": "HEATWAVE", "label": "Heatwave",
            "family": "thermal", "severity": "HIGH", "confidence_score": 0.44,
            "factor_coverage": 0.8, "verdict": "CONTRADICTED", "review_status": "PENDING_HUMAN_REVIEW",
            "district": "…", "state": "…", "verified_at": "…", "age_minutes": 38.5,
            "report_count": 5, "flagged_reports": 0, "contradictions": [{…}], "claim": null}]}
```

`?counts=true` returns `{"pending": 7, "contradicted": 2, "suspicious": 1, "high_impact": 4,
"recent": 3, "claimed": 0}` in one call. An unknown `tab` is a `422` naming it; a database error
`503`.

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

### `GET /api/geo/stations` (24 Sep)

Every rainfall station with its newest reading and the last 48 h, one row per observation hour
(the poller stores each hour several times), wettest first. `rainfall_mm` is the trailing 24 h
accumulation; `0.0` is a measured dry day. Today these are six **Open-Meteo model points**
(`agency: OPEN_METEO`), not IMD gauges. A station silent for 48 h is left out. `503` on a database
error. **Phase 2:** rows with no rainfall amount (the airport observations now in the same table)
are left out, so this list stays what it was; they are served by `/api/stations/latest`.

```json
[{"station_code": "OM-KOLKATA", "station_name": "Kolkata", "agency": "OPEN_METEO",
  "lat": 22.5726, "lng": 88.3639, "rainfall_mm": 24.2, "recorded_at": "2026-09-24T04:00:00+00:00",
  "series": [{"at": "2026-09-23T17:00:00+00:00", "rainfall_mm": 19.8}, …]}]
```

---

## `/api/stations` (Phase 2 T3)

### `GET /api/stations/latest?feed=metar&max_age_hours=3`

The newest observation from each station of one feed, for a map layer. `feed=metar` is India's
aerodromes (about 105 reporting on 24 Sep): **observed** weather from each airport's METAR, not a
model. `feed=open_meteo` is the six modelled rainfall points. A station whose newest reading is
older than `max_age_hours` (1–48, default 3) is left out rather than drawn with an old number.
Open. `422` for another `feed`, `503` on a database error.

The example is the real 24 Sep 05:30 UTC Delhi report from the test fixture, parsed as the code
parses it (11009KT → 9 kt × 1.852 = 16.7 km/h); it was not captured from a running stack.

```json
{"feed": "metar", "generated_at": "…", "max_age_hours": 3, "count": 105,
 "stations": [{"station_code": "VIDP", "station_name": "New Delhi/Gandhi Intl", "agency": "AERODROME_METAR",
   "feed": "metar", "lat": 28.567, "lng": 77.117, "recorded_at": "2026-09-24T05:30:00+00:00", "age_minutes": 22,
   "temperature_c": 31.0, "dewpoint_c": 24.0, "wind_kmh": 16.7, "gust_kmh": null, "visibility_m": 5000,
   "weather_codes": ["HZ"], "convective_cloud": false, "rainfall_mm": null,
   "raw_observation": "METAR VIDP 240530Z 11009KT 5000 HZ FEW030 31/24 Q1010 NOSIG"}]}
```

`visibility_m` 10,000 means "10 km or more". `weather_codes` is present weather only, normalised:
`+TSRA` → `["TS", "RA+"]`, `VCTS` (a storm in the vicinity) stays `["VCTS"]`. `rainfall_mm` is
`null` because a METAR carries no rainfall amount. `agency` is `AERODROME_METAR`, not `IMD`: some
Indian METAR stations are military airfields.

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

**Phase 4 (tested 27 Sep):** `verdicts`, `[{"value": "CORROBORATED", "count": n}, …]`
in the order CORROBORATED, UNCONFIRMED, CONTRADICTED, over non-rejected events that have a
verdict.

Empty database: every list `[]` and both dates `null`. Cached for **60 s** (Redis key
`meta:filters`, with an in-memory fallback), so a new event can take up to a minute to appear in the
options; it appears in the list at once. `503` on a database error, never invented options.

### `GET /api/meta/sources` (Phase 2 T2)

Whether each feed is alive. Since Phase 2 each poller records a **heartbeat** at the end of every
tick (`feed_status`), and `status` is read from it:

| `status` | When |
|---|---|
| `ok` | the last successful tick is within 3 poll intervals; a push feed is always `ok` |
| `stale` | no successful tick for 3 × `poll_interval_s` (`stale_after_s`), or never one yet |
| `failing` | the last 3 ticks failed in a row; `last_error` says why |
| `disabled` | the poller's setting is off |

`basis` is `heartbeat` for a poller and `push` for the intake routes (citizen, official), whose
`last_success_at` is the newest report received. `rows_24h` and `rows_total` are counted from the
table each feed writes to; `newest_row_at` is that table's newest row (what `last_success_at` meant
before the heartbeat). `last_attempt_at`, `last_error_at`, `consecutive_failures` and
`items_last_tick` come from the heartbeat. `dead_letters` counts the report-stream messages the
pipeline gave up on (Phase 2 T8); `0` is healthy.

```json
{"generated_at": "…",
 "feeds": [
  {"feed": "metar", "kind": "station", "title": "Airport weather (METAR)", "enabled": true, "status": "ok",
   "last_success_at": "…", "last_attempt_at": "…", "last_error": null, "last_error_at": null,
   "consecutive_failures": 0, "items_last_tick": 104, "newest_row_at": "…", "rows_24h": 4800,
   "rows_total": 9120, "poll_interval_s": 600, "stale_after_s": 1800, "basis": "heartbeat"}, …],
 "dead_letters": {"total": 0, "last_at": null, "last_error": null, "topic": "indra.raw.reports.dlq"}}
```

Feeds, in order: `citizen`, `official`, `sachet`, `open_meteo`, `metar`, `mastodon`, `google_news`.
`503` on a database error (including a database not yet migrated to `0015`).

---

## `/api/dashboard`

### `GET /api/dashboard/summary`

KPI counts for the dashboard cards: total reports, verified events, critical events and citizen
reports, each with a 24-hour delta percentage (**since Phase 2, `total_reports` also counts the
posts and headlines the pollers collect; `citizen_reports` does not**), plus `awaiting_review` (escalated or quarantined)
and `active_alerts` (unexpired SACHET warnings). `verified_events` counts only `AUTO_PUBLISHED` and
`HUMAN_APPROVED` (BUG-034). Every number comes from the database.

---

## `/api/feed`

### `GET /api/feed/recent?limit=10&include=reports,events,warnings`

What has just happened, newest first, merged from three streams (24 Sep, BUG-071):
`report` (a stored report), `event` (an event formed, not rejected) and `warning` (an official
warning **in force**). `include` narrows the streams; the default is all three. Every item keeps the
old fields (`id`, `source`, `sourceLabel`, `message`, `time`) and adds `kind`, `at` (ISO 8601) and,
where they apply, `place`, `severity`, `status`, `event_id`. `time` is **IST** `HH:MM`; it was the UTC
clock time until 24 Sep. `source` is `citizen`, `official`, `social`, `news`, `event` or `warning`.

```json
[{"id": "warning-97403024-…", "kind": "warning", "source": "warning", "sourceLabel": "Odisha-SDMA",
  "message": "Moderate Rain , Thunderstorm, lightning and wind speed 40 -50 kmph is very likely …",
  "place": "5 districts of Odisha", "severity": "HIGH", "at": "2026-09-24T04:55:18+00:00", "time": "10:25"},
 {"id": "44d18dd5-…", "kind": "report", "source": "citizen", "sourceLabel": "Citizen report",
  "message": "Water rising fast near Gandhi Maidan, knee deep on the road.", "place": "Patna, Bihar",
  "status": "pending", "at": "2026-09-21T14:57:17.653497+00:00", "time": "20:27"}]
```

A report's `status` is `pending`, `in_event` or `duplicate`. **Phase 2:** a collected item's
`sourceLabel` is `Mastodon` for a post and the publisher's name for a headline (`"The Hindu"`), and it
carries `platform` (`mastodon`, `google_news`).

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

```json
{"access_token": "eyJ…", "token_type": "bearer", "role": "COMMANDER", "agency": "SDMA_BIHAR",
 "operator_id": "OP-CMD-001", "username": "commander", "expires_in": 28800}
```

A real HS256 JWT whose claims are `sub` (the username), `role`, `agency`, `operator_id`, `iat` and
`exp`.
`expires_in` is in seconds, `JWT_EXPIRY_HOURS` × 3600: 28,800 at the default 8 h.

| Code | When |
|---|---|
| `200` | Signed in |
| `401 {"detail": "Incorrect username or password"}` | A wrong password, an unknown username, or an account with no password set: one answer for all three |
| `503` | Database error |

**Accounts** are the rows of `user_profiles`, one per operator, with role `ADMIN`, `COMMANDER`,
`ANALYST` or `CITIZEN`. The password is stored only as a bcrypt hash in `password_hash` (migration
`0019`), which no read endpoint returns; `NULL` means the account cannot sign in. No password is
written in the source, in this file or in the dashboard. Until 25 Sep four fixed demo passwords
were listed here and shipped in the dashboard (BUG-093); they are still in git history, so every
deployed account needs a new one.

Passwords are set per environment with one script, run from the repo root:

```bash
backend/.venv/bin/python scripts/set_operator_password.py commander          # prompts twice
backend/.venv/bin/python scripts/set_operator_password.py --all --generate   # prints each new password once
backend/.venv/bin/python scripts/set_operator_password.py --all --from-env INDRA_OPERATOR_PASSWORD
```

`scripts/set_operator_password.py [USERNAME ...] [--all] [--from-env VAR | --generate]` writes to
`DATABASE_URL` from the environment, else the backend's settings and `.env`, and prints the host,
port and database it is about to change, never the password. It refuses a username with no row in
`user_profiles` (exit 2; it does not create accounts) and a password shorter than 10 characters.
With neither `--from-env` nor `--generate` it prompts twice with `getpass`.

**Deploying this to a server:** run `alembic upgrade head` (it adds `0018` and `0019`), **then set
the passwords**. No hash is seeded, so until the script has run every sign-in is a `401`.

---

## `/api/teams` and `/api/profile`

`GET /api/teams` · `GET /api/teams/{id}` · `POST /api/teams` (201) ·
`PATCH /api/teams/{id}/assign` · `GET /api/teams/hackathon/sixth-sense`

`GET|PATCH /api/profile/me` · `GET /api/profile/activity?user=<username>` ·
`GET /api/profile/operators`

Reads are open, except `GET /api/profile/me`: it is the signed-in operator's own record, so it
needs a token (`401` without one or with an invalid one; `404` if the token's user has no profile
row). `GET /api/profile/activity` needs `user` (`422` without it, `404` for a username with no
profile) and lists that operator's audit-ledger actions, `[]` until they have reviewed something.
`/api/profile/preferences` was removed on 25 Sep: it was a per-process store that nothing read and a
restart lost; the dashboard keeps its settings in the browser. Writes need a token (matrix above):

| Endpoint | Codes |
|---|---|
| `POST /api/teams` | `201` · `409` duplicate `team_code` · `422` unknown agency or status, or no `members_count` (1–1000; there is no default head-count) · `503` |
| `PATCH /api/teams/{id}/assign` `{event_id: uuid \| null}` | `200 {team_id, assigned_event_id, status, assigned_by}` · `404` team or event not found · `422` malformed `event_id` · `503` |
| `PATCH /api/profile/me` | `200` the saved profile · `422` unknown `duty_status` · `503` when the write fails |

Until 22 Sep a failed dispatch answered `200 "Updated in demo store"` from an in-memory list, and a
failed profile edit answered `200` after `except: pass`. Both now fail loudly.

A profile holds only what was recorded. The four accounts migration `0008` seeds (`admin`,
`commander`, `analyst`, `citizen`) have `badge_number`, `callsign` and `team_role` `null` since
`0018`, the citizen's `agency` is `PUBLIC`, and `full_name` is the role's title (`Incident
Commander`). A client shows an absent field as absent.

---

## Top level

| Endpoint | Behaviour |
|---|---|
| `GET /` | Redirects to the dashboard on :3000 |
| `GET /api/info` | Platform metadata: `platform`, `tagline`, `version`, `sih_ps_id`, `team`. No `status` since 25 Sep: it said `operational` whatever Postgres or Kafka were doing. Whether the platform is up is `/healthz`'s answer |
| `GET /healthz` | Real dependency check — see below |
| `WS /ws/events` | The live stream |
| `GET /api/e2e/identity` | **Only on a backend started with `ENVIRONMENT=e2e`**; a `404` in every other mode. See below |

### `GET /api/e2e/identity` — E2E mode only

`{"environment": "e2e", "database": …, "reports_topic": …, "consumer_group": …}`, where `database`
is `SELECT current_database()`. The browser tests read it before they start and refuse to run
unless it names a database ending in `_e2e`, an `indra.e2e.` topic and an `indra-e2e-` consumer
group. A backend with `ENVIRONMENT=e2e` refuses to start unless its database name ends in `_e2e`,
its report, event and dead-letter topics start with `indra.e2e.`, `KAFKA_CONSUMER_GROUP` starts
with `indra-e2e-` and the lake archive is off. So a browser test can never write into `indra_db`,
take messages from the dev consumer or archive into the real lake. `503` on a database error. `make e2e-backend` starts one on
`127.0.0.1:8100` against `indra_e2e`.

### `GET /healthz`

Checks Postgres (**including whether the schema exists**), Kafka/Redpanda, Redis, Open-Meteo,
the outbox backlog and (Phase 2) the **object store** concurrently, each capped at 2 s.

| Status | HTTP | When |
|---|---|---|
| `healthy` | 200 | everything up |
| `degraded` | 200 | Redis, Open-Meteo or the object store is down (or the store is not configured), or a report has waited more than 60 s for Kafka — none of these loses anything |
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
| `VERIFIED_EVENT` | `{type, event}` | The pipeline created or updated an event. **Phase 4:** also when late corroboration re-scored one (`event.late_corroboration` says by what); `event.verdict` on every one |
| `EVENT_REVIEWED` | `{type, event, review, claim_released}` | A commander approved, rejected or re-graded one. `claim_released` (Phase 4) is true when the decision released a review claim |
| `EVENT_CLAIMED` | `{type, event: {id, event_code}, claim}` | **Phase 4.** A commander claimed an event for review; `claim` is `{operator_id, claimed_at, expires_at}`, or `null` with `released_by` when it was released. Show "being reviewed by …" |
| `NEW_FEED_ITEM` | `{type, report}` | **Phase 2.** A poller collected a post or headline. Same payload as `NEW_REPORT` (`source_type` `SOCIAL_MEDIA` or `NEWS_MEDIA`; `latitude`/`longitude` may be `null`). A separate type so a news tick storing dozens of headlines does not fire dozens of `NEW_REPORT` refetches; a dashboard that ignores it is unaffected |

`report` carries `raw_text`, `h3_res8`, `credibility_score` and `source_type`. The key is
`raw_text`, **not** `text`. Its keys are exactly the nine the Kafka message has always had; the
docket, the reporter hash and feed metadata are never added, because this message goes to every
connected browser.

> Fan-out is in-process by design, so **run one backend process**. Two backends against one broker
> will re-deliver reports (BUG-011).

---

## Proposed — Phase 4, 5 and 6

Phase 2's four are built (above), and Phase 4's four are written (above: the review queue,
claiming, history and `?verdict=`; tested 27 Sep). **The rest are not built yet.** These are the
names later phases will use, published now so the dashboard can be built against them. Shapes will
be fixed in this file when each one lands; until then treat everything but the path as
provisional.

| Phase | Endpoint | For |
|---|---|---|
| 5 | `POST /api/reports/submit` as multipart | Photo and video upload |
| 5 | `GET /api/media/{id}` | A report's media |
| 5 | `DELETE /api/reports/{docket}` | A citizen withdrawing their own report |
| 5 | `GET /api/admin/sources` | Per-source credibility |
| 6 | `GET /api/analytics/kpis`, `/timeseries`, `/by-state`, `/latency`, `/verification-funnel` | The analytics page |
| 6 | `POST /api/ingest/batch` | Bulk import of real archives; a load test only ever against an isolated test backend |

---

## Empty and unavailable

There is no demo mode. `DEMO_MODE`, `core/demo.py` and every hardcoded payload behind them were
deleted on 25 Sep (history: BUG-024, BUG-045, BUG-069); a `DEMO_MODE` line left in an old `.env`
is ignored. Every read answers from the database or not at all:

| Case | Answer |
|---|---|
| No rows | The real empty result: `[]`, all-zero KPIs on `/api/dashboard/summary`, `cells: []` on the heatmap, and N days at `0` on `/api/reports/trend` |
| Unknown id | **404** on a detail endpoint (`/api/events/{id}`, `/api/teams/{id}`) |
| Database error | **503 `{"detail": "Database unavailable"}`** |

`app/core/empty.py::empty_or_503(endpoint, empty, error=None)` is the one place that decides it,
and it logs a WARNING whenever it is reached: `<endpoint>: no rows — returning empty result`, or
`<endpoint>: database error — returning 503: <err>`. `/api/dashboard/summary`, `/api/events`,
`/api/events/distribution`, `/api/events/{id}`, `/api/feed/recent`, `/api/reports/trend`,
`/api/reports/recent`, `/api/geo/heatmap`, `/api/teams` and `/api/teams/{id}` go through it.

An empty dashboard that fills as reports and feed rows arrive is both honest and the better
demonstration. Until 20 Sep an empty database answered `GET /api/events` with a fabricated
`0.94 / AUTO_PUBLISHED / CRITICAL` event, a value the engine cannot produce (BUG-024).

---

## When you add an endpoint

1. Put the contract here in the same shape, before merging.
2. If the dashboard must change, write it into [`frontend-handover.md`](frontend-handover.md).
3. It serves only what the database holds: no rows → the empty result or `404`, a database error
   → `503`, through `empty_or_503()`, with a case in `tests/test_empty_and_unavailable.py`.
