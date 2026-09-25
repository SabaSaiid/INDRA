# 🛰️ Comprehensive Technical Audit: NDMA SACHET vs. INDRA Platform

**Document Date:** 25 September 2026  
**Author / Team:** Saba Saeed • Team Sixth Sense  
**Project:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Target Benchmark:** NDMA SACHET (*National Disaster Alert Portal* — [sachet.ndma.gov.in](https://sachet.ndma.gov.in/))  
**Git Branch:** `saba-24sep`  
**Problem Statement ID:** `SIH26069` (Ministry of Earth Sciences / MoES)  

---

## Executive Summary

This document presents a technical audit of India's official disaster warning portal, **SACHET** (developed by **C-DOT** for the **National Disaster Management Authority - NDMA**), and provides a side-by-side comparative analysis against **INDRA**.

### The Core Architectural Divergence
* **SACHET is a Top-Down Broadcast Megaphone (Agencies $\rightarrow$ Public):**  
  It collects official bulletins from authorized government bodies (IMD, CWC, INCOIS, SDMAs) and pushes them to citizens via Cell Broadcast SMS (`XX-NDMAEW`), mobile applications, and web dashboards.  
  *Critical Blind Spot:* SACHET operates on an open-loop model. It has **no crowdsourcing feedback**, **no ground verification**, **no deduplication**, and **no way to confirm whether a warned disaster actually materialized on the ground.**
* **INDRA is a Bidirectional Disaster Intelligence & Verification Engine:**  
  INDRA closes the loop. It ingests SACHET's official government warnings as a top-down baseline, cross-references them with bottom-up citizen field reports and live physical weather stations (Open-Meteo), deduplicates noise using semantic AI (MiniLM), verifies truth via an explainable 100-point **Verification Receipt**, and logs every command in a tamper-evident **SHA-256 cryptographic hash chain**.

```
                      SACHET (Top-Down Broadcast Only)
   [Government Agencies] ──────────► [SACHET Portal] ──────────► [Citizens via SMS/Web]
   (IMD / CWC / SDMA)                 (Broadcaster)               (Passive Receivers)
   ⚠️ Blind spot: Cannot tell if the disaster actually happened on the ground.

                     INDRA (Bidirectional Intelligence Loop)
   [Official SACHET Alerts] ┐
   [Live Rainfall Stations] ┼──► [INDRA Fusion Engine] ──► [Verified Event + Receipt]
   [Citizen Field Reports]  ┘    • MiniLM Deduplication    • SHA-256 Audit Trail
                                 • DBSCAN + Uber H3         • Commander Dispatch Action
   ✨ Superpower: Fuses top-down government alerts with bottom-up ground reality.
```

---

## 🔍 Part 1: Deep-Dive Technical Audit of SACHET

### 1. System Architecture & Governing Standards
* **Operator:** National Disaster Management Authority (NDMA), Government of India (chaired by the Prime Minister).
* **Engineering & Technology Provider:** Centre for Development of Telematics (**C-DOT**).
* **Protocol Standard:** ITU-T Recommendation X.1303 / OASIS **Common Alerting Protocol (CAP v1.2)**.
* **Frontend Tech Stack:** Next.js (React), Material UI (MUI with Emotion CSS), Google Maps JavaScript API.
* **Telecom Core:** Direct SS7 / Diameter integration with Indian Telecom Service Providers (Jio, Airtel, Vi, BSNL) for location-based **Cell Broadcast Service (CBS)**.

---

### 2. Upstream Alert Providers & Data Ingestion
SACHET aggregates warning bulletins from primary national alert-generating agencies and all 36 States/UTs:
1. **India Meteorological Department (IMD):** Cyclones, Heavy Rainfall, Thunderstorms, Heatwaves, Cold Waves, Fog, Squall.
2. **Central Water Commission (CWC):** River basin water levels, in-flow warnings, flash flood alerts.
3. **Indian National Centre for Ocean Information Services (INCOIS):** Tsunami, High Sea Waves, Storm Surges.
4. **Forest Survey of India (FSI):** Forest Fire alerts.
5. **Defence Geoinformatics Research Establishment (DGRE / DRDO):** Avalanches and Snow/Landslides.
6. **36 State & UT Disaster Management Authorities (SDMAs/DDMAs):** Local administrative emergency warnings.

---

### 3. Public Web Endpoints & Interface Surface
Through live inspection, SACHET exposes the following primary routes:

| Route / Resource | Description | Technical Format |
| :--- | :--- | :--- |
| `https://sachet.ndma.gov.in/` | Public homepage with alert ticker, live weather search, and statistics. | Next.js Static / SSR |
| `https://sachet.ndma.gov.in/Dashboard` | Interactive GIS map displaying current color-coded alerts across India. | Google Maps JS API |
| `https://sachet.ndma.gov.in/CapFeed` | Public machine-readable CAP feed index with agency integration guides. | HTML + PDF link |
| `.../cap_public_website/rss/rss_india.xml` | Pan-India RSS 2.0 index listing all active warnings with unique GUIDs. | RSS 2.0 XML |
| `.../FetchXMLFile?identifier={guid}` | Full OASIS CAP v1.2 detailed document (parameters, urgency, severity). | CAP XML |
| `.../FetchPolygonXMLFile?identifier={guid}` | Geographic boundaries of warning areas (district or custom polygon). | Geo-Polygon XML |
| `https://sachet.ndma.gov.in/DosDont` | Public survival guidelines covering 18 distinct natural and man-made hazards. | HTML + YouTube Video embeds |
| `https://sachet.ndma.gov.in/ScreenReader` | Accessible interface for screen-reader software used by visually-impaired. | WCAG-compliant HTML |

---

### 4. Alert Dissemination Channels
SACHET broadcasts through 4 distinct media:
1. **Cell Broadcast / Geo-Targeted SMS:** Broadcasts via telecom towers to all mobile handsets located within the warning zone under sender ID **`XX-NDMAEW`** (no internet or app required).
2. **Native Mobile Applications:** Android (Google Play) and iOS (Apple App Store) apps with location tracking and custom watchlists.
3. **Web Browser Push Notifications:** Desktop/laptop push alerts for Google Chrome, Mozilla Firefox, and Microsoft Edge.
4. **Machine-Readable RSS Distribution:** Public RSS feed for media houses, news tickers, and external platforms (which INDRA actively consumes).

---

### 5. Educational & Multilingual Layer
* **18 Hazard Categories in "Do's and Don'ts":** Cyclones, Tsunamis, Avalanches, Cold Waves, Heat Waves, Lightning, Floods, Earthquakes, Urban Floods, Landslides, Fires, Droughts, Forest Fires, Thunderstorms/Squalls, Smog/Air Pollution, Nuclear/Radiological, Biological, and Chemical Emergencies.
* **12 Indian Regional Languages:** English, हिन्दी (Hindi), বাংলা (Bengali), ગુજરાતી (Gujarati), ಕನ್ನಡ (Kannada), മലയാളം (Malayalam), मराठी (Marathi), ଓଡିଆ (Odia), ਪੰਜਾਬੀ (Punjabi), தமிழ் (Tamil), తెలుగు (Telugu), অসমীয়া (Assamese).
* **Audio Accessibility:** Built-in text-to-speech audio reader on survival guides.

---

### 6. Architectural & Operational Limitations of SACHET
1. **Zero Crowdsourcing or Ground Truth:** Citizens are strictly passive receivers. If an alert states *"Heavy flooding in Balasore"*, SACHET cannot tell if water actually rose or if streets remained dry.
2. **No Multimodal Deduplication:** If IMD and a State SDMA both issue alerts for the same rain event, SACHET publishes both separately. It cannot deduplicate overlapping warnings.
3. **No Sensor Cross-Correlation:** Alerts are broadcast based on predictive models without validating against live physical weather stations or rain gauges.
4. **Coarse Geospatial Precision:** Visualizes broad district boundaries or simple bounding circles rather than tight, dynamic storm contours.
5. **No Incident Command or Dispatch:** SACHET stops at notification. It provides no tools to dispatch disaster response teams (NDRF/SDRF), track field units, or log commander decisions.
6. **No Cryptographic Audit Trail:** Changes to alert statuses are not immutably logged in a public tamper-evident ledger.

---

## ⚖️ Part 2: Comprehensive Comparison: SACHET vs. INDRA

| Feature / Domain | SACHET (NDMA / C-DOT) | INDRA (Sixth Sense) | Detailed Evaluation |
| :--- | :---: | :---: | :--- |
| **Primary System Goal** | Disaster Warning Broadcast | Disaster Intelligence & Ground Truth Verification | **Different Paradigms:** SACHET is a megaphone; INDRA is an intelligence brain. |
| **Data Directionality** | 1-Way (Top-down only) | 2-Way (Bidirectional closed loop) | 🏆 **INDRA:** Receives citizen ground data + sensor telemetry. |
| **Citizen Field Reports** | ❌ None | ✅ Live PWA Endpoint (`/api/reports/submit`) | 🏆 **INDRA:** Citizens upload reports with GPS, water depth, and photos. |
| **Official Authenticated Reports**| ❌ Agency login only | ✅ Role-gated route (`/api/reports/official`) | 🏆 **INDRA:** Field commanders file attributed reports. |
| **Deduplication Engine** | ❌ None (Redundant rows) | ✅ Sentence-Transformers (`all-MiniLM-L6-v2`) | 🏆 **INDRA:** Semantically collapses duplicates (cosine $\ge 0.88$, $\le 1\text{ km}$). |
| **Ground Truth Verification** | ❌ None (Forecast assumed true) | ✅ 100-Point Deterministic Verification Receipt | 🏆 **INDRA:** Cross-validates claims against live Open-Meteo physical rain. |
| **Factor Coverage Transparency**| ❌ Opaque | ✅ Explicit `factor_coverage` (0.80 published) | 🏆 **INDRA:** Never fakes missing sensors; openly states offline factors. |
| **Mapping & GIS Visualization** | 🟡 2D Google Maps (Flat polygons) | ✅ 3D MapLibre Tactical Globe + PostGIS + H3 | 🏆 **INDRA:** 3D globe with 250 m-buffered concave hulls and H3 hex heatmaps. |
| **Auditability & Integrity** | ❌ Standard Database Tables | ✅ Append-only SHA-256 Hash Chain + DB Triggers| 🏆 **INDRA:** Cryptographically verifiable decision chain. |
| **Incident Command & Dispatch** | ❌ None | ✅ Team creation, incident review, dispatch | 🏆 **INDRA:** Allocates response teams to verified emergencies. |
| **National Telecom SMS Broadcast**| ✅ Full Scale (Direct TSPs `XX-NDMAEW`) | ❌ None (Intentionally avoided) | 🏆 **SACHET:** Direct cell-broadcast telecom integration. |
| **Multilingual UI (12 Languages)**| ✅ 12 Regional Indian Languages | 🟡 English only (Regex extracts Hindi terms) | 🏆 **SACHET:** Reaches non-English speaking citizens. |
| **Accessibility & Screen Reader** | ✅ Dedicated WCAG Screen Reader + Audio TTS| 🟡 Basic web accessibility | 🏆 **SACHET:** Built-in accessibility for differently-abled. |
| **Citizen "Do's & Don'ts" Guides**| ✅ 18 Hazard survival guides + Videos | ❌ None (Focuses on tactical response) | 🏆 **SACHET:** Comprehensive public preparedness education. |
| **Native Mobile Applications** | ✅ Android & iOS apps on App Stores | 🟡 Responsive Next.js Web PWA | 🏆 **SACHET:** Native mobile ecosystem. |

---

## 🏆 Part 3: What INDRA Has That SACHET Lacks (Our Core Superpowers)

1. **The Ground Truth Verification Receipt:**  
   When SACHET issues an alert, it cannot confirm ground reality. INDRA generates an explainable mathematical receipt:
   $$\text{Confidence} = \frac{\sum_{\text{online}} (\text{Weight} \times \text{Score})}{\sum_{\text{online}} \text{Weight}}$$
   Cross-referencing citizen claims against actual physical millimeter rainfall recorded at nearby weather stations.

2. **Semantic Deduplication (MiniLM NLP):**  
   During a crisis, thousands of citizens post identical tweets or reports. SACHET would treat them as separate alerts. INDRA embeds text using `all-MiniLM-L6-v2` and collapses them into **one unified incident**, preventing alert fatigue.

3. **High-Precision Geospatial Intelligence:**  
   While SACHET draws wide district-level administrative shapes, INDRA uses PostGIS to compute a tight, **250-meter buffered concave hull polygon** around actual report coordinates, mapped onto an Uber H3 hexagonal discrete global grid.

4. **Tamper-Evident Governance (SHA-256 Ledger):**  
   Every automated pipeline decision (`AUTO_VERIFY`, `QUARANTINE`) and every commander intervention (`HUMAN_APPROVE`, `MANUAL_OVERRIDE`) is permanently chained cryptographically in `audit_logs` with PostgreSQL triggers preventing deletion or modification.

5. **Operational Incident Command:**  
   INDRA provides an active Command Center where emergency response teams are assembled, tracked, and dispatched to verified disaster zones.

---

## ⚠️ Part 4: What We Lack as of Now (Gap Analysis)

To make INDRA an all-encompassing national disaster platform, we currently have six specific gaps compared to SACHET:

1. **Gap 1: Public Survival Education ("Do's and Don'ts"):**  
   INDRA has no citizen-facing guidelines on how to survive a flash flood, cyclone, or lightning strike.
2. **Gap 2: Multilingual Support:**  
   INDRA's dashboard and PWA are currently in English only. SACHET serves 12 Indian regional languages.
3. **Gap 3: Audio & Screen-Reader Accessibility:**  
   INDRA lacks built-in text-to-speech audio read-outs for emergency instructions.
4. **Gap 4: Specialized Hazard Feeds (INCOIS, FSI, DGRE):**  
   INDRA's [`sachet_poller.py`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/workers/sachet_poller.py) ingests meteorological and flood alerts (IMD & CWC), but filters out or ignores INCOIS (tsunami/ocean swell), FSI (forest fires), and DGRE (avalanches).
5. **Gap 5: Outbound Citizen Alert Dissemination:**  
   INDRA does not broadcast outbound notifications (browser web-push, Telegram responder bots, or SMS).
6. **Gap 6: Citizen Multi-Location Watchlist:**  
   INDRA has no user preference system allowing citizens to bookmark multiple geographic regions for remote alert tracking.

---

## 🛠️ Part 5: Actionable Implementation Plan: Getting What We Lack Done

Here is the exact step-by-step engineering plan to implement the missing capabilities into INDRA:

```
                      INDRA UPGRADE ROADMAP (BRIDGING GAPS)
┌────────────────────────────────────────┐    ┌────────────────────────────────────────┐
│     SPRINT 1: QUICK WINS (24-48h)      │    │     SPRINT 2: ENTERPRISE EXPANSION     │
├────────────────────────────────────────┤    ├────────────────────────────────────────┤
│ 1. "Do's & Don'ts" Modal + Audio TTS   │    │ 5. Full 12-Language i18n Translation   │
│ 2. Bilingual Support (Hindi + English) │    │ 6. Telegram / SMS Webhook Dispatcher   │
│ 3. INCOIS & FSI Feed Parsing Support   │    │ 7. Web Push Browser Notifications      │
│ 4. Citizen Multi-Location Watchlist    │    │ 8. Offline-First Flutter Mobile App    │
└────────────────────────────────────────┘    └────────────────────────────────────────┘
```

---

### Step 1: Implement Citizen "Do's & Don'ts" Guide with Audio TTS
* **Goal:** Provide actionable survival steps for all 18 disaster types with audio read-out accessibility.
* **Implementation:**
  * Create `frontend/src/app/dos-donts/page.tsx` and a reusable component `DosDontModal.tsx`.
  * Store structured JSON survival checklists for Floods, Cyclones, Heatwaves, and Thunderstorms in `frontend/src/lib/disaster-guidelines.json`.
  * Implement Web Speech API (`window.speechSynthesis`) so users can click **"Listen to Instructions"** for audio playback.

---

### Step 2: Implement Bilingual Support (Hindi & English)
* **Goal:** Enable citizens and field operators to toggle between English and हिन्दी.
* **Implementation:**
  * Add a lightweight translation provider in `frontend/src/lib/i18n.ts` storing key-value dictionaries for UI components, hazard names, and alert statuses.
  * Add a language toggle (`EN | HI`) in [`frontend/src/components/Topbar.tsx`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/Topbar.tsx).

---

### Step 3: Expand SACHET Poller to Ingest INCOIS & FSI Alerts
* **Goal:** Broaden ingestion beyond IMD and CWC to include marine tsunamis and forest fires.
* **Implementation:**
  * In [`backend/app/services/cap_parser.py`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/backend/app/services/cap_parser.py), add categories:
    * `INCOIS` $\rightarrow$ Hazard: `TSUNAMI` / `STORM_SURGE`
    * `FSI` $\rightarrow$ Hazard: `FOREST_FIRE`
    * `DGRE` $\rightarrow$ Hazard: `AVALANCHE`
  * Map these hazards to specific icons on the [`GlobeEventMap.tsx`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/client-only/GlobeEventMap.tsx).

---

### Step 4: Implement Outbound Alert Dispatch (Telegram & Web Push)
* **Goal:** Close the operational loop by notifying responders when an event is `HUMAN_APPROVED`.
* **Implementation:**
  * **Telegram Responder Dispatcher:** In `backend/app/services/alert_dispatcher.py`, send an automated alert payload (coordinates, map pin link, depth, severity) to an NDRF Telegram bot channel when a commander approves an incident.
  * **Browser Web Push:** Integrate standard browser `Notification.requestPermission()` in the dashboard to ping operators when a critical event forms.

---

### Step 5: Multi-Location Citizen Watchlist
* **Goal:** Allow users to save multiple districts to monitor.
* **Implementation:**
  * In `frontend/src/app/profile/page.tsx`, add a **"Monitored Districts"** multi-select field backed by `localStorage` or `user_profiles`.
  * Filter live notifications in [`NotificationPopover.tsx`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/NotificationPopover.tsx) to highlight monitored areas.

---

## 🎯 Part 6: How to Pitch This to SIH Evaluators & Judges

When presenting to evaluators from the Ministry of Earth Sciences (MoES):

> **"We did not reinvent SACHET; we built the missing intelligence brain for it."**
>
> 1. **Top-Down Meets Bottom-Up:**  
>    *SACHET is a one-way megaphone broadcasting warnings to citizens. INDRA turns this into a two-way conversation by empowering citizens to submit real-time ground truth reports and photos from the field.*
>
> 2. **Verification Over Blind Trust:**  
>    *Instead of assuming every warning is accurate or guessing if a disaster happened, INDRA calculates an explainable Verification Receipt checking ground claims against physical weather stations.*
>
> 3. **AI Deduplication:**  
>    *While national portals suffer from redundant duplicate alerts, INDRA’s Sentence-Transformers engine merges duplicates, protecting commanders from alert fatigue.*
>
> 4. **From Public Alerting to Tactical Action:**  
>    *SACHET stops at sending an SMS. INDRA equips disaster commanders with a 3D tactical map, a tamper-evident audit ledger, and a direct rescue team dispatch engine.*

---

*Report prepared for SIH 2026 Evaluation • Team Sixth Sense • Branch `saba-24sep`*
