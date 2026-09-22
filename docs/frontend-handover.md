# Handover — Backend → Dashboard

**From:** Aditya (layers 1–3, 5, 6, 7, 8a) · **To:** whoever owns `INDRA/frontend/`
**Covers:** every backend change from 16–21 Sep 2026 that the dashboard can see, plus the `main` build failure found 22 Sep (item 12).

**Up to 20 Sep, `frontend/` was never touched from the backend side.** On 21 Sep that changed, on
request: PRs #25 and #27 carry `fix(9)` / `feat(9)` / `refactor(frontend)` commits that removed
the mock-data fallbacks, added the live map layers and self-refresh, and fixed BUG-043/044 (see
`git log --author=kraditya9241 -- frontend/`). Item 12 below is **not** among them and is yours.
This file supersedes the three notes that used to live in `aditya/`
(`handover-verified-event-ws.md`, `handover-review-provenance.md`,
`handover-20sep-geo-and-confidence.md`); they stay where they are as history.

Most of this is new data you can use. **Two** items need a change — item 8 (`ADVISORY` chip) and
item 12 (the production build fails on `main`) — and one is visible immediately whether you act on
it or not — item 9.

Full endpoint shapes: [`api-contract.md`](api-contract.md).

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

## 8. ⚠ The one change that is actually needed: `ADVISORY` severity

The backend now grades severity from what reports say, and **`ADVISORY` is reachable and common** —
most fresh clusters are two to four reports with no depth quoted. The dashboard's severity filter
chips are `['ALL', 'CRITICAL', 'HIGH', 'MODERATE']`, so **`ADVISORY` events appear under ALL and
cannot be filtered or filtered out.**

Please add an `ADVISORY` chip. No backend change is involved. Quadrant handling is unaffected —
`assign_quadrant` already groups ADVISORY with MODERATE.

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

## 11. Proposed, not done: gating the rest of the API

Every endpoint the dashboard calls today is open, including the mutations (`POST /api/teams`,
`PATCH /api/teams/{id}/assign`, `PATCH /api/profile/*`). They should require a token once the
dashboard has a login flow. **That flow is yours to build, so this is a proposal, not a change** —
tell me when you want it and I will gate them in one commit. Tracked as BUG-009.

---

## 12. ⚠ `next build` fails on `main` — four type errors, all nullable place names

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

**Test:** `cd frontend && npx tsc --noEmit && npm run build` — both exit 0.

---

## Things that are not coming, so please do not leave space for them

| | |
|---|---|
| **Alerts** — no SMS, email, dispatch or `GET /api/alerts` | Cancelled 20 Sep. If the UI has an alerts panel, it has no backend and never will |
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
