# 🇮🇳 INDRA — Industrial-Grade Multi-Persona Platform Architecture & October 2026 Strategic Plan

**Document:** `PLAN for Oct.md`  
**Target Release:** INDRA Enterprise v2.0 / SIH Grand Finale  
**Author / Team:** Saba Saeed & Team Sixth Sense  
**System:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Git Branch:** `Saba-1-oct-2026`  
**Problem Statement:** SIH26069 — Ministry of Earth Sciences (MoES) / NDMA  

---

## Executive Summary & Vision

Disaster response fails when **different operational roles are forced to look at the same generic screen**. 

During extreme weather events (such as the 2023 North India floods or Cyclone Biparjoy), four distinct stakeholders operate under radically different physical conditions, cognitive loads, and decision timelines:
1. **Control Room / Incident Commanders (SEOC / DEOC / Nodal Officers)** need high-level tactical oversight, cross-district incident governance, rapid verification receipts, escalation controls, and official broadcast authorization.
2. **NDRF & Rescue Teams (SDRF / QRT / Field Responders)** need an ultra-fast, mobile-first, offline-tolerant tactical PWA operating in pouring rain with sunlight readability, turn-by-turn flood-safe routing, live victim distress pins, ground-truth reporting, and one-tap team status updates.
3. **Data & Meteorological Analysts (Intelligence & Science Desk)** need deep diagnostic telemetry, raw sensor time-series (Open-Meteo, METAR, AWS, CWC gauges), DBSCAN spatial clustering diagnostics, AI/ML model calibration telemetry, H3 hexagonal drill-downs, and bulk archive replay.
4. **Citizens & Community Reporters** need an intuitive, vernacular (12+ Indian languages), zero-login reporting portal with instant hazard warnings, evacuation shelter routes, safe zones, and live tracking of their report docket without exposing their private PII (DPDP Act 2023 compliant).

This document establishes the **industrial-grade architectural blueprint and step-by-step October 2026 roadmap** to upgrade INDRA from a unified operator console into a **multi-persona, role-tailored national emergency operating system**.

```
                                  INDRA UNIFIED CORE
            ┌─────────────────────────────────────────────────────────────┐
            │   FastAPI Modular Monolith • PostGIS • Redpanda • Redis     │
            │   Verification Engine v2 • SHA-256 Tamper-Evident Ledger    │
            └──────┬──────────────┬──────────────┬──────────────┬─────────┘
                   │              │              │              │
         WebSocket │    WebSocket │    WebSocket │    WebSocket │
     /ws/control-room   /ws/field/{id}  /ws/analyst   /ws/public
                   ▼              ▼              ▼              ▼
           ┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
           │   COMMAND    ││     NDRF     ││   ANALYST    ││   CITIZEN    │
           │ CONTROL ROOM ││ FIELD RESCUE ││ INTELLIGENCE ││ COMMUNITY PWA│
           │  DASHBOARD   ││  TACTICAL UI ││   TELEMETRY  ││   PORTAL     │
           ├──────────────┤├──────────────┤├──────────────┤├──────────────┤
           │ High-density ││ Mobile-first ││ Deep-dive GIS││ Vernacular   │
           │ Multi-monitor││ Offline PWA  ││ Time-series  ││ Zero-login   │
           │ Review Queue ││ Low-bandwidth││ ML telemetry ││ SOS Beacon   │
           │ Broadcast Cap││ GPS & Photos ││ SQL / Exports││ DPDP-shield  │
           └──────────────┘└──────────────┘└──────────────┘└──────────────┘
```

---

## 1. Persona Architectural Profiles & Requirements Matrix

| Dimension | 1. Admin / Control Room | 2. NDRF & Rescue Teams | 3. Meteorological Analysts | 4. Citizens & Reporters |
|---|---|---|---|---|
| **Primary User** | District Magistrate, Nodal Officer, SEOC Chief | NDRF Battalion Commander, Boat Team Lead, SDRF Rescuer | Meteorologist, GIS Specialist, Data Scientist | Citizen in distress, Village Sarpanch, Local Reporter |
| **Operating Environment** | Command center, high-speed fiber, 4K multi-displays | Field, torrential rain, 2G/3G patchy network, wet screens | Operations room, workstation, multi-tab analytics | Mobile browser, outdoor/home, emergency conditions |
| **Key Objectives** | Verify events, allocate budgets/units, issue alerts | Save lives, navigate hazards, report ground reality | Detect data anomalies, validate models, inspect receipts | Report local flood, check safe shelters, track status |
| **Authentication** | Mandatory Hardware 2FA / TOTP + RBAC (`COMMANDER`/`ADMIN`) | Quick PIN / QR / Biometric device token (`FIELD_RESPONDER`) | SSO / Institutional JWT (`ANALYST`) | Zero-friction anonymous or phone OTP (`CITIZEN`) |
| **Critical Metric** | Incident Resolution Time & Evacuation Reach | Response Latency & Ground Team Safety | Verification Accuracy & Spatial Precision | Safety Advisory Timeliness & Privacy |
| **Data Visibility** | Full national tactical picture & audit ledger | Local district/sub-division task assignments | Raw sensor readings, ML feature weights, DLQ logs | Coarse district safety heatmaps, verified alerts only |

---

## 2. Detailed Profile Specifications

### Profile A: Admin & State Control Room (SEOC / Nodal Officers)
* **Design Philosophy:** *Maximum situational awareness, zero latency, absolute decision accountability.*
* **Core Screens & Capabilities:**
  1. **National/State Situational Wall:** Full-screen 3D globe and interactive tactical map with real-time incident cluster boundaries (concave hulls), active SACHET alerts, and rainfall isobar layers.
  2. **Human-in-the-Loop Review Queue:** Rapid triaging of events flagged as `PENDING_HUMAN_REVIEW` or `QUARANTINED`. Side-by-side inspection of citizen photos, satellite/radar passes, and airport METAR observations.
  3. **Official Action Dispatcher:** One-click approval to transition events from `PENDING` to `HUMAN_APPROVED` with cryptographic signing into the SHA-256 audit ledger.
  4. **Public Warning Broadcast Gateway:** Interface to trigger OASIS CAP v1.2 emergency alerts, sending targeted Cell Broadcast notifications via C-DOT/SACHET integration.
  5. **Team Roster & Resource Mobilization:** Real-time visibility into NDRF/SDRF unit deployments, equipment availability (inflatable boats, de-watering pumps), and operational duty statuses.

### Profile B: NDRF & Field Rescue Teams
* **Design Philosophy:** *Tactical utility, high contrast, battery-efficient, offline-first.*
* **Core Screens & Capabilities:**
  1. **Task Action Queue:** Dispatched rescue assignments prioritized by life-safety severity (`CRITICAL` urban flood drowning risk vs. `MODERATE` road waterlogging).
  2. **Tactical Field Map (Offline Cached):** Vector map tiles cached locally via IndexedDB. Displays flood depth contours, road impassability vectors, and safe extraction zones.
  3. **Ground-Truth Check-In:** Rapid camera capture with water depth estimation markers (ankle, knee, waist, overhead), GPS auto-tagging, and survivor count logging.
  4. **Field Team Telemetry:** Auto-beaconing of responder GPS location every 30 seconds back to the control room when connected; queued in local SQLite/IndexedDB when offline.
  5. **SOS Emergency Beacon:** Immediate "Mayday / Team in Danger" distress trigger that overrides all control room audio/visual alerts.

### Profile C: Meteorological & Data Analysts (Intelligence Desk)
* **Design Philosophy:** *Exhaustive telemetry, mathematical transparency, deep diagnostic tooling.*
* **Core Screens & Capabilities:**
  1. **Telemetry & Sensor Correlation Studio:** Multi-axis time-series correlating Open-Meteo precipitation curves, IMD aerodrome METAR pressure/wind shifts, and citizen report spikes.
  2. **Verification Receipt Deep Inspector:** Mathematical breakdowns of all 7 verification factors, weights, normalized confidence scores, and missing-factor penalties.
  3. **Geospatial Clustering Tuning:** Interactive H3 hexagon resolution switcher (Res 6, 7, 8) and DBSCAN parameter inspector (`eps`, `min_samples`) to detect split or over-merged clusters.
  4. **AI/ML Model Diagnostics & Feature Telemetry:** Confusion matrices, drift detection graphs, false-positive/negative rates across hazard types, and raw token attributions for the NLP classifier.
  5. **Data Lake Archival & Bulk Replay:** Interface to replay historical disaster days (e.g., 2023 Patna floods) through the pipeline to test algorithm adjustments.

### Profile D: Citizens & Community Reporters
* **Design Philosophy:** *Accessible to every citizen, zero friction, highly vernacular, privacy-preserving.*
* **Core Screens & Capabilities:**
  1. **10-Second Hazard Reporting:** Simple 3-step filing: *What is happening?* (icon grid: Flood, Tree Fallen, Cloudburst), *Where?* (auto GPS with manual street search), *Photo/Voice* (optional camera upload or 15s voice note).
  2. **Vernacular Multilingual Interface:** Native translations across 12 Indian languages (Hindi, Marathi, Bengali, Tamil, Telugu, Gujarati, Odia, Assamese, Kannada, Malayalam, Punjabi, English) with voice prompt support.
  3. **Live Hyper-Local Safety Radar:** User's current location shown against active verified danger zones, official SACHET red/orange alerts, and nearest NDRF relief shelters.
  4. **Anonymous Docket Tracker:** Citizens track their submission status (`Received` → `Corroborated by Radar` → `Rescue Dispatched`) via a random UUID docket without requiring an account.
  5. **DPDP Act Privacy Shield:** Automatic blurring of faces and vehicle license plates on uploaded photos before ingestion; coordinates fuzzed to 1 km on public views.

---

## 3. Frontend Architecture Improvements

### 3.1 App Router Structural Reorganization
Transition the Next.js 14 architecture into clean, persona-scoped route groups with role-enforced layouts:

```
frontend/src/app/
├── (public)/                      # Citizen & Public Portal (No Auth Required)
│   ├── page.tsx                   # Citizen Home & Emergency Warning Radar
│   ├── report/page.tsx            # Zero-friction Citizen Hazard Filing
│   ├── track/[docket]/page.tsx    # Anonymous Docket Tracking
│   └── shelters/page.tsx          # Relief Camps & Evacuation Routes
│
├── (control-room)/                # Command & Operations Console
│   ├── layout.tsx                 # High-Density Tactical Header & Incident Ticker
│   ├── command/page.tsx           # Multi-screen Tactical Map & Live Feeds
│   ├── review/page.tsx            # Human Review Queue & Receipt Approval
│   └── broadcast/page.tsx         # Official Warning & CAP Broadcaster
│
├── (field)/                       # NDRF / SDRF Tactical Mobile PWA
│   ├── layout.tsx                 # Ultra-compact, Touch-friendly Mobile Shell
│   ├── tasks/page.tsx             # Assigned Dispatch Tasks & Navigation
│   ├── ground-truth/page.tsx      # Field Water Depth & Situation Report
│   └── team-status/page.tsx       # Equipment, Personnel & Battery Status
│
└── (analyst)/                     # Scientific & Telemetry Workbench
    ├── layout.tsx                 # Split-pane Telemetry Workspace
    ├── intelligence/page.tsx      # Sensor Fusion & Correlation Studio
    ├── receipts/[id]/page.tsx     # 100-Point Verification Math Inspector
    ├── ml-diagnostics/page.tsx    # Model Drift, Embeddings & Clustering
    └── replay/page.tsx            # Historical Disaster Simulator
```

### 3.2 Offline-First PWA for Field Responders
* **Service Worker Strategy:** Use Workbox with a dual-cache policy:
  * *Static Assets & Shell:* Cache-first strategy for rapid instant booting even in zero-network scenarios.
  * *Vector Tiles:* Pre-cache district boundary tiles and street networks for the team's Area of Responsibility (AOR) into IndexedDB.
* **Background Sync Queue:** When an NDRF rescuer submits a ground-truth report without internet, the payload and compressed image are stored in an IndexedDB `offline_queue`. As soon as 2G/3G connectivity is detected, a background sync worker automatically flushes the queue to `POST /api/reports/submit`.

### 3.3 Persona-Tailored Design Systems
* **Control Room:** Dark-mode tactical theme (`#0B0F17` background) with high-contrast amber/rose emergency indicators, optimized for 4K video walls and low eye fatigue during 24-hour operations.
* **NDRF Tactical:** Military-grade high-contrast mode with yellow/cyan high-visibility markers, 48px touch targets for gloved fingers, and sunlight-readable monochrome toggle.
* **Citizen Portal:** Warm, accessible government public service styling following the *India Design System* guidelines, large vernacular typography, and WCAG 2.1 AAA accessibility.

### 3.4 WebSocket Multiplexing & Reconnection
* Currently, every tab opens raw WebSockets that can flood the backend.
* Create a unified `IndraSocketProvider` that opens **one authenticated WebSocket per client** and multiplexes subscriptions across virtual channels:
  * `subscribe("events:critical")`
  * `subscribe("team:dispatch:{team_id}")`
  * `subscribe("system:telemetry")`
* Implement exponential backoff with jitter and automated state synchronization upon reconnection.

---

## 4. Backend Architecture Improvements

### 4.1 Granular RBAC & Attribute-Based Access Control (ABAC)
Upgrade `backend/app/core/security.py` to enforce persona and agency scoping:

```python
# Conceptual Security Scoping Matrix
class Permission(str, Enum):
    EVENT_REVIEW = "event:review"              # Control Room only
    BROADCAST_ALERT = "alert:broadcast"        # Admin / State Nodal Officer
    FIELD_CHECKIN = "field:checkin"            # NDRF / SDRF Field Responders
    INSPECT_RECEIPT = "receipt:inspect_deep"   # Analyst & Commander
    PUBLIC_REPORT = "report:citizen_submit"    # Public (Rate-limited)

class UserProfile:
    role: OperatorRole                         # COMMANDER, FIELD_RESPONDER, ANALYST, CITIZEN
    agency: TeamAgency                         # NDRF, SDRF, IMD, NDMA, CWC
    jurisdiction_district_ids: List[int]       # Spatial filtering (AOR)
```

* **Route Guards:** Endpoints enforce both role permissions and spatial boundaries. An NDRF officer assigned to Patna District can only update tasks within their district boundary.

### 4.2 New Data Models & Alembic Migrations
Add the following core tables to support multi-persona dispatch and field tracking:
1. `dispatch_assignments`:
   - Links a `verified_event_id` to a `team_id`.
   - Priority (`P1_IMMEDIATE_LIFE_SAFETY`, `P2_EVACUATION`, `P3_RELIEF_SUPPLY`).
   - Status (`DISPATCHED`, `EN_ROUTE`, `ON_SCENE`, `COMPLETED`, `ABORTED`).
   - Navigation target (lat/lon, concave hull waypoint).
2. `field_checkins`:
   - Ground-truth validation submitted by responders on scene.
   - Measured water depth (cm), confirmed hazard category, accessible roads.
   - Rescued victim count, remaining stranded count.
3. `citizen_dockets`:
   - Privacy-preserving table mapping anonymous UUID dockets to `report_id`.
   - Allows citizens to check verification progress without exposing their IP, phone, or identity.

### 4.3 Redis Pub/Sub WebSocket Highway
* **Current Limitation:** Single backend process holds in-memory WebSocket connections (BUG-011).
* **Industrial Upgrade:** Deploy Redis Pub/Sub channels (`indra:ws:control_room`, `indra:ws:field:{team_id}`, `indra:ws:public`).
* Multiple Uvicorn worker processes or cluster nodes publish event lifecycle updates to Redis; Redis fans them out to connected clients across nodes instantly.

### 4.4 Privacy & DPDP Act 2023 Compliance Gate
* **Fix BUG-124:** In `backend/app/api/reports.py`, create a strict serializer split:
  * `PublicReportOut`: Coarse coordinates (fuzzed to 2 decimal places / ~1.1 km), citizen description stripped of phone numbers/names, media served without EXIF metadata.
  * `TacticalReportOut`: Full micro-precision coordinates, raw text, and camera EXIF metadata accessible **only** to authenticated `COMMANDER` and `ANALYST` roles with logged audit justification.

---

## 5. Industrial-Grade AI & Machine Learning (Layer 4)

To move Layer 4 from its current **synthetic-development advisory state** (`factor_coverage: 0.80`) into a **production-grade validation pipeline**, we will implement four key enhancements:

```
                          LAYER 4 INDUSTRIAL AI/ML PIPELINE
  Raw Input
  (Text/Media)
      │
      ├──► [Vision Engine] ────► Fast FloodNet SegNet ──► Water Depth & Vehicle Submersion
      │                          pHash + EXIF Matcher ──► Recycled / Misleading Media Flag
      │
      ├──► [NLP Engine] ───────► IndicBERT Multilingual ─► 16 Hazard Categories + Urgency
      │                          Regex Guardrail Matrix ──► Zero False Negatives on Flood/Landslide
      │
      ├──► [Climate Anomaly] ──► 30-Year IMD Normal ────► Z-score Anomaly Deviation
      │
      └──► [Credibility Core] ─► Bayesian Source Prior ──► Corroboration Weight
                                         │
                                         ▼
                            [Unified Verification Receipt]
                           (Confidence Score: 0.00 – 1.00)
```

### 5.1 Production Multimodal Computer Vision (`vision_analysis`)
* **Model Selection:** Lightweight `YOLOv8-Nano` or `MobileNetV4-SegNet` exported to ONNX format with INT8 quantization (runnable in <40ms on standard CPUs without GPU dependencies).
* **Specific Tasks:**
  1. **Water Surface Segmentation:** Detect water presence in citizen photographs and compute surface area ratio.
  2. **Submersion Keypoint Reference:** Detect standard urban reference markers (car tires, car headlights, humans, motorcycle seats) to estimate real-world depth ($<30\text{ cm}$, $30\text{--}60\text{ cm}$, $>100\text{ cm}$).
  3. **Recycled Media Defense:** Compute 64-bit Perceptual Hash (pHash) and compare against the historical media database (`report_media.phash`). Flag duplicates or media re-uploaded from previous years.
* **Safety Gate:** If image classification confidence $<0.75$, the factor is gracefully marked `insufficient_confidence` rather than guessing, preserving verification honesty.

### 5.2 Multilingual Indic NLP Classifier (`text_classification`)
* **Model Selection:** Fine-tune `IndicBERT-v2` or `SetFit` on a curated dataset of 5,000+ Indian disaster social media posts and citizen reports in Hindi, Marathi, Bengali, Tamil, Telugu, and Hinglish.
* **Cost-Sensitive Loss Guard:**
  * Standard models fail by classifying a critical Hindi flood report (*"pura mohalla doob gaya hai, bache fase hain"*) as generic rain.
  * Implement an asymmetric loss function penalizing false negatives on `URBAN_FLOOD`, `CLOUDBURST`, and `LANDSLIDE` by **$10\times$** relative to ordinary errors.
* **Deterministic Keyword Override:** Hardcode published safety rules: if keywords such as *"drowning"*, *" बह गया"*, *"underwater"*, or *"boat needed"* are detected, the classifier is strictly prohibited from predicting `NOT_RELEVANT`.

### 5.3 Historical Climate Anomaly Baseline (`anomaly_detection`)
* **Objective:** Activate the `anomaly_detection` factor (5% weight), raising full operational coverage.
* **Implementation:**
  * Ingest the 30-year IMD gridded monthly rainfall normals for all 737 districts into `climate_normals`.
  * Compute the real-time standardized precipitation index:
    $$Z = \frac{R_{\text{observed}} - \mu_{\text{district, month}}}{\sigma_{\text{district, month}}}$$
  * An extreme cloudburst ($Z \ge 3.0$) automatically elevates event urgency and triggers an anomaly alert for analysts.

### 5.4 Automated Triage & Priority Dispatch Engine
* Automatically evaluate incoming corroborated events against NDRF operational criteria:
  * If $\text{Severity} == \text{CRITICAL}$ and $\text{Confidence} \ge 0.75$ and water depth $\ge 100\text{ cm}$:
    * Auto-generate a **Priority 1 Dispatch Recommendation** in the Control Room.
    * Pre-calculate the nearest available NDRF battalion and estimated response ETA.

---

## 6. Step-by-Step Implementation Plan for October 2026

```
                           OCTOBER 2026 SPRINT TIMELINE
┌─────────────────────────┬─────────────────────────┬─────────────────────────┬─────────────────────────┐
│         WEEK 1          │         WEEK 2          │         WEEK 3          │         WEEK 4          │
│       OCT 01 - 07       │       OCT 08 - 14       │       OCT 15 - 21       │       OCT 22 - 31       │
├─────────────────────────┼─────────────────────────┼─────────────────────────┼─────────────────────────┤
│ • Architecture Scaffold │ • NDRF Field PWA        │ • Control Room Suite    │ • Model Fine-Tuning     │
│ • DB Migrations (Tasks) │ • Offline Sync Engine   │ • Analyst Deep-Dive GIS │ • Chaos & Load Testing  │
│ • RBAC Route Guards     │ • Citizen Reporting PWA │ • Redis Pub/Sub Cluster │ • SIH Grand Finale Drill│
│ • DPDP Privacy Gateway  │ • Vernacular i18n (12x) │ • External Audit Anchor │ • Production Hardening  │
└─────────────────────────┴─────────────────────────┴─────────────────────────┴─────────────────────────┘
```

### Week 1 (Oct 01 – Oct 07): Architectural Scaffolding, RBAC & Privacy Gate
* **Day 1–2 (Backend):**
  * Create Alembic migration `0024_dispatch_and_tasks.py` (`dispatch_assignments`, `field_checkins`, `citizen_dockets`).
  * Implement DPDP Act privacy sanitizer in `backend/app/api/reports.py` (resolving BUG-124).
  * Expand `OperatorRole` with granular permissions in `backend/app/core/security.py`.
* **Day 3–4 (Frontend):**
  * Reorganize `frontend/src/app` into route groups `(control-room)`, `(field)`, `(analyst)`, `(public)`.
  * Implement role-gated navigation and layout switchers based on JWT claims.
  * Clean up residual mock telemetry in `RiskZonesSection.tsx` (remove stock photos and fake baseline zones).
* **Day 5–7 (Testing & Verification):**
  * Write backend tests for new dispatch tables and privacy-preserving report serializers.
  * Verify all existing 1,788 pytest tests continue to pass.

### Week 2 (Oct 08 – Oct 14): NDRF Field Tactical App & Citizen Portal
* **Day 8–10 (NDRF Field PWA):**
  * Build `(field)/tasks` and `(field)/ground-truth` mobile UI with high-contrast tactical styling.
  * Integrate Service Worker with Workbox and IndexedDB offline queue for offline report capture.
  * Add one-tap team duty toggles (`AVAILABLE`, `EN_ROUTE`, `ON_SCENE`, `RETURNING`).
* **Day 11–13 (Citizen Portal):**
  * Build zero-login 3-step reporting wizard with vernacular language switcher (12 Indian languages).
  * Implement anonymous docket tracking (`/track/[docket]`) querying `citizen_dockets`.
  * Embed hyper-local safety radar displaying nearby SACHET warnings and relief camps.
* **Day 14 (Field Simulation Drill):**
  * Conduct simulated offline drill: disconnect network on mobile device, submit 5 reports, reconnect, verify auto-flush and deduplication in backend.

### Week 3 (Oct 15 – Oct 21): Control Room, Analyst Suite & Redis Scale-Out
* **Day 15–17 (Control Room & Dispatch):**
  * Build multi-monitor command center UI with incident cluster concave hulls and 1-click dispatch modal.
  * Implement CAP v1.2 XML alert generation endpoint (`POST /api/alerts/broadcast-cap`).
* **Day 18–19 (Analyst Intelligence Workbench):**
  * Wire time-series sensor correlation dashboard (Open-Meteo rainfall vs. METAR stations vs. citizen volume).
  * Build mathematical Verification Receipt visualizer with live weight sliders for scenario testing.
* **Day 20–21 (Scale-Out & Infrastructure):**
  * Migrate WebSocket broadcast system to Redis Pub/Sub (`indra:ws:broadcast`).
  * Implement external head-hash anchoring for the `audit_logs` SHA-256 chain (preventing tail truncation).

### Week 4 (Oct 22 – Oct 31): Industrial AI/ML Activation, Load Testing & Grand Finale Polish
* **Day 22–24 (AI/ML Production Gate):**
  * Integrate lightweight ONNX water segmentation model into `backend/app/ml/vision/`.
  * Seed 30-year IMD climate normals for anomaly Z-score calculation.
  * Conduct release gate validation (`validate_ml_release()`) and update `factor_coverage` to `0.95`.
* **Day 25–27 (Load Testing & Resilience):**
  * Build `POST /api/ingest/batch` and run load tests simulating 10,000 reports/minute through Redpanda.
  * Verify zero report drops and confirm DLQ replay resilience.
* **Day 28–31 (Final Dry Run & Demonstration Polish):**
  * Complete full end-to-end multi-role disaster demonstration script.
  * Final audit against SIH26069 requirements and executive video showcase recording.

---

## 7. Concrete Deliverables & Verification Checklist

When this October plan is completed, INDRA will be validated against these strict criteria:

- [ ] **Control Room:** Incident Commander can approve a pending flood event, dispatch an NDRF unit, and view the action logged in the tamper-evident SHA-256 audit ledger.
- [ ] **NDRF Field App:** A rescuer in the field can load assigned tasks offline, take a photo of water levels, record depth, and have it auto-sync once cell signal returns.
- [ ] **Analyst Studio:** A data scientist can inspect the 7 verification factors, download raw CSV/GeoJSON exports, and correlate rainfall station curves with citizen reports.
- [ ] **Citizen Experience:** A citizen in Assam or Kerala can file a flood report in their local language without signing in, receive a tracking docket, and see nearby red alert zones.
- [ ] **Privacy & Governance:** Zero citizen phone numbers, names, or micro-GPS coordinates are exposed on public endpoints, fully satisfying India's DPDP Act 2023.
- [ ] **System Scale:** Multi-worker deployment running across Redis Pub/Sub passes a 5,000-message burst test without dropping WebSocket connections.

---

*Authored by Team Sixth Sense • October 2026 Strategic Roadmap • INDRA Platform*
