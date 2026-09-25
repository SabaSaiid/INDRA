# Handover — Backend → Dashboard

**From:** Aditya (layers 1–3, 5, 6, 7, 8a) · **To:** whoever owns `INDRA/frontend/`
**Covers:** every backend change from 16–23 Sep 2026 that the dashboard can see, and — new on
22 Sep — **what was changed inside `frontend/` that day, and why** (section 0). **New on 23 Sep:
section 13, Phase 1** — sixteen event types, the PS's filters, citizen dockets, and no lost reports.
**New on 24 Sep: section 14** — a browser test the map redesign broke, and the frontend team's
backend report, checked — **and section 15**: the dashboard shows its own review status instead of
the API's, so a commander's approval never appears. **Also 24 Sep: the team server is on HTTPS** at
`https://indra-sixthsense.duckdns.org` (section 13, last row). **Also new on 24 Sep: section 16**
— Aditya repaired seven dashboard pages inside `frontend/` (his go-ahead for that day), which also
closes section 15. Please read 16 before your next merge into `frontend/`.

**Up to 20 Sep, `frontend/` was never touched from the backend side.** On 21 Sep that changed, on
request: PRs #25 and #27 carry `fix(9)` / `feat(9)` / `refactor(frontend)` commits that removed
the mock-data fallbacks, added the live map layers and self-refresh, and fixed BUG-043/044 (see
`git log --author=kraditya9241 -- frontend/`). On 22 Sep, again on request, a larger set of
frontend fixes followed — section 0 lists every one. This file supersedes the three notes that used to live in `aditya/`
(`handover-verified-event-ws.md`, `handover-review-provenance.md`,
`handover-20sep-geo-and-confidence.md`); they stay where they are as history.

Most of this is new data you can use. The two items that needed a change — item 8 (`ADVISORY`)
and item 12 (the production build) — are **done** as of 22 Sep, as is item 11 (gating the API).
Item 9 is visible whether you act on it or not.

Full endpoint shapes: [`api-contract.md`](api-contract.md).

---

## 0. What changed in `frontend/` on 22 Sep, and why

Every change below is a separate commit on `aditya_22sep_c`, with the reason in its message.
The common thread: **the dashboard showed things INDRA does not have.** The 21 Sep work removed
invented data that arrived through fallbacks; these were constants written straight into pages,
which no fallback test could see. They were found by reading every page.

**Invented content removed**

| Where | What it showed | What it shows now |
|---|---|---|
| Warnings page (`alerts/page.tsx`) | Four hardcoded bulletins credited to IMD, the Cyclone Warning Division, GSI and CWC ("Cyclone Marut", "port signal 8 hoisted"); any HIGH/CRITICAL event, quarantined ones included, as an NDMA "CRITICAL WARNING" with a canned evacuation order; "CAP-INDIA BROADCAST ONLINE" | Real SACHET warnings (`GET /api/alerts/agency`) in the issuer's words, and severe INDRA events labelled *"not an official warning"* with their true review status |
| Map (`GlobeEventMap.tsx`) | A "Cyclone DANA — Forecast Track", six "NDRF Operational Bases" (one mislabelled), and for every pin "AI Verified", "Rainfall 86 mm/h", "Wind Gusts 68 km/h", "Water Level +1.9m Danger" chosen by severity | Those layers are gone; the pin panel gives the marker's real status, source and coordinates |
| Admin (`admin/page.tsx`) | "99.98% Uptime", "BigQuery 14ms", "Zero Breaches · MFA", "CLEARANCE: LEVEL 5", an invented audit trail | `/healthz` per dependency, the operator accounts, and the newest ledger rows with the chain verified (`GET /api/audit/recent`) |
| Data sources (`datasets/page.tsx`) | A catalogue of IMD radar, INSAT-3DR, CWC gauges and a BigQuery lakehouse, all "STREAMING_HEALTHY" | The five feeds INDRA reads, where each lands, and a "not connected" list |
| Analytics, live map header | "BIGQUERY ML ENGINE", "96.4%", "1.42M Doppler points/s", "Tracking: Cyclone DANA", "NDRF Units: 8 Deployed" | Counts from `/api/dashboard/summary`, events, teams |
| Settings page and drawer | Toggles for radar, cyclone, river-basin and NDRF layers, a "satellite data saver", a live-vs-mock switch, a "~6.4 MB" cache meter, hardcoded diagnostics | Removed (none was read by anything); diagnostics run `/healthz`. Seven dead keys left `useSettings` |
| Small things | "IMD • NDRF Synced", "Grid Synced", "Verified Identity", sensor/radar/satellite copy, nav descriptions | Accurate text |

**Behaviour fixed**

- **Build**: the four nullable-place type errors (item 12) — `npm run build` passes.
- **Dispatch** sent every team to the fabricated event code `WX-EV-28231827-A`; it now picks a live
  event, sends the persona's token, changes the card only after the backend has written it, and
  shows a refusal. The roster no longer falls back to four invented officers.
- **Profile and duty saves** reverted nothing on failure ("cached locally"); now they put the
  server's version back and say why.
- **Map pins**: a late `load` event wiped every pin (a stale closure left by the BUG-043 fix);
  both style handlers now call the latest renderer.
- **Receipt**: coverage under the score and the points ÷ coverage arithmetic (item 3); offline
  factors read from `state` (item 4); "filed by …" on official reports.
- **Report modal**: a Commander/Admin persona can tick *"File as an official dispatch"*
  (`POST /api/reports/official`).
- **Live feed**: messages read the fields the backend sends; official dispatches are `OFCL`.
- **Severity**: `advisory` has its own label; the recent-events list showed it as Moderate.

**New in `lib/api.ts`**: `currentPersona()`, `OPERATOR_STORAGE_KEY`, `fetchHealth()`,
`fetchOperators()`, `fetchAuditLedger()`, `fetchSummaryCounts()`, `submitOfficialReport()`;
`EventDetail.city/state` are typed nullable.

**Tests**: `e2e/no-invented-data.spec.ts` walks all eleven pages for the removed values, and checks
the warnings and admin pages against the API. If a real feature later needs one of those strings
(a real IMD radar integration, say), update the list in the same commit. 26/26 pass.

---

## 1. Three WebSocket message types on `/ws/events`

| Type | Payload | When |
|---|---|---|
| `NEW_REPORT` | `{type, report}` | a report was accepted |
| `VERIFIED_EVENT` | `{type, event}` | the pipeline created **or updated** an event |
| `EVENT_REVIEWED` | `{type, event}` | a commander approved, rejected or re-graded one |

`VERIFIED_EVENT` fires repeatedly for the *same* event as corroborating reports arrive — the
confidence climbs each time. Treat it as an upsert keyed on the event id, not an append.

The `report` payload carries `raw_text`, `h3_res8`, `credibility_score` and `source_type`. **The
text key is `raw_text`, not `text`.**

---

## 2. Confidence changed meaning, and is no longer capped at 0.80

An offline factor used to score `0.0` while keeping its full weight, so confidence could never
exceed 0.80 and `AUTO_PUBLISHED` (≥ 0.90) was unreachable. It is now the weighted mean over the
factors that actually reported:

```
confidence = Σ_online(weight × score) / Σ_online(weight)
```

**Every confidence value is about 1.25× its old value** while vision and anomaly are the only
missing factors. No range in the UI needs to change — but **if anything hardcodes "0.80 is the
maximum", it is now wrong.**

---

## 3. New receipt field: `factor_coverage` — please show it beside the score

`verification_receipt` carries a top-level `factor_coverage`: the share of the designed model that
actually reported. `0.80` normally, `0.55` when the weather feed is down.

```json
{"confidence_score": 0.4984, "factor_coverage": 0.8, "total_weighted": 0.3987,
 "factors": [...], "severity_basis": {...}}
```

A score without its coverage is misleading, and this is the single most valuable thing the
dashboard could add. Something as small as `0.50 · coverage 0.80` next to the number is enough.

`total_weighted / factor_coverage == confidence_score` exactly, so the receipt is self-checking.

---

## 4. Each factor now says whether it reported

Every entry in `factors` has a `state` of `computed` or `offline` and an `evidence` sentence.
`offline` factors should render visibly as absent — greyed, struck through, "no signal" — rather
than as a zero bar, which reads as "measured, and bad". `vision_analysis` and `anomaly_detection`
are **permanently** offline.

---

## 5. `boundary_geojson` is now always populated

`GET /api/events/{id}` returns a real `Polygon` containing every contributing report (concave hull
buffered 250 m). It was `null` on every event before Day 5. Nothing is required of you — but if the
map currently draws a circle from `impact_radius_km`, the polygon is the true footprint.

---

## 6. New endpoint: `GET /api/geo/heatmap`

```
GET /api/geo/heatmap?window=24h|48h|7d&resolution=6|7|8
→ {resolution, window, generated_at,
   cells: [{h3, lat, lng, report_count, linked_report_count}]}
```

Open, no token. Duplicates excluded. Zooming out is **aggregation, not re-binning** — a res-7 count
is the exact sum of its res-8 children, so the layer can be rendered at any of the three without
double counting. `422` on an unsupported window or resolution; it will not quietly substitute a
different one.

---

## 7. Each report carries an `analysis` object

`{cleaned_text, language (en|hi|hinglish), depth_cm, depth_basis, keywords, places, url_count,
phone_count, extracted_at}`.

Two honest caveats: `places` resolves a 56-city gazetteer, so it yields **cities, never landmarks**
(`"Patna"`, not `"Gandhi Maidan"`); and it is `null` when extraction failed, which never fails an
ingest. It is rule-based — regex and dictionaries, not a model — so label it as extracted text, not
as an AI reading.

---

## 8. ✅ Done: `ADVISORY` severity

The backend now grades severity from what reports say, and **`ADVISORY` is reachable and common** —
most fresh clusters are two to four reports with no depth quoted. The dashboard's severity filter
chips are `['ALL', 'CRITICAL', 'HIGH', 'MODERATE']`, so **`ADVISORY` events appear under ALL and
cannot be filtered or filtered out.**

Please add an `ADVISORY` chip. No backend change is involved. Quadrant handling is unaffected —
`assign_quadrant` already groups ADVISORY with MODERATE.

**22 Sep:** the events page's chips already included `ADVISORY` (from PR #26). What was still wrong
was the label: `SeverityLevel` had no `advisory`, so the recent-events list fell back to
*Moderate*. It now has its own entry.

---

## 9. `DEMO_MODE` now defaults to **false**, and must stay false

An empty database used to answer `GET /api/events` with a fabricated
`0.94 / AUTO_PUBLISHED / CRITICAL` event. The opening seconds of a live run are exactly when the
database is empty, so the dashboard opened on a confident disaster that no code computed.

With it off: **no rows → `[]`**, unknown detail id → **404**, database error → **503
`{"detail": "Database unavailable"}`**.

So the dashboard needs an honest **empty state** and an honest **error state**. An empty dashboard
that fills as reports arrive is both truthful and the better demonstration.

---

## 10. Two endpoints require a bearer token

| Endpoint | Roles |
|---|---|
| `PATCH /api/events/{id}/review` | `COMMANDER`, `ADMIN` |
| `GET /api/events/{id}/provenance` | `ANALYST`, `COMMANDER`, `ADMIN` |

Get one from `POST /api/auth/token`, **form-encoded** (OAuth2 password flow, not JSON):
`username=commander&password=commander123`. HS256, 8 h expiry. Send as
`Authorization: Bearer <token>`.

`401` without a token, `403` with an insufficient role, `409` on an illegal transition (e.g.
approving an already-rejected event) — a `409` is not an error to retry, it means the event moved.

Review actions: `approve` → `HUMAN_APPROVED`, `reject` → `REJECTED` (drops out of the list),
`override_severity` (status unchanged). `reason` is required, 5–1000 characters.
**`confidence_score` is never changed by a review** — show the machine's reading and the human's
decision separately.

`review_status` gained `HUMAN_APPROVED`. The display label `verification` maps it to `verified`,
alongside `AUTO_PUBLISHED`.

---

## 11. ✅ Done: every write requires a token

Since 22 Sep: `POST /api/teams` and `PATCH /api/teams/{id}/assign` need COMMANDER or ADMIN;
`PATCH /api/profile/me` and `/preferences` need any token and edit **only the token's own
operator** (`?user=` is ignored); `POST /api/reports/official` needs COMMANDER or ADMIN. The
dashboard already fetched a JWT for its selected persona, so no login screen was needed — the
calls now send it. A real login flow is still the right end state: the demo passwords ship with the
persona switcher.

---

## 12. ✅ Fixed 22 Sep: `next build` failed on `main` — four type errors, all nullable place names

Found 21 Sep on the team server, re-checked on `main` (`dc99a76`) on 22 Sep with
`npx tsc --noEmit`:

```
src/app/alerts/page.tsx(180,17): error TS2322: Type 'string | null' is not assignable to type 'string'.
src/app/alerts/page.tsx(180,26): error TS2322: Type 'string | null' is not assignable to type 'string'.
src/app/events/page.tsx(92,10):  error TS18047: 'ev.city' is possibly 'null'.
src/app/events/page.tsx(93,10):  error TS18047: 'ev.state' is possibly 'null'.
```

They came in with `1725a84` through the `frontend-20sep` merge (PR #26). `city` and `state` are
`string | null` **on purpose**: since BUG-033 the backend reverse-geocodes every event and returns
`null` when a point is offshore or outside every district, rather than inventing a name. So the
fix is here, not in the API: decide what each page shows for an unnamed place (drop the chip, or
say "Unnamed location").

Until it builds, the team server runs the dashboard with `next dev`, which skips the type check.
Once `npm run build` passes, the server unit switches to `next start`.

**Fixed on `aditya_22sep_c`** (`1004d75`, `2f411d1`) by rendering unnamed places through
`formatPlace()` — "Location unresolved" — and dropping null chips. `npm run build` is clean.

**Test:** `cd frontend && npx tsc --noEmit && npm run build` — both exit 0.

---

## 13. Phase 1 (23 Sep): sixteen event types, the PS's filters, dockets, and no lost reports

Nothing here breaks the dashboard as it is: every existing response keeps its shape and values, and
everything below is additive. Shapes and captured examples: [`api-contract.md`](api-contract.md).

| Change | What the dashboard can do with it | |
|---|---|---|
| **12 new event types**, 16 in all (contract: *Event types*) | Labels still come from the API as `eventType`. Each list item now also has **`event_type`** (the enum) and **`family`**. Please key icons and colours on `event_type` rather than the label, and render any type you do not recognise as its `eventType` label — never throw. `GlobeEventMap.tsx`'s `eventTypeEmojis` keys on labels; the five it knows (`Flood`, `Thunderstorm`, `Strong Winds`, `Fog`, `Heavy Rainfall`) were kept exactly so it keeps working | recommended |
| **`GET /api/events` filters** | **F1, the filter bar**: `from`/`to` (IST days), `event_type`, `family`, `review_status`, `severity` (lists), `state`, `district`, `source_type`, `min_confidence`, `q`, `sort`, `limit`/`offset`. The body is still a list; **the total is in the `X-Total-Count` header**, which CORS now exposes so `response.headers.get('X-Total-Count')` works from the browser. A bad value is a 422 naming the parameter | new |
| **`GET /api/meta/filters`** | The filter bar's options, each with its count — no hard-coded option lists, and nothing offered that has no events behind it. Cached 60 s server-side | new |
| **The 202 body gains `docket` and `will_retry`** | **F5**: after a submit, show the docket (`R-7K3M9QX2`) and tell the citizen to keep it; add a "track my report" box that calls **`GET /api/reports/track/{docket}`**. `queued: false` now means *stored, and it will be processed when the event bus is back* — please do not show it as a failure | new |
| **Optional `observed_at`, `hazard` and `X-Reporter-Id` on submit** | Generate a random id once per browser (`crypto.randomUUID()`), keep it in `localStorage`, and send it as the `X-Reporter-Id` header; only a keyed hash is stored. Offer a hazard picker (values from `/api/meta/filters` or the contract's table) and an optional "when did this happen?" — send `observed_at` **with its timezone** (`toISOString()`); a naive time is a 422 | optional |
| **`/healthz` gains `outbox_backlog`** | The admin console can show `{count, oldest_s}`: reports stored but still waiting for the event bus | optional |
| An `https://` address for the team server | **Live since 24 Sep: `https://indra-sixthsense.duckdns.org`** (Phase 1 T7). The dashboard, the API and the WebSocket share the name; `wss://` follows automatically, because `useIndraWebSocket.ts` derives it from the API base. The server's dashboard is already built with it as `NEXT_PUBLIC_API_BASE_URL`, so phones can use the report form's location button (browsers allow GPS only over HTTPS). Nothing changes for local development. `http://15.252.50.176:3000` and `:8000` keep working until everyone has switched, and will then be closed | live |

**Track statuses, in words a citizen understands** — a suggestion, yours to change:

| `status` | Say |
|---|---|
| `received` | Received — being checked |
| `duplicate` | Already reported — thank you, it was counted with the first report |
| `not_yet_an_event` | Received — not yet confirmed by other reports |
| `part_of_event` | Part of event `event_code`, being reviewed |
| `event_approved` | Confirmed |
| `event_rejected` | Reviewed and not confirmed |

The track route never returns the report's text, coordinates or anything about who sent it, so the
page can show everything it returns.

**Test:** with the backend running, `curl -s -D - 'localhost:8000/api/events?limit=1' | grep -i x-total-count`
prints the total, and `curl -s localhost:8000/api/meta/filters` returns the options.

---

## 14. After the 23 Sep frontend merge: one stale test, and the backend report, checked

**One of the dashboard's own browser tests now fails, because of the map redesign.**
`e2e/dashboard-cold-load.spec.ts:37` ("the map draws the pins its own badge is counting") looks for
the text `N Incidents`. The redesigned map no longer shows that badge, so the test times out. The
other 25 pass against the Phase 1 backend (24 Sep, production build of `main` @ `c6b8354`). The test
needs updating to whatever the map now shows as its count; the backend has nothing to change.

**`Saba/reports/2026-09-23_backend_issues.md`, checked line by line against the code.** Thank you
for it. Two of its symptoms came from the synthetic seeder, not from the pipeline, and are fixed:

| Report item | Finding | Status |
|---|---|---|
| 1A: random review status on `WX-EV-…` events | Confirmed in `scripts/seed_national_data.py`: statuses were drawn at random, half `AUTO_PUBLISHED` below 0.90 | **Fixed** 24 Sep (BUG-064). The seeder now asks the engine, as the pipeline does |
| 2: a 1,564 km impact radius | Root cause: the seeder linked each report to a random event anywhere in India, so one merged real report recomputed the footprint across the country | **Fixed** (BUG-065): farthest linked report 11.7 km, was 2,096 km |
| 2B/2C: the merge catchment grows without a ceiling | Confirmed in the pipeline | Open (BUG-066), for Phase 3's per-hazard radii — it moves scores |
| 1B: a High event at 0.47 is quarantined, though the docs said "never ignored" | Confirmed: routing used confidence alone | **Fixed** 24 Sep (BUG-067): High and Critical events below 0.60 now go to review, never quarantine; the receipt's `routing.basis` says `severity` when that is why. **Not adopted:** auto-publishing Moderate events at ≥ 0.70 — nothing is published without a human below 0.90 |
| 3B: demo KPIs had citizen > total | Confirmed | **Fixed** (BUG-069) |
| 3A: "Total Reports" vs the 7-day trend | Not a defect: the card counts all time, the chart the last 7 days. If the card should say "all time", that is its label | — |
| 4: map default view | Frontend only; no backend endpoint serves map defaults | — |

**Please do not debug backend behaviour against `WX-EV-…` events.** That prefix is only ever
written by the synthetic seeder (`--synthetic`), whose numbers are random by design; the pipeline
writes `INDRA-YYYYMMDD-NNN`. To see what the engine really does, start from an empty database and run
`scripts/run_patna_demo.py`.

---

## 15. ✅ Fixed 24 Sep (section 16): the dashboard replaced the API's review status with its own matrix

**Found 24 Sep while marking up the backend report (BUG-070, S2, layer 9).** Nothing in `frontend/`
was changed.

`frontend/src/lib/eventState.ts::safeEventState()` was added on 23 Sep to guard against the seeder's
random statuses (report item 1A). It never returns what the API sent: it derives the status and the
quadrant from `(severity, confidence)` with a 0.90 / **0.70** matrix, and only logs a warning when
the two differ. `/events`, `/alerts` and `EventVerificationModal` all use it. With the seeder fixed
(BUG-064), and the pipeline's status and quadrant read from one pair of gates (BUG-017), the guard now
hides real decisions rather than bad data:

| The backend has | The dashboard shows |
|---|---|
| `HUMAN_APPROVED` — a commander approved it | the machine status again (a 0.52 Moderate event reads "Quarantined"), and the modal still offers **Approve**; a second approve is refused with 409 |
| `REJECTED` | the machine status, with the commander bar still showing |
| the Patna scene on 24 Sep: Moderate, 0.6198, `PENDING_HUMAN_REVIEW` | "Quarantined", titled "Noise" |
| Moderate or Advisory at 0.70–0.8999, `PENDING_HUMAN_REVIEW` | "Auto-Published" — a publication that never happened |
| High or Critical below 0.90 | "Pending Human Review" — correct, and since BUG-067 the backend agrees |

This also means an approval made during the demo (the runbook's scene 3 approves over `curl`, and
`EVENT_REVIEWED` reaches the dashboard) never shows on the cards or in the modal.

The backend's rule lives in one place (`fusion_engine.py`, gates from settings):

| Confidence | Advisory / Moderate | High / Critical |
|---|---|---|
| ≥ 0.90 | `AUTO_PUBLISHED` | `AUTO_PUBLISHED` |
| 0.60 – 0.8999 | `PENDING_HUMAN_REVIEW` | `PENDING_HUMAN_REVIEW` |
| < 0.60 | `QUARANTINED` | `PENDING_HUMAN_REVIEW` — never quarantined (BUG-067) |

A commander's decision overrides the table: `HUMAN_APPROVED` or `REJECTED`, and once an event is
approved its quadrant follows its severity.

**What the dashboard needs:** show `review_status` and `quadrant` exactly as the API sends them, and
keep the derivation only as a fallback for when `review_status` is missing. `HUMAN_APPROVED` already
has a label in all three files (`REVIEW_BADGE`, `REVIEW_LABEL`, `STATUS_STYLES`), and `REJECTED` in
two of them; neither is ever reached today. The console warning can stay if it names the API's value as
the one shown. If the team wants the 0.70 matrix, that is a change to the backend's routing, to be
decided in the open, not a display rule: below 0.90 nothing is published without a human, by decision
(report item 1B, not adopted).

**Check:** approve a quarantined event from the modal. The pill and the card should read "Approved",
and the Approve button should disappear.

---

## 16. What changed in `frontend/` on 24 Sep, and why

Aditya reported the dashboard, Incident Events, Field Reports, Telemetry Analytics and Geospatial
Feeds as "not working", and the frame of the dashboard and the live map as off, and gave himself the
go-ahead to change `frontend/` for the day (not its core design). Branch `aditya_24sept_frontend`,
one commit per change, reason in each message. The design language is unchanged: same cards,
colours, fonts and layout grid.

**First, what was not broken.** The team database held one report and no events, so Recent Events,
Event Distribution and Incident Events were honestly empty. That is still true of the event panels
until reports arrive; the panels now say why and show the live data that does exist beside them.

| Area | Change | Commit |
|---|---|---|
| `lib/useIndraWebSocket.ts` | **One socket per tab.** Same hook signature (`{connected, subscribe}`); the connection is module-level. Please do not open raw `new WebSocket(...)` in components; subscribe instead | `55fe2ab` |
| `lib/eventState.ts` | `safeEventState(id, sev, conf, apiStatus, apiQuadrant?)` **returns the API's status and quadrant**; derives only when they are missing (BUG-070) | `44f2486` |
| `lib/api.ts` | `fetchRecentFeed(limit, include?)`, `fetchFieldReports(limit, hours, unfusedOnly)`, `fetchDataSources`, `fetchStations`, `agencyAlertsToDistribution`, `fetchEvents({from, limit})`; the events dedupe window is 2 s, not 15 | `4a0f762`, `6a88062` |
| `lib/ui-config.ts` | `KpiItem.delta` is `number \| null` (null = no comparison window, no "0%"); `FeedItem` gains `kind`, `at`, `place`, `severity`, `status`; feed source `warning` | `1fbb5d1`, `4a0f762` |
| `lib/utils.ts` | `formatIst(at)` ("20:27" today, "21 Sept 20:27" otherwise) and `formatAgo(at)` | `4a0f762` |
| KPI strip (`globals.css`, `KpiCard`) | six across at ≥ 1280 px, 3 × 2 below, 2 × 3 on phones | `1fbb5d1`, `96cbf35` |
| `GlobeEventMap` | `canvasClassName` prop for viewport-relative heights; opening camera fitted to India; `ResizeObserver`; warnings refetched every 2 min; field reports 7 days; shared socket; Escape closes the roster | `e3b21ff`, `2ff657b`, `fb445b0`, `40794c5` |
| Dashboard (`app/page.tsx`) | map height `clamp(340px, 100dvh − 490px, 680px)`; the map sets the row height and Recent Events scrolls | `e3b21ff`, `e6c80d1`, `fb445b0` |
| `RecentEventsList` | fills its row; "View all" → `/events`; with no events, lists **official warnings in force**, labelled as such | `6fcd548` |
| `EventDistributionChart` | header switch **Events N \| Warnings N**; opens on warnings once when there are no events | `9e65ea7` |
| `ReportsTrendChart` | linear line with dots, whole-number axis, total, refetch on `NEW_REPORT` | `5ee85a9` |
| `LiveFeed` | merged feed (reports, events, warnings) in IST, rows link to their page, refetch every minute | `4c95253` |
| `/events` | 24H / 7D / 30D / ALL; ADVISORY filter fixed (the API says `low`); error state; empty state with links | `068203c` |
| `/reports` | reads `/api/reports/recent?unfused_only=false` for 30 days: place, status, event code, depth, IST time; source and status filters | `6f20b66` |
| `/analytics` | rainfall panel (`/api/geo/stations`) and warnings-by-agency panel; figures refresh | `d8db6b4`, `7bc68f5` |
| `/datasets` | per-feed LIVE / STALE / DISABLED, newest row, rows 24 h / total, from `/api/meta/sources` | `841f600` |
| `/live-map` | canvas `clamp(420px, 100dvh − 352px, 1100px)`; header counts the report layer; refreshes | `fdc2d4f`, `fefbada` |

**Checked:** `tsc --noEmit` and `next build` pass; every page was opened in a browser against the
team API at 1425 × 780 with no console errors. **Not checked:** phone widths, and the three parts that
need the 24 Sep backend (feed warnings, rainfall, feed status) against a deployed backend.

**For you:**

1. Please review the PR, since it is your layer.
2. `e2e/dashboard-cold-load.spec.ts` looks for a `\d+ Incidents` badge. The map has said
   "N map pins" since before today, so that test skips or fails on its own; worth updating to
   `/\d+ map pins/`.
3. Lint: `GlobeEventMap.tsx` has an unnecessary `smartDeclutter` dependency in a `useCallback`
   (warning only, present before today).

---

## 17. Phase 2 (24 Sep): five live feeds, airport weather, a data lake, search and export

**Backend status: written, not yet tested** (branch `aditya_24sep_c`). The shapes are in
[`api-contract.md`](api-contract.md), each marked "Phase 2"; none is captured from a running stack
yet. **Nothing here breaks the dashboard as it is:** every existing response keeps its shape, the one
behaviour change to an existing route keeps the map drawing exactly what it drew, and everything
else is additive. No file in `frontend/` was touched.

| Change | What the dashboard can do with it | |
|---|---|---|
| **New `source_type`s arrive: `SOCIAL_MEDIA` (Mastodon posts tagged #IMD and other weather hashtags) and `NEWS_MEDIA` (Google News headlines)**, each with a `platform` (`mastodon`, `google_news`) | **F7, the social and news panel.** In `GET /api/feed/recent` a post's `sourceLabel` is `Mastodon`, a headline's is its publisher (`"The Hindu"`), `source` is `social` or `news`, and the item has `platform`. The existing icons for `social` and `news` already fit | recommended |
| **A new WebSocket message, `NEW_FEED_ITEM`** — same payload as `NEW_REPORT`, for a collected post or headline | Collected items no longer arrive as `NEW_REPORT`: one news tick stores dozens of headlines at once, and every screen refetches on each `NEW_REPORT`. If you want the live feed to move when posts arrive, listen for `NEW_FEED_ITEM` **and debounce the refetch** (one per second is plenty). Ignoring it is safe | optional |
| **Reports can now have no coordinates.** `raw_reports.latitude`/`longitude` are nullable; each report has `place_precision`: `gps`, `district`, `state` or `none` | `GET /api/reports/recent` **leaves collected items out by default**, so the field-reports layer draws exactly what it drew before. With `?include_feeds=true` it includes them, and `lat`/`lng` are `null` for a post that names no place: draw nothing for those, and label a `district` or `state` precision as approximate ("near Ernakulam", "Kerala"), never as a pin on a street | behaviour note |
| **`GET /api/meta/sources` reads real heartbeats** | **F3, the feed-status panel** (`/datasets` already reads it). Three more feeds are listed — `metar`, `mastodon`, `google_news` — and `status` can now be **`failing`** (3 failed ticks, with `last_error`). `basis` is `heartbeat` for pollers, so `last_success_at` now means *the last successful poll*, not the newest row: the card's "Newest row" label should read "Last polled" when `basis` is `heartbeat` (the old figure is `newest_row_at`). New: `last_attempt_at`, `last_error_at`, `consecutive_failures`, `items_last_tick`, and a top-level `dead_letters: {total, last_at, last_error}` — 0 is healthy | recommended |
| **`GET /api/stations/latest?feed=metar`** — open | **F4, a map layer of real airport observations**: ~105 Indian aerodromes, each with temperature, dewpoint, wind and gusts (km/h), visibility (m; 10,000 = "10 km or more"), `weather_codes` (`["HZ"]`, `["TS", "RA+"]`, `["FG"]`) and `convective_cloud`. These are **observed**, not modelled: say "airport observation" rather than "forecast". `GET /api/geo/stations` (the six Open-Meteo rainfall points) is unchanged | new |
| **`GET /api/reports/search`** — **analyst token** | **F3, the data explorer**: every report, post and headline with the filters in the contract (`from`/`to`, `source_type`, `platform`, `publisher`, `state`, `district`, `precision`, `status`, `has_media`, `language`, `hazard`, `q`, `sort`, `limit`/`offset`); total in `X-Total-Count`. Send the analyst's bearer token as for provenance; a citizen token gets 403. Show `status` `held` as "collected — not clustered until hazard tagging" | new |
| **`GET /api/reports/export` and `GET /api/events/export`** (`format=csv` or `geojson`) — **analyst token** | Download buttons beside the explorer and the event list, passing the same filters the screen shows. Fetch with the token and save the blob; the file name is in `Content-Disposition`, which CORS now exposes. **Every export is written to the audit ledger**, so a button label like "Export (recorded)" is honest | new |
| **`/healthz` gains `object_store`** | Non-critical, like Redis: down or unconfigured makes the whole status `degraded`, never `unhealthy`. The admin console can show it beside `outbox_backlog` | optional |
| **`total_reports` in `/api/dashboard/summary` now includes collected posts and headlines**; `citizen_reports` does not | If the KPI card is labelled "Total reports", "Signals collected" would now describe it better; or show `citizen_reports` there instead | behaviour note |

**Test, once the branch is deployed:** `curl -s localhost:8000/api/meta/sources | python3 -m json.tool`
lists seven feeds and `dead_letters`; `curl -s 'localhost:8000/api/stations/latest?feed=metar' | head -c 400`
shows airport observations once `METAR_POLLER_ENABLED=true`.

---

## Things that are not coming, so please do not leave space for them

| | |
|---|---|
| **INDRA-issued alerts** — no SMS, email or broadcast | Cancelled 20 Sep. The warnings page shows *official* SACHET warnings (`GET /api/alerts/agency`); INDRA itself issues none |
| **Risk zones** | Not built, not scheduled |
| **Image / vision analysis** | Out of scope. `media_url` is stored as a string and nothing opens it |
| **Anomaly detection** | Out of scope. Permanently `offline` in the receipt |
| **Event-type classification by a model** | Trained, measured below its gate, unwired, and frozen with the rest of layer 4. Tagging the 16 types by published rules is Phase 3; until then every event is `URBAN_FLOOD` |

If the dashboard currently renders any of these with mock data, that is the highest-value thing to
remove before the demo — a panel showing invented telemetry is exactly what we spent 20–21 Sep
taking out of the backend.

---

**Questions:** ask me. If something needs a new response shape or a new message type, say so and I
will add it backend-side — I do not edit `frontend/`.
