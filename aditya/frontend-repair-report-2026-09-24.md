# INDRA Dashboard Repair — Report, 24 Sep 2026

24 Sep 2026 · Aditya · branch `aditya_24sept_frontend` · 34 commits

All seven dashboard pages reported as broken are fixed on the branch, which builds cleanly. The
biggest single cause was not a bug. The team database holds **1 report and 0 events**, so most event
panels were correctly empty. The rest was real defects, now fixed. **None of it is on the team server
yet**: it goes live after the PR is merged and the server is redeployed.

## What was actually wrong

Most "not working" panels had no data to show. The rest were real defects in the pages and in three
backend endpoints.

| What the database held on 24 Sep, ~10:30 IST | Count |
| --- | --- |
| Reports (one test report from 21 Sep, Patna) | 1 |
| Events | 0 |
| Official warnings stored (SACHET) | 340, of which 109 arrived in the last 24 h and ~20 are in force |
| Open-Meteo rainfall readings (6 city points) | 504 |

An event forms only when two nearby reports back each other up, so with one report every event
panel stays empty. Meanwhile the live warnings and rainfall readings, which do arrive every few
minutes, were shown almost nowhere. The fix therefore has two halves:

1. Fix the real defects.
2. Show the live data that exists, clearly labelled, and say plainly why the event panels are
   empty.

## Issue by issue

| Page · issue you reported | Cause | Fix | Commits |
| --- | --- | --- | --- |
| Dashboard · Recent Events | 0 events. Also a dead "View all" button, and the card was 90 px shorter than the map beside it | Card fills its row and "View all" opens Incident Events. With no events it lists the official warnings in force, marked as warnings | `6fcd548`, `e6c80d1` |
| Dashboard · Event Distribution | 0 events to group | New **Events / Warnings** switch; opens on warnings when there are no events | `9e65ea7` |
| Dashboard · Reports Trend | A single report drawn as a smooth bell curve, a "0.5 reports" tick, never refreshed. The backend also counted days in UTC and "7d" meant 8 days | Straight line with dots, whole numbers only, total shown, updates when a report arrives; backend counts IST days | `5ee85a9`, `bfa9350` |
| Dashboard · Live Feed | Citizen reports only, UTC time with no date ("14:57" for a report filed at 20:27 IST, three days ago) | Feed now merges reports, events and warnings in force, times in IST with the date, each row clickable | `5434f51`, `4c95253` |
| Dashboard · Frame | KPI strip was a 4-column grid for 6 tiles (4 + 2 with gaps); fixed-height map left empty space at the bottom; "0%" on figures that have no comparison | 6 tiles in one row; map height follows the screen; map sets the row height; no fake "0%" | `1fbb5d1`, `96cbf35`, `e3b21ff`, `fb445b0` |
| Live Tactical Map · Frame | Fixed 560 px map: too short on a monitor, cut labels on a laptop; fixed zoom cut off south India | Map fills the screen; opening view fits all of India; canvas resizes with its box | `e3b21ff`, `fb445b0`, `fefbada` |
| Live Tactical Map · Check all | Warnings never refreshed; the Patna report would vanish after 72 h; 5 WebSocket connections per tab; Escape left the roster open | Refresh every 2 min; reports kept 7 days; one shared socket; Escape closes it; header also counts reports | `2ff657b`, `55fe2ab`, `40794c5`, `fdc2d4f` |
| Incident Events | 0 events. Also: the ADVISORY filter could never match (the API says `low`), errors hidden as "no match", 7 days only | ADVISORY fixed, 24H / 7D / 30D / ALL picker, error state with Retry, empty state explains why and links to warnings and reports | `068203c` |
| Incident Events (and Early Warnings, receipt) | Showed a status the dashboard invented, not the API's (BUG-070): an approved event never showed as approved | Shows the API's status; derives one only when missing | `44f2486` |
| Field Reports | Built on the feed endpoint, so no place, no status, UTC time, search by place impossible | Reads the stored reports for 30 days: place, status (awaiting / in event / duplicate), event code, water depth, IST time; filters | `6f20b66`, `5d1014e` |
| Telemetry Analytics | Only four counts and two empty charts | Adds rainfall for the 6 stations (bar + 48 h sparkline) and warnings by colour and by agency; figures refresh | `d8db6b4`, `1e98c2a`, `7bc68f5` |
| Geospatial Feeds | Static text; could not tell a dead feed from a live one | Each feed shows LIVE / STALE, newest row, rows in 24 h and in total, poll interval, from the new `GET /api/meta/sources` | `841f600`, `74e9a46` |

## Backend changes (my layers)

Five endpoints changed or were added so the pages had something real to show. Existing response
fields are unchanged, so the current dashboard keeps working until the new one is deployed.

| Endpoint | Change | Commit |
| --- | --- | --- |
| `GET /api/feed/recent` | Reports + events + warnings in force, newest first; `at` (ISO) and IST `time` (BUG-071) | `5434f51` |
| `GET /api/reports/trend` | IST days, exactly N days (BUG-072) | `bfa9350` |
| `GET /api/reports/recent` | Adds `event_id`, `event_code`, `observed_at`, `credibility_score`; never the docket | `5d1014e` |
| `GET /api/meta/sources` (new) | Phase 2 T2's contract served early, worked out from each table's newest row until T2 adds the heartbeat table | `74e9a46` |
| `GET /api/geo/stations` (new) | Latest rainfall and the last 48 h per station | `1e98c2a` |

## How it was checked

Build and visual checks are done. The pytest run waits for the testing pass, per the code-first rule.

| Check | Result |
| --- | --- |
| `tsc --noEmit` | Pass |
| `next build` (production) | Pass, 14 pages |
| Browser, every changed page, local build against the live team API, 1425 × 780 | Renders, no console errors. Map controls tried: roster, layers panel, fullscreen, India fit |
| New backend SQL | Run read-only on the team database: all queries return the expected rows (7 IST days; warnings newest first; 6 stations × 12 hours) |
| New pytest files `test_feed_api.py`, `test_meta_sources.py`, `test_geo_stations.py` | **Written, not yet run** |
| Phone widths | Not checked |
| Warnings in the feed, rainfall, feed status on the live site | Only after deploy; the server still runs the old backend |

## Documents updated

- `docs/bug-register.md`: BUG-070 fixed; BUG-071 to BUG-080 added.
- `docs/api-contract.md`: all five endpoints.
- `docs/frontend-handover.md`: section 16 lists every frontend change for the frontend team and closes section 15.

## Next steps

| Step | Who | Note |
| --- | --- | --- |
| Review and merge the PR | Frontend team + Aditya | Touches their layer; handover §16 |
| Build on the Mac, then redeploy the server (API restart + frontend rebuild) | Aditya | No migration, no new `.env` key. Build with `NEXT_PUBLIC_API_BASE_URL=https://indra-sixthsense.duckdns.org` |
| Run the three new pytest files and the full suite | Aditya | Testing pass |
| Put events on the dashboard | Aditya | Needs real reports, or `./start.sh demo` on the server (synthetic Patna reports through the real pipeline). It was left unseeded on purpose; your call |
| Update `e2e/dashboard-cold-load.spec.ts` | Frontend team | It looks for "N Incidents"; the map says "N map pins" |

## WhatsApp message

> *INDRA dashboard update (24 Sep)*
> Fixed all 7 pages on branch `aditya_24sept_frontend` (PR open, 34 commits). Main finding: the team DB has only 1 report and 0 events, so the event panels were empty rather than broken. The real bugs are fixed too:
> • Dashboard: one-row KPI strip, map fills the screen, Recent Events and the Event Distribution donut show live official warnings when there are no events, Live Feed now shows reports + events + warnings in IST, Trend chart fixed
> • Live map: full-screen frame, all of India in view, warnings refresh every 2 min
> • Incident Events: ADVISORY filter fixed, time range picker, the review status is now the API's (BUG-070)
> • Field Reports: place, status, event code, date for every report
> • Analytics: live rainfall for 6 cities + warnings by agency
> • Geospatial Feeds: LIVE/STALE status per feed
> Frontend team: please review the PR (details in docs/frontend-handover.md §16). It goes on the server after merge.
