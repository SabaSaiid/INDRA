# Handover — Backend → Dashboard

**From:** Aditya (layers 1–3, 5, 6, 7, 8a) · **To:** whoever owns `INDRA/frontend/`
**Covers:** every backend change from 16–22 Sep 2026 that the dashboard can see, and — new on
22 Sep — **what was changed inside `frontend/` that day, and why** (section 0).

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

## Things that are not coming, so please do not leave space for them

| | |
|---|---|
| **INDRA-issued alerts** — no SMS, email or broadcast | Cancelled 20 Sep. The warnings page shows *official* SACHET warnings (`GET /api/alerts/agency`); INDRA itself issues none |
| **Risk zones** | Not built, not scheduled |
| **Image / vision analysis** | Out of scope. `media_url` is stored as a string and nothing opens it |
| **Anomaly detection** | Out of scope. Permanently `offline` in the receipt |
| **Event-type classification from text** | Trained, measured below its gate, unwired |

If the dashboard currently renders any of these with mock data, that is the highest-value thing to
remove before the demo — a panel showing invented telemetry is exactly what we spent 20–21 Sep
taking out of the backend.

---

**Questions:** ask me. If something needs a new response shape or a new message type, say so and I
will add it backend-side — I do not edit `frontend/`.
