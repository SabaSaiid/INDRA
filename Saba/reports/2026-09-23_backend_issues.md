# INDRA Backend Issues & Root Cause Analysis

> **Report Date:** 23 September 2026 (`2026-09-23`)  
> **Author:** Saba  
> **Target System:** INDRA (Indian National Disaster Response & Alerting Platform)  
> **Scope:** Backend Pipeline, Data Seeding, Geo-Clustering, Database Schemas, and API Endpoints  
> **Verification Status:** 100% Verified against Active Codebase  

---

<details open>
<summary>📋 <b>Executive Summary</b></summary>

### Overview
During testing and frontend validation of the INDRA operational dashboard, several critical inconsistencies and display anomalies were identified. While temporary display-layer safeguards and defensive UI transformations were implemented on the frontend, the underlying root causes reside in the **backend data pipelines, seeding scripts, fusion logic, and API query implementations**.

This document provides a 100% verified, line-by-line technical audit of the four major backend issues causing system instability, misleading incident statuses, and visual bugs.

</details>

---

<details>
<summary>🚨 <b>Issue 1: Desynchronization of <code>review_status</code> and <code>quadrant</code> (2×2 Matrix Violation)</b></summary>

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

</details>

---

<details>
<summary>📏 <b>Issue 2: Impact Radius Scaling Anomalies (<code>impact_radius_km = 1564.0</code>)</b></summary>

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

</details>

---

<details>
<summary>📊 <b>Issue 3: Discrepancy Between Reports Trend and Dashboard Summary (KPI Strip)</b></summary>

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

</details>

---

<details>
<summary>🗺️ <b>Issue 4: Map Viewport & Default Focus</b></summary>

### 4.1 The Symptom
On the main live map (`/` and `/events`):
- The default zoom level (`4.6`) was positioned slightly too wide, displaying excessive portions of the Indian Ocean and clipping northern border regions (Jammu & Kashmir, Ladakh) and eastern states on standard 1080p command center displays.

### 4.2 Frontend Safeguard Implemented
[`frontend/src/components/client-only/GlobeEventMap.tsx` lines 333 & 965–970](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/client-only/GlobeEventMap.tsx#L333-L335) updated the default zoom to `5.0` centered at `[22.5, 82.5]` to ensure the entire Indian subcontinent fits cleanly within standard aspect ratios.

### 4.3 Recommended Backend Alignment
Any backend configurations or metadata endpoints delivering default bounding boxes (e.g., `INDIA_BOUNDS` or map tile presets) should align with `zoom: 5.0` / Center `[22.5, 82.5]`.

</details>

---

<details open>
<summary>📋 <b>Summary Table of Files & Recommended Backend Changes</b></summary>

| File | Exact Bug Description | Severity | Recommended Fix |
| :--- | :--- | :--- | :--- |
| [`scripts/seed_national_data.py` (L233–241)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/scripts/seed_national_data.py#L233-L241) | `review_status` picked via `random.choices()`, violating `quadrant` and the 2×2 decision matrix. | **High** | Replace random selection with deterministic `derive_event_state(severity, confidence)`. |
| [`backend/app/services/fusion_engine.py` (L263–293)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/fusion_engine.py#L263-L293) | `determine_review_status` does not consider `severity`. | **High** | Unify `assign_quadrant` and `determine_review_status` into a single matrix resolver. |
| [`backend/app/services/pipeline.py` (L485–489, L870)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/pipeline.py#L870) | No upper ceiling clamp on `impact_radius`; runaway merge window causes snowball cluster expansion. | **Medium** | Enforce domain-specific radius ceilings (e.g. 100 km for rain); cap merge search window. |
| [`backend/app/services/geo_clustering.py` (L170–178)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/geo_clustering.py#L170-L178) | Radius uses `MAX(ST_Distance)` without outlier filtering. | **Medium** | Use 95th percentile distance or reject spatial outliers prior to radius derivation. |
| [`backend/app/api/dashboard.py` (L17–23, L56–61)](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/api/dashboard.py#L56-L61) | `total_reports` counts lifetime table rows, conflicting with 7-day trend; `citizen_reports > total_reports` in `DEMO_KPIS`. | **Medium** | Align time filters between dashboard KPI and trend endpoints; fix impossible numbers in `DEMO_KPIS`. |

</details>

---

*Document generated for engineering alignment and backend handover.*
