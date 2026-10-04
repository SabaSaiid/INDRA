# INDRA Backend Issues & Root Cause Analysis

> **Report Date:** 23 September 2026 (`2026-09-23`)  
> **Author:** Saba  
> **Target System:** INDRA (Indian National Disaster Response & Alerting Platform)  
> **Scope:** Backend Pipeline, Data Seeding, Geo-Clustering, Database Schemas, and API Endpoints  
> **Verification Status:** 100% Verified against Active Codebase  
> **Backend Resolution:** Checked item by item against the code by Aditya on 24 September 2026; fixes merged to `main` in PR #31. Status per item in the table below and at the end of each issue.  

---

<details open>
<summary>✅ <b>Resolution Update — 04 October 2026 (Frontend-Backend Architecture & Hydration Sync)</b></summary>

The system-level integration and runtime stability bugs identified during October multi-persona development were systematically resolved, verified by `verify-build.sh`, and merged on `Saba-4-Oct-2026`:

| # | Architecture Touchpoint | Symptom & Root Cause | Operational Resolution |
| :--- | :--- | :--- | :--- |
| **5A** | **SSR Role Context Hydration** | Dynamic import with `{ ssr: false }` for `RoleProvider` in `layout.tsx` caused hydration mismatches on initial HTML mount | Statically imported `RoleProvider` from `@/lib/useRoleContext`, establishing universal client context across all routes without DOM mismatch |
| **5B** | **Dev/Prod Build Cache Collision** | Running `npm run build` wiped `.next/` while `next dev` was active, causing `404 Not Found` for `layout.css` and JS chunks | Dynamically isolated development (`.next-dev/`) from production builds (`.next/`) via `PHASE_DEVELOPMENT_SERVER` in `next.config.mjs` |
| **5C** | **Supervisor Zombie Healthcheck** | `start.sh` treated raw HTTP 200 HTML as active even when CSS was 404, preventing automatic recovery of corrupted dev processes | Enhanced supervisor with asset probing (`curl -w "%{http_code}" /_next/static/css/...`), auto-recycling broken instances within 1.0s |
| **5D** | **Admin Omni-Console Endpoints** | Need for live AI model inspection, zero-shot NLP testing, and dynamic spatial reclustering | Deployed `GET /api/admin/ml-observatory`, `POST /api/admin/ml-test-nlp`, and `POST /api/admin/recluster` in `backend/app/api/admin.py` |

</details>

---

<details open>
<summary>✅ <b>Resolution Status — 24 September 2026</b></summary>

Every item was checked against the code on `main` @ `c6b8354`, and the fixes were merged in **PR #31**. Both example cards (`WX-EV-B85B4E8E-E`, `WX-EV-43DDEC9C-B`) carry the `WX-EV-…` code that only the synthetic seeder (`scripts/seed_national_data.py --synthetic`) writes; the pipeline writes `INDRA-YYYYMMDD-NNN`. So the symptoms came from seeded rows, and two of the root causes were in the seeder. Bug numbers refer to [`docs/bug-register.md`](../../docs/bug-register.md).

| # | Item | Status | Resolution |
| :--- | :--- | :--- | :--- |
| 1A | Seeder picks `review_status` at random | ✅ **Done** | BUG-064 (`da63990`): the seeder takes `quadrant` and `review_status` from `FusionEngine`, exactly as the pipeline does |
| 1B | `determine_review_status` ignores severity | ✅ **Done** | BUG-067 (`6083572`, docs `5d0a7e1`): a High or Critical event is never quarantined; below 0.90 it always goes to `PENDING_HUMAN_REVIEW` |
| 1B | Low / Moderate / Advisory at ≥ 0.70 → `AUTO_PUBLISHED` | ❌ **Not adopted**, by design | Nothing is published without a human below 0.90. Moderate and Advisory events at 0.60–0.89 go to human review |
| 1.2 | The docs give the review gate as 0.70 | ✅ **Done** | BUG-068 (`a1cfe84`): README and ARCHITECTURE say 0.60, the value since 20 Sep |
| 2 | 1,564 km impact radius | ✅ **Done** (root cause) | BUG-065 (`e55ea41`): the seeder linked reports to random events anywhere in India; now only to an event in the report's own city |
| 2A–2C | The merge catchment and the radius have no ceiling | ⏳ **Open — Phase 3** | BUG-066: capped per hazard family when Phase 3 makes clustering and merging per hazard. It changes scores, so it is not patched on its own |
| 3A | "Total Reports" (all time) vs the 7-day trend | ✅ **No backend defect** | Both numbers are right: the card counts all time, the chart the last 7 days |
| 3B | `DEMO_KPIS` has more citizen reports than reports | ✅ **Done** | BUG-069 (`a89d948`), with a test |
| 4 | Map default view | ✅ **No backend change needed** | No backend endpoint serves a default map view |

**One follow-up on the frontend side (BUG-070, [`docs/frontend-handover.md`](../../docs/frontend-handover.md) §15).** Now that the backend sends a consistent status, `frontend/src/lib/eventState.ts::safeEventState()` should show the API's `review_status` instead of re-deriving it. Today it ignores what the API sent, so `HUMAN_APPROVED` and `REJECTED` never appear, and Moderate events in human review show as "Quarantined" (0.60–0.69) or "Auto-Published" (0.70–0.89).

</details>

---

<details open>
<summary>📋 <b>Executive Summary</b></summary>

### Overview
During testing and frontend validation of the INDRA operational dashboard, several critical inconsistencies and display anomalies were identified. While temporary display-layer safeguards and defensive UI transformations were implemented on the frontend, the underlying root causes reside in the **backend data pipelines, seeding scripts, fusion logic, and API query implementations**.

This document provides a 100% verified, line-by-line technical audit of the four major backend issues causing system instability, misleading incident statuses, and visual bugs.

</details>

---

<details>
<summary>🚨 <b>Issue 1: Desynchronization of <code>review_status</code> and <code>quadrant</code> (2×2 Matrix Violation)</b> — ✅ <b>Resolved</b> (one suggestion not adopted)</summary>

### 1.1 The Symptom
On the Incident Events view (`/events`) and Alert feed (`/alerts`):
- Card `WX-EV-B85B4E8E-E` displayed the title **"Rainfall — Unverified Threat"** (83% confidence, High severity), yet its status pill read **"Auto-Published"**.
- Card `WX-EV-43DDEC9C-B` displayed High severity and 47% confidence, but was marked **"Quarantined"** instead of **"Pending Human Review"**.

### 1.2 The Specification Rule
Per INDRA's canonical architecture specifications ([`docs/ARCHITECTURE.md` §2, lines 170–197](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/docs/ARCHITECTURE.md#L170-L197), [`README.md` lines 105–125](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/README.md#L105-L125), and [`understand.md` lines 915–945](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/understand.md#L915-L945)), every event belongs to a strict 2×2 decision matrix governed by `(severity, confidence_score)`:

| Severity | Confidence Score | Required Quadrant (`quadrant_enum`) | Required Review Status (`review_status_enum`) | Operational Action |
| :--- | :--- | :--- | :--- | :--- |
| **High / Critical** | $\ge 90\%$ (0.90) | `Critical Verified Event` | `AUTO_PUBLISHED` | Instant sirens, SMS broadcast, NDRF dispatch |
| **High / Critical** | $< 90\%$ (0.90) | `Unverified Threat` | `PENDING_HUMAN_REVIEW` | Urgent operator verification queue; **never auto-published** |
| **Low / Moderate / Advisory** | $\ge 70\%$ (0.70) | `Confirmed Minor Event` | `AUTO_PUBLISHED` | Municipal tracking; monitor without public panic |
| **Low / Moderate / Advisory** | $< 70\%$ (0.70) | `Noise` | `QUARANTINED` | Filtered out from command center view |

Under no circumstances should a High-severity event under 90% confidence ever be `AUTO_PUBLISHED`. High-severity events with unconfirmed confidence represent life-critical situations (e.g. unverified dam break) that mandate operator review.

### 1.3 The Backend Root Causes

#### A. Synthetic Data Generator ([`scripts/seed_national_data.py` lines 233–241](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/scripts/seed_national_data.py#L233-L241))
```python
severity = random.choices(SEVERITIES, SEVERITY_WEIGHTS)[0]
confidence = round(random.uniform(0.55, 0.98), 4)
quadrant = compute_quadrant(severity, confidence)
review_status = random.choices(REVIEW_STATUSES, REVIEW_WEIGHTS)[0]  # <--- BUG!

# If critical + high confidence, force AUTO_PUBLISHED
if severity == "CRITICAL" and confidence >= 0.90:
    review_status = "AUTO_PUBLISHED"
```
- **Flaw:** While `quadrant` is computed via `compute_quadrant(severity, confidence)`, `review_status` is chosen **completely at random** (`random.choices(REVIEW_STATUSES, ...)`), with only a single narrow exception for Critical $\ge 90\%$.
- An event with High severity and 83% confidence correctly computes `quadrant = "Unverified Threat"`, but receives `review_status = "AUTO_PUBLISHED"` from the random choice.
- An event with High severity and 47% confidence computes `quadrant = "Unverified Threat"`, but receives `review_status = "QUARANTINED"` from the random choice.

#### B. Pipeline Decoupling ([`backend/app/services/pipeline.py` lines 329–335](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/pipeline.py#L329-L335) & [`backend/app/services/fusion_engine.py` lines 263–293](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/fusion_engine.py#L263-L293))
In `pipeline.py`:
```python
severity = decided["severity"]
quadrant = fusion.assign_quadrant(severity, confidence)
review_status = fusion.determine_review_status(
    confidence,
    settings.AUTO_PUBLISH_THRESHOLD,
    settings.HUMAN_REVIEW_THRESHOLD,
)
```
In `fusion_engine.py`:
```python
def determine_review_status(
    self,
    confidence: float,
    auto_threshold: Optional[float] = None,
    review_threshold: Optional[float] = None,
) -> ReviewStatus:
    if confidence >= auto_threshold:
        return ReviewStatus.AUTO_PUBLISHED
    elif confidence >= review_threshold:
        return ReviewStatus.PENDING_HUMAN_REVIEW
    else:
        return ReviewStatus.QUARANTINED
```
- **Flaw:** `determine_review_status` only accepts `confidence`. It completely ignores `severity`!
- For an `ADVISORY` event with 75% confidence, `determine_review_status` outputs `PENDING_HUMAN_REVIEW`, whereas the system specification dictates that low-severity events with $\ge 70\%$ confidence should be auto-published as `Confirmed Minor Event` without blocking the human review queue.
- Conversely, because `assign_quadrant` and `determine_review_status` are two disconnected functions, thresholds and outcomes drift, producing mismatched database columns (`quadrant` vs `review_status`).

### 1.4 Frontend Safeguard Implemented
To protect users before backend remediation, [`frontend/src/lib/eventState.ts`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/lib/eventState.ts) was created to implement `safeEventState(severity, confidence, rawReviewStatus)`. This guarantees that all UI cards derive their quadrant and status pill strictly from the 2×2 matrix.

### 1.5 Recommended Backend Fix
1. Unify the decision logic into a single authoritative Python function in `fusion_engine.py`:
   ```python
   def derive_event_state(severity: Severity, confidence: float) -> Tuple[Quadrant, ReviewStatus]:
       is_high = severity in {Severity.HIGH, Severity.CRITICAL}
       if is_high:
           if confidence >= 0.90:
               return Quadrant.CRITICAL_VERIFIED, ReviewStatus.AUTO_PUBLISHED
           return Quadrant.UNVERIFIED_THREAT, ReviewStatus.PENDING_HUMAN_REVIEW
       else:
           if confidence >= 0.70:
               return Quadrant.CONFIRMED_MINOR, ReviewStatus.AUTO_PUBLISHED
           return Quadrant.NOISE, ReviewStatus.QUARANTINED
   ```
2. Update `scripts/seed_national_data.py` to use `derive_event_state` rather than selecting `review_status` via `random.choices()`.
3. Update `backend/app/services/pipeline.py` to call `derive_event_state`.

### 1.6 ✅ Resolution (24 Sep 2026)

- **1.3A — ✅ Done** (BUG-064, `da63990`). The seeder now takes `quadrant` and `review_status` from `FusionEngine`, the same two calls the pipeline makes, instead of `random.choices()`. Its own `compute_quadrant()`, with the old 0.70 gate, is gone. Seeded on an empty database: 0 of 37 events off the engine's rule (the old seeder: 11 `AUTO_PUBLISHED` below 0.90).
- **1.3B — ✅ Done** (BUG-067, `6083572`; docs `5d0a7e1`). `determine_review_status()` now takes the severity. A `HIGH` or `CRITICAL` event is never quarantined: below 0.90 it always goes to `PENDING_HUMAN_REVIEW`, and it still needs 0.90 to publish on its own. The receipt's `routing.basis` reads `severity` when that is why. Under this rule `WX-EV-43DDEC9C-B` (High, 47%) and `WX-EV-B85B4E8E-E` (High, 83%) would both be Pending Human Review.
- **The two functions drifting apart — ✅ Done.** `assign_quadrant()` and `determine_review_status()` read the same two gates from settings (`AUTO_PUBLISH_THRESHOLD` 0.90, `HUMAN_REVIEW_THRESHOLD` 0.60), so they cannot disagree about where a threshold is (BUG-017).
- **Auto-publishing Low / Moderate / Advisory events at ≥ 0.70 — ❌ not adopted, by design.** Nothing is published without a human below 0.90 (`AUTO_PUBLISH_THRESHOLD`, `backend/app/core/config.py`). A Moderate or Advisory event at 0.60–0.89 goes to `PENDING_HUMAN_REVIEW`; below 0.60 it is `QUARANTINED`. The 0.70 in the docs was out of date: the review gate has been 0.60 since 20 Sep. BUG-068 (`a1cfe84`) corrected the docs, and also removed their claim that auto-publishing sounds sirens, sends SMS and dispatches NDRF: the alert engine was cancelled on 20 Sep.
- **1.4 — the frontend safeguard now disagrees with the backend (BUG-070, open, frontend).** `safeEventState()` returns its own 0.70 matrix whatever the API sent. With the backend fixed, that hides `HUMAN_APPROVED` and `REJECTED` (an approved event keeps its old pill and its Approve button), shows the Patna scene (Moderate, 0.62, in human review) as "Quarantined", and shows a Moderate event at 0.75 as "Auto-Published" though nothing published it. Please show `review_status` as sent; see `docs/frontend-handover.md` §15.

</details>

---

<details>
<summary>📏 <b>Issue 2: Impact Radius Scaling Anomalies (<code>impact_radius_km = 1564.0</code>)</b> — 🟡 <b>Root cause fixed</b>; the ceiling is open for Phase 3</summary>

### 2.1 The Symptom
On the Incident Events view (`/events`), card `WX-EV-43DDEC9C-B` (a rainfall event in Bhojpur, Bihar) displayed:
- **Impact Radius: 1,564.0 km**
- This radius is larger than the geographical distance between New Delhi and Kolkata (~1,500 km) and spans nearly half of India for a localized district rain event.

### 2.2 The Backend Root Causes

#### A. Outlier Aggregation in Geo-Clustering ([`backend/app/services/geo_clustering.py` lines 170–178](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/geo_clustering.py#L170-L178))
```sql
SELECT
    COALESCE((
        SELECT MAX(ST_Distance(p.geom_point::geography, (SELECT c FROM centroid)::geography))
        FROM pts p
    ), 0.0) AS radius_m
```
- `radius_km` is computed as the maximum ground distance of any constituent report from the cluster centroid:
  ```python
  "radius_km": round(float(radius_m or 0.0) / 1000.0, 4)
  ```
- If DBSCAN chains across multiple points or if an unvalidated report with an erroneous GPS coordinate (e.g. coordinates inverted, or inaccurate location string) gets clustered, `MAX(ST_Distance)` produces an astronomical radius.

#### B. The Merge Window "Snowball" Expansion ([`backend/app/services/pipeline.py` lines 485–489](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/pipeline.py#L485-L489))
```sql
AND ST_DWithin(
    center_point::geography,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
    (COALESCE(impact_radius_km, 0) + :eps) * 1000
)
```
- In `_find_mergeable_event`, incoming reports are merged into an existing event if they fall within `(impact_radius_km + eps) * 1000` meters.
- **The Runaway Bug:** If an event absorbs even a single distant outlier report, its `impact_radius_km` expands. The larger radius expands the merge threshold for the next report, creating a snowball effect where reports from adjacent or distant districts get merged into a single event, driving `impact_radius_km` past 1,500 km.

#### C. Missing Upper Ceilings in Pipeline Scoring ([`backend/app/services/pipeline.py` line 870](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/pipeline.py#L870))
```python
impact_radius = max(stats["radius_km"], 0.5)
```
- The backend enforces a minimum radius (`0.5 km`), but **imposes no physical maximum ceiling**.
- Physical hazard domains dictate strict limits (e.g. localized rainfall rarely exceeds 50–100 km).
- Additionally, if an upstream process writes `radius_m` directly without dividing by 1,000 (e.g. 1,564 meters being recorded as 1,564 km), no validation gate rejects the value.

### 2.3 Frontend Safeguard Implemented
[`frontend/src/app/events/page.tsx` lines 31–55](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/app/events/page.tsx#L31-L55) and [`frontend/src/components/EventVerificationModal.tsx` lines 47–71](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/EventVerificationModal.tsx#L47-L71) introduced `clampImpactRadius()` and `clampImpactKm()` with per-hazard plausible ceilings (e.g. 100 km for rainfall, 300 km for flood). If the raw value exceeds the ceiling, the UI renders `"unavailable"` and emits a console warning.

### 2.4 Recommended Backend Fix
1. Add hazard-aware ceiling clamps in `pipeline.py`:
   ```python
   HAZARD_RADIUS_LIMITS_KM = {
       EventType.FLOOD: 50.0,
       EventType.FLASH_FLOOD: 25.0,
       EventType.RAINFALL: 100.0,
       EventType.LANDSLIDE: 15.0,
       EventType.CYCLONE: 600.0,
   }
   ceiling = HAZARD_RADIUS_LIMITS_KM.get(event_type, 50.0)
   impact_radius = min(max(stats["radius_km"], 0.5), ceiling)
   ```
2. Cap the search window in `_find_mergeable_event` with a maximum merge limit (e.g. `LEAST(impact_radius_km, 50.0) + eps`) to stop runaway snowball merges.
3. In `geo_clustering.py`, replace strict `MAX(ST_Distance)` with the 95th percentile distance to reject spatial outliers.

### 2.5 🟡 Resolution (24 Sep 2026)

- **The 1,564 km radius — ✅ Done, at the root cause** (BUG-065, `e55ea41`). The seeder linked 40% of its ~1,200 mixed-source reports and 30% of its ~8,200 citizen reports to a random event anywhere in India, so a Bhojpur event owned reports in Chennai and Delhi. Seeded rows keep their stored 2–25 km radius, but once the live pipeline merges one real report into such an event it recomputes the footprint over every linked report, and the radius becomes the distance to the farthest city. A seeded report now links only to an event in its own city: farthest linked report 11.7 km, median 4.7 km (the old seeder: 2,096 km).
- **2.2B / 2.2C — the merge catchment grows with the event and has no ceiling — ⏳ Open, Phase 3** (BUG-066, confirmed). With real data the growth is bounded by DBSCAN's 5 km chaining and the 120-minute merge window, but nothing caps it. Phase 3 makes clustering and merging per hazard family, each with its own radius and time window (water 5 km / 6 h, convective 10 km / 3 h, thermal 25 km / 24 h, visibility 15 km / 12 h, already defined in `backend/app/services/hazards.py`), and the catchment and the radius get their ceiling there. It is not patched on its own because it changes scores.
- **2.2A — `MAX(ST_Distance)` with no outlier filter — ⏳ Open, with BUG-066.** Coordinates outside India are refused with a 422 and never stored, so no such point can join a cluster; the remaining path to a far-off member is the unbounded merge above.
- Until Phase 3 lands, the frontend's `clampImpactRadius()` / `clampImpactKm()` guard stays useful.

</details>

---

<details>
<summary>📊 <b>Issue 3: Discrepancy Between Reports Trend and Dashboard Summary (KPI Strip)</b> — ✅ <b>Resolved</b></summary>

### 3.1 The Symptom
On the Commander Dashboard (`/`):
- The KPI strip shows **9,401 Total Reports** (or **1,248** in demo mode).
- The "Incoming Reports Trend" line chart immediately below it shows daily counts hovering around **0 to 4 reports**, with a maximum y-axis value of 4.

### 3.2 The Backend Root Causes

#### A. Unfiltered All-Time KPI vs. Windowed Daily Series
1. **Dashboard Summary Query ([`backend/app/api/dashboard.py` lines 56–61](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/api/dashboard.py#L56-L61)):**
   ```sql
   WITH
   current_window AS (
       SELECT
           COUNT(*) AS total_reports,
           COUNT(*) FILTER (WHERE source_type = 'CITIZEN_APP') AS citizen_reports
       FROM raw_reports
   ),
   ```
   `current_window` does **not** filter by date! It executes `COUNT(*) FROM raw_reports` across the **entire table for all time**.

2. **Reports Trend Query ([`backend/app/api/reports.py` lines 99–111](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/api/reports.py#L99-L111)):**
   ```sql
   WITH date_series AS (
       SELECT generate_series(
           CURRENT_DATE - CAST(:days AS int),
           CURRENT_DATE::date,
           '1 day'::interval
       )::date AS day
   )
   SELECT
       ds.day,
       COALESCE(COUNT(r.id), 0) AS reports
   FROM date_series ds
   LEFT JOIN raw_reports r ON r.created_at::date = ds.day
   GROUP BY ds.day
   ORDER BY ds.day
   ```
   The trend endpoint groups strictly by the last 7 calendar days from `CURRENT_DATE`.

3. **The Timestamp Gap:**
   - In production and demo staging, data seeded by `scripts/seed_national_data.py` assigns timestamps relative to when the script was run (`now - timedelta(...)`).
   - If the seed script was run a week ago, `raw_reports` contains thousands of historical rows, so `total_reports` displays `9,401`.
   - However, for the rolling 7-day window ending today (`CURRENT_DATE`), there are 0 to 4 recent reports.
   - Consequently, the user sees 9,400+ total reports on the card, but a flat-zero trend line.

#### B. Static Mock / Fallback Contradiction
When running with fallback mock data (`DEMO_MODE=true` or database unavailable):
- In `backend/app/api/dashboard.py` (lines 17–23):
  ```python
  DEMO_KPIS = {
      "total_reports": 1248,
      ...
      "citizen_reports": 8421, # <--- BUG: citizen reports (8,421) > total reports (1,248)!
  }
  ```
- In `backend/app/api/reports.py` (lines 76–84):
  `DEMO_TREND` returns hardcoded dates: `"09 Sep"` (85), `"10 Sep"` (112), ..., `"15 Sep"` (134), whose sum equals exactly 1,248.
- In live database mode, this alignment breaks completely because the two endpoints query disparate timestamp windows.

### 3.3 Recommended Backend Fix
1. Clarify the semantics of the KPI summary:
   - If `total_reports` is intended to reflect the current operational cycle (e.g. last 7 or 30 days), add an explicit time filter:
     ```sql
     WHERE created_at >= NOW() - INTERVAL '7 days'
     ```
   - If `total_reports` is intended to be cumulative lifetime reports, rename the KPI field to `lifetime_reports` and provide a corresponding `active_cycle_reports` field.
2. In `scripts/seed_national_data.py`, ensure seeded timestamps are generated relative to execution time (`NOW()`), or provide a replay mechanism so demo environments always have fresh data within the active 7-day window.
3. Fix the mock constant in `backend/app/api/dashboard.py` where `citizen_reports (8421)` exceeds `total_reports (1248)`.

### 3.4 ✅ Resolution (24 Sep 2026)

- **3.2B — `DEMO_KPIS` has 8,421 citizen reports out of 1,248 — ✅ Done** (BUG-069, `a89d948`, with a test in `backend/tests/test_demo_mode.py`). Demo KPIs are served only with `DEMO_MODE=true`, which stays false on the team server.
- **3.2A — "Total Reports" vs the 7-day trend — ✅ no backend defect.** Both numbers are right: `total_reports` counts every report ever received (its deltas are over 24 hours), and the trend chart covers the last 7–30 days. A database seeded a week earlier has thousands of old rows and a flat recent week. If the card should read "all time", that is its label on the dashboard.
- **3.3, recommendation 2 — seeded timestamps — ✅ already so.** The seeder stamps rows `now − timedelta(hours=…)` at the moment it runs; rows seeded a week ago simply age out of the 7-day window. A replay of a real day is Phase 6.

</details>

---

<details>
<summary>🗺️ <b>Issue 4: Map Viewport & Default Focus</b> — ✅ <b>No backend change needed</b></summary>

### 4.1 The Symptom
On the main live map (`/` and `/events`):
- The default zoom level (`4.6`) was positioned slightly too wide, displaying excessive portions of the Indian Ocean and clipping northern border regions (Jammu & Kashmir, Ladakh) and eastern states on standard 1080p command center displays.

### 4.2 Frontend Safeguard Implemented
[`frontend/src/components/client-only/GlobeEventMap.tsx` lines 333 & 965–970](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/client-only/GlobeEventMap.tsx#L333-L335) updated the default zoom to `5.0` centered at `[22.5, 82.5]` to ensure the entire Indian subcontinent fits cleanly within standard aspect ratios.

### 4.3 Recommended Backend Alignment
Any backend configurations or metadata endpoints delivering default bounding boxes (e.g., `INDIA_BOUNDS` or map tile presets) should align with `zoom: 5.0` / Center `[22.5, 82.5]`.

### 4.4 ✅ Resolution (24 Sep 2026)

No backend change needed. No backend endpoint or setting serves a default map view, zoom or bounding box. The only India box in the backend (`INDIA_MIN_LNG`, `INDIA_MAX_LAT`, … in `backend/app/services/geocoding.py`) refuses out-of-India coordinates on submit; it is a validation limit, not a view, and nothing in it has to match the map. The frontend's `zoom 5.0` / `[22.5, 82.5]` is the only default.

</details>

---

<details open>
<summary>📋 <b>Summary Table of Files & Recommended Backend Changes</b></summary>

| File | Exact Bug Description | Severity | Recommended Fix | Status (24 Sep 2026) |
| :--- | :--- | :--- | :--- | :--- |
| [`scripts/seed_national_data.py` (L233–241)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/scripts/seed_national_data.py#L233-L241) | `review_status` picked via `random.choices()`, violating `quadrant` and the 2×2 decision matrix. | **High** | Replace random selection with deterministic `derive_event_state(severity, confidence)`. | ✅ **Done** — BUG-064 (`da63990`): status and quadrant from `FusionEngine`. Also BUG-065 (`e55ea41`): reports link only to an event in their own city |
| [`backend/app/services/fusion_engine.py` (L263–293)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/fusion_engine.py#L263-L293) | `determine_review_status` does not consider `severity`. | **High** | Unify `assign_quadrant` and `determine_review_status` into a single matrix resolver. | ✅ **Done** — BUG-067 (`6083572`): High and Critical never quarantined; both functions read the same gates. Auto-publishing minor events at ≥ 0.70 ❌ not adopted |
| [`backend/app/services/pipeline.py` (L485–489, L870)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/pipeline.py#L870) | No upper ceiling clamp on `impact_radius`; runaway merge window causes snowball cluster expansion. | **Medium** | Enforce domain-specific radius ceilings (e.g. 100 km for rain); cap merge search window. | ⏳ **Open** — BUG-066, capped per hazard family in Phase 3 |
| [`backend/app/services/geo_clustering.py` (L170–178)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/geo_clustering.py#L170-L178) | Radius uses `MAX(ST_Distance)` without outlier filtering. | **Medium** | Use 95th percentile distance or reject spatial outliers prior to radius derivation. | ⏳ **Open** — with BUG-066, Phase 3 |
| [`backend/app/api/dashboard.py` (L17–23, L56–61)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/api/dashboard.py#L56-L61) | `total_reports` counts lifetime table rows, conflicting with 7-day trend; `citizen_reports > total_reports` in `DEMO_KPIS`. | **Medium** | Align time filters between dashboard KPI and trend endpoints; fix impossible numbers in `DEMO_KPIS`. | ✅ **Done** — BUG-069 (`a89d948`). All time vs 7 days is not a defect |

</details>

---

*Document generated for engineering alignment and backend handover.*  
*Resolution status added 24 Sep 2026 by Aditya (backend).*
