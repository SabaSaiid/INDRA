# INDRA Architecture Specification & Engineering Blueprint

**Project Title**: INDRA (Intelligent National Disaster & Weather Platform)  
**Problem Statement ID**: SIH26069 (National Weather Big Data Analytics Platform)  
**Theme**: Disaster Management | **Category**: Software  
**Team**: Sixth Sense — Smart India Hackathon 2026  

> **How to read this document.** This is the **target architecture** — the system INDRA is
> designed to be. Sections 1–8 describe that design and do not change as implementation
> progresses. **Section 0 below is the honest ledger of what is actually built**, and it is
> the section to trust when asking "does this run today?". Keep them separate: the design is
> the pitch, the ledger is the truth, and conflating the two is how a demo falls apart under
> a judge's follow-up question.
>
> Ledger last verified against code: **16 Sep 2026** (end of backend sprint **Day 3**; Days 2
> and 3 were finished ahead of their 17/18 Sep slots).
>
> **Branch caveat:** Day 1 is on `main`. Day 2 (PR #14, `aditya_17sep`) and Day 3 (PR #15,
> `aditya_18sep`, stacked on Day 2) are **open, not yet merged**. Until they merge, anything
> below marked *Day 2* or *Day 3* is true of `aditya_18sep`, not of `main`.

---

## 0. Implementation Status Ledger

Legend: ✅ built and exercised · 🟡 partial — real but incomplete · ⬜ designed, not built

This ledger is organised by the **canonical 9-layer stack** from the team's official
SIH26069 system-architecture diagram. Every other diagram in this repo — including §3's
four-tier engineering view — is a projection of this stack; where they disagree, **this is
the reference.**

Legend: ✅ built · 🟡 partial · ⬜ designed, not built

```mermaid
flowchart TD
    SRC["<b>1. DATA SOURCES</b><br/>⬜ IMD / Govt APIs<br/>🟡 Weather APIs<br/>🟡 Public datasets<br/>⬜ Social media<br/>✅ Citizen reports<br/>🟡 Images / Videos"]

    ING["<b>2. DATA INGESTION</b><br/>✅ REST API / Webhooks<br/>✅ Kafka / Redpanda<br/>🟡 Batch ingestion<br/>✅ Stream ingestion"]

    PROC["<b>3. DATA PROCESSING LAYER</b><br/>⬜ Cleaning<br/>✅ Normalization<br/>✅ Deduplication<br/>⬜ Timestamp processing<br/>🟡 Geocoding<br/>⬜ Metadata extraction"]

    AI["<b>4. AI / ML LAYER</b><br/>🟡 NLP classifier<br/>⬜ Event detection<br/>⬜ Fake detection<br/>✅ Duplicate matching<br/>⬜ Image analysis<br/>⬜ Anomaly detection"]

    GEO["<b>5. GEO-ANALYTICS</b><br/>✅ Location mapping<br/>✅ Spatial clustering<br/>🟡 Heatmaps<br/>🟡 Event boundaries<br/>⬜ Risk zones<br/>🟡 Time-space trends"]

    FUS["<b>6. EVENT FUSION ENGINE</b><br/>✅ Correlate observations<br/>✅ Merge duplicate reports<br/>✅ Calculate confidence<br/>🟡 Determine severity<br/>✅ Build weather event"]

    PLAT["<b>7. DATA PLATFORM</b><br/>✅ PostgreSQL + PostGIS<br/>🟡 Redis<br/>⬜ Object Storage S3/MinIO<br/>🟡 Historical datasets"]

    API["<b>8a. REAL-TIME API</b><br/>✅ FastAPI<br/>✅ WebSocket<br/>✅ REST APIs<br/>✅ Human review + RBAC"]

    ALERT["<b>8b. ALERT ENGINE</b><br/>⬜ Critical events<br/>⬜ SMS / Email<br/>⬜ Dashboard alerts"]

    CC["<b>9. IMD COMMAND CENTER</b><br/>✅ India Weather Map<br/>✅ Real-time Analytics<br/>✅ Weather Events<br/>⬜ Risk Zones<br/>✅ Verification Status<br/>🟡 Historical Trends<br/>⬜ Critical Alerts<br/>🟡 Report Investigation"]

    SRC --> ING --> PROC
    PROC --> AI
    PROC --> GEO
    AI --> FUS
    GEO --> FUS
    FUS --> PLAT
    PLAT --> API
    PLAT --> ALERT
    API --> CC
    ALERT --> CC

    classDef built fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef partial fill:#fff8e1,stroke:#f9a825,stroke-width:2px;
    classDef absent fill:#fbe9e7,stroke:#c62828,stroke-dasharray: 5 5,stroke-width:2px;

    class ING,GEO,FUS,API built;
    class SRC,PROC,PLAT,CC partial;
    class AI,ALERT absent;
```

### Layer-by-layer ledger

| # | Layer | Status | What is actually true |
|---|---|---|---|
| 1 | Data Sources | 🟡 **2 of 6** | Citizen reports have a live writer (`POST /api/reports/submit`). **Day 2:** Open-Meteo rainfall is the first external feed actually read (`services/weather.py`, `httpx`, 3 s timeout, cached per H3 res-8 cell). It is pulled *per event* for the weather factor, not polled on a schedule, so `station_readings` is still empty. `TWITTER_IMD`, `AWS_SENSOR`, `CWC_GAUGE`, `OFFICIAL_DISPATCH` are declared `SourceType` values with no producer; the OpenWeather, IMD and Twitter keys are unread. `raw_reports.media_url` stores a string; no image is uploaded or opened. |
| 2 | Data Ingestion | 🟡 **stream real, batch synthetic** | REST → Postgres **and** Redpanda (`indra.raw.reports`); `workers/report_consumer.py` consumes it. **Batch ingestion is not real (corrected Day 4):** the ✅ previously rested on `scripts/seed_national_data.py`, which invents events, receipts and reports. Since Day 4 it refuses to run without `--synthetic`, marks every receipt `synthetic: true`, and no longer writes `station_readings` or unchained audit rows. **Day 2:** the Kafka message now carries exactly the stored row (sanitised coordinates, `raw_text`, `h3_res8`, `credibility_score`). **Day 4:** a report that cannot be stored returns 503 and is never published (a stored report whose publish fails returns 202 `queued: false`); a re-delivered message is not re-broadcast as `NEW_REPORT`. |
| 3 | Data Processing | 🟡 **3 of 6** | Deduplication is real and wired (`services/dedup.py`: MiniLM cosine ≥ 0.88 **AND** ≤ 1 km **AND** ≤ 15 min, Levenshtein ≥ 0.75 fallback). **Day 4:** a suppressed report is recorded as `duplicate_of` its original (migration `0004`) and excluded from clustering, so it is never counted as corroboration. **Day 2:** out-of-India coordinates are **rejected with 422 and never stored** (previously snapped to `(22, 82)` or to a city named in the text); a swapped lat/lng is still corrected. Each report gets a computed `credibility_score` (`services/credibility.py`: source prior × text quality) instead of a flat 0.5. Geocoding is a 56-city static gazetteer, and the bounds check is a bounding box, not the border. Cleaning, timestamp processing and metadata extraction do not exist. |
| 4 | AI / ML | 🟡 **1 of 6** | `all-MiniLM-L6-v2` runs for duplicate matching. **Day 4:** An event-type text classifier (MiniLM + logistic regression) is **trained and measured on a synthetic labelled set but below its acceptance gate, so it is offline and not wired** (test macro-F1 0.787; NOT_RELEVANT recall 0.667 and 5/72 floods dismissed fail the gate; `backend/app/ml/artifacts/event_classifier_v1.metrics.json`). The labelled set is `data/labelled/reports_v1.csv` (300 synthetic rows, frozen split, `DATASHEET.md`). So nothing yet derives event type or severity from report content. No vision model, no fake detection, no anomaly detection. **Day 2:** vision and anomaly are now *explicitly* `"offline"` in every receipt rather than filled with random numbers — a deliberate choice, and the reason confidence is capped at 0.80. |
| 5 | Geo-Analytics | ✅ **mostly** | `ST_ClusterDBSCAN` clustering is real, persists membership, and yields centroid / radius / max-pairwise stats in `geography` metres. H3 res-8 cells are computed and stored but nothing reads them yet, so heatmaps are storage-ready, not built. Events carry `center_point` and `impact_radius_km`; `boundary_polygon` exists in the schema but is never populated. Risk zones do not exist. |
| 6 | Event Fusion | ✅ **the spine** | `services/pipeline.py` correlates, merges duplicates, merges *streaming-arrival fragments* into one event, scores, and persists. **Day 2: no randomness left** — 4 factors are measured (weather, report density, spatial coherence, source reliability), 2 are explicitly offline, and a determinism test proves the same cluster gives a byte-identical receipt. **Day 3:** a human decision (approve / reject / severity override) is never overwritten by a later merge; each pipeline write (report links + event + audit row) is one transaction. Severity stays 🟡: it is derived from corroboration count, and the receipt says so (`heuristic_from_cluster_size`). |
| 7 | Data Platform | 🟡 **2 of 4** | PostGIS is fully real (3 migrations, GIST indexes, enums, audit-immutability trigger). **Day 3:** `audit_logs` is a real append-only **SHA-256 hash chain** (`services/audit.py`, migration `0003`), written by the pipeline and the review endpoint, appended under an advisory lock so concurrent writers cannot fork it. **Redis runs but no backend code connects to it** — WebSocket fan-out is an in-process list, so the app cannot run multi-worker. Object storage is configured in `.env` but absent from `docker-compose.yml`. |
| 8a | Real-Time API | ✅ **complete** | FastAPI, 7 routers, REST + `/ws/events` carrying `NEW_REPORT`, `VERIFIED_EVENT`, `EVENT_REVIEWED` (Day 3), `DEMO_PULSE`. **Day 2:** `DEMO_MODE` gates every demo fallback (`[]` / 404 / 503 when off). **Day 3:** `PATCH /api/events/{id}/review` (COMMANDER/ADMIN) and `GET /api/events/{id}/provenance` (ANALYST/COMMANDER/ADMIN) are **auth-enforced**. Caveat: *only those two* are gated — every endpoint the dashboard already calls is still open, because the frontend holds no token yet. **Day 4:** `/healthz` checks Postgres, Kafka, Redis and Open-Meteo concurrently (2 s cap each): 503 `unhealthy` if Postgres or Kafka is down, 200 `degraded` if Redis or Open-Meteo is. |
| 8b | Alert Engine | ⬜ **absent** | Not implemented in any form: no notification code, no SMS/email provider, no critical-event trigger. Not scheduled in this sprint. |
| 9 | Command Center | 🟡 | The Next.js dashboard is built (frontend team). Backend-side, verification status and events are served from real data; review and provenance endpoints now exist but the dashboard does not call them yet (handover written). Risk zones and critical alerts have no backend behind them. Every frontend fetch falls back to mock data, so **the UI looking complete says nothing about backend state**. |

### Where the real path runs

```
Citizen report ──► REST ──► Redpanda ──► consumer ──► dedup ──► DBSCAN cluster
                                                                      │
                          Open-Meteo rainfall ──► 6-factor receipt ◄──┘
                                                        │
   WebSocket ◄── verified_events row + audit row (one transaction)
       │
       └── commander: PATCH /review ──► HUMAN_APPROVED + audit row ──► EVENT_REVIEWED
```

Everything on that line is live and test-covered (**326 passed, 2 skipped**, against a separate `indra_test` database).
Everything off it — NLP classification, vision, anomaly detection, alerting, object storage,
scheduled external polling — is not.

### Audit, auth and review — three claims to keep straight

| Claim made elsewhere in this doc | Reality (Day 3) |
|---|---|
| "Unalterable SHA-256 audit trail" | ✅ **Real.** Every pipeline decision (`AUTO_VERIFY` / `ESCALATE` / `QUARANTINE`) and every human review (`HUMAN_APPROVE` / `HUMAN_REJECT` / `MANUAL_OVERRIDE`) writes one chained row; the DB trigger rejects `UPDATE`/`DELETE`; tampering with, deleting or reordering a row is detected at that row. **Honest limit:** rows cut off the *end* of the chain, or a `TRUNCATE`, still leave a valid chain — that needs an external anchor for the head hash, which is not built. |
| "Human-in-the-loop review queue" | ✅ **Real.** `PATCH /api/events/{id}/review` approves or rejects from `QUARANTINED` or `PENDING_HUMAN_REVIEW`, or overrides severity; illegal transitions → 409, concurrent approvals → one 200 and one 409. `GET /api/events/{id}/provenance` returns the contributing reports, the audit rows and a chain check. |
| "RBAC / role-gated access" | 🟡 **Enforced on the two new endpoints only** (pinned by a 7-token × 3-endpoint test matrix). Endpoints the dashboard already calls stay open until the frontend has a login flow. |

### Fixed defect (found Day 3, fixed Day 4)

A report suppressed as a duplicate used to stay in `raw_reports` with `event_id NULL`, so the
next genuine report clustered with it and it was merged into the event (6 distinct reports
showed as **7**). It is now marked `duplicate_of` its original and never clustered; the live
re-run gives `report_count 6`, and the former strict `xfail` passes.

### The one-line summary

The **spine is real and now honest**: a citizen report travels REST → Kafka → dedup → DBSCAN
cluster → deterministic scoring (4 measured factors incl. live Open-Meteo rainfall, 2
explicitly offline) → a persisted event with a hash-chained audit row → WebSocket, and a
commander can approve it through an auth-gated endpoint without the next report undoing the
decision. What is **not** real is most of the *perception* (no NLP classification, no
vision, no anomaly detection; a text classifier is measured but below its gate), scheduled *external ingestion*, and the entire *alerting*
tier. Because two factors are offline, **confidence tops out at 0.80**: nothing
auto-publishes, and the live demo cluster lands at ~0.43 → `QUARANTINED` until a human
approves it.

---

## 1. Core Engineering Philosophy

> **"We are building an intelligence platform, not a weather app."**

Traditional weather apps simply answer: *"What is the weather in Patna?"* (1 API request $\rightarrow$ 1 UI update).  
**INDRA** answers the critical emergency question: **"What weather events are unfolding, how severe are they, how reliable is the data, and what is the underlying verifiable evidence?"**

| Dimension | Standard Weather App | INDRA Intelligence Platform |
| :--- | :--- | :--- |
| **System Paradigm** | Basic CRUD / Proxy to third-party API | Event-Fusion Engine & Emergency Command Center |
| **Data Ingestion** | Synchronous pull on user page load | Asynchronous multi-stream push via Kafka/Redpanda |
| **Data Integrity** | Unvetted, blind trust in external feed | AI Verification, cross-source corroboration, anomaly detection |
| **Output Entity** | Simple weather forecast card (temp, rain %) | Fused **Verified Weather Event** with unalterable evidence trail |
| **Target User** | Individual citizen checking today's rain | NDRF, SDMAs, District Emergency Operations Centers (EOCs) |

---

## 2. Decoupling Confidence from Severity: The 2×2 Matrix

Disaster response requires separating **how dangerous an event is** (Severity) from **how certain we are that it is happening** (Confidence).

```
                      SEVERITY (Low ───────► Critical)
          ▲
          │   ┌─────────────────────────────┬─────────────────────────────┐
          │   │      UNVERIFIED THREAT      │   CRITICAL VERIFIED EVENT   │
          │   │                             │                             │
          │   │  Single report of dam break │  Patna flood (100+ reports) │
H         │   │  ACTION: Immediate Admin    │  ACTION: Immediate Public   │
I  C      │   │          Review Flag        │          & NDRF Alert       │
G  O      │   ├─────────────────────────────┼─────────────────────────────┤
H  N      │   │            NOISE            │    CONFIRMED MINOR EVENT    │
   F      │   │                             │                             │
│  I      │   │  Isolated rumor or tweet    │  Verified localized puddle  │
│  D      │   │  ACTION: Filter & Ignore    │  ACTION: Monitor; no alert  │
▼  E      │   │                             │          dispatch           │
   N      │   └─────────────────────────────┴─────────────────────────────┘
   C
   E
```

- **Critical Verified Event (High Severity, High Confidence)**: Multi-source consensus confirmed. Auto-publishes and triggers instant sirens, SMS broadcast, and NDRF dispatch.
- **Unverified Threat (High Severity, Low Confidence)**: A catastrophic claim (e.g. dam breach or landslide) with only 1 or 2 uncorroborated reports. **Never ignored, never auto-published**—flagged with highest priority in the human review queue.
- **Confirmed Minor Event (Low Severity, High Confidence)**: Confirmed minor waterlogging; logged for urban municipal tracking without inducing public panic.
- **Noise (Low Severity, Low Confidence)**: Filtered out before reaching operators.

---

## 3. The Complete Tiered System Architecture

Solid borders mark what is **built** today; dashed borders mark what is **designed but not
implemented** (see §0 for the detail behind each).

```mermaid
flowchart TD
    subgraph TIER1["TIER 1: DATA SOURCES (INPUTS)"]
        SRC1[Open-Meteo Primary API]
        SRC2[OpenWeather Secondary API]
        SRC3[Citizen Mobile PWA: GPS + Camera]
        SRC4[Public Sensor Datasets: CWC / IMD AWS]
    end

    subgraph TIER2["TIER 2: INGESTION & PROCESSING"]
        K1[Kafka / Redpanda Event Highway]
        V1[Coordinate Validation & Normalization]
        V2[Geocoding: Country / State / City]
        V3[Deduplication: Text + GPS + Time]
    end

    subgraph TIER3["TIER 3: THE BRAIN (ENGINES)"]
        AI1[Sentence Transformers: dedup embeddings]
        AI2[PyTorch / OpenCV Vision Pipeline]
        AI3[Isolation Forest Anomaly Detector]
        GEO1[PostGIS ST_ClusterDBSCAN]
        GEO2[Uber H3 Hexagonal Spatial Indexing]
        FUS[Multi-Source Event Fusion Engine]
    end

    subgraph TIER4["TIER 4: PLATFORM & OUTPUT"]
        DB[(PostgreSQL + PostGIS)]
        RD[(Redis State & Pub/Sub)]
        OBJ[(MinIO / S3 Media)]
        API[FastAPI Gateway]
        ALERT[Alert Engine: SMS / Email / Dispatch]
        UI[Next.js Live WebSocket Command Center]
    end

    SRC1 & SRC2 & SRC3 & SRC4 --> K1
    K1 --> V1 --> V2 --> V3
    V3 --> AI1 & AI2 & AI3 & GEO1 & GEO2
    AI1 & AI2 & AI3 & GEO1 & GEO2 --> FUS
    FUS --> DB & RD & OBJ
    DB & RD --> API --> UI
    API --> ALERT

    classDef notBuilt stroke-dasharray: 5 5,stroke-width:1px;
    class SRC2,SRC4,AI2,AI3,OBJ,ALERT notBuilt;
```

> Open-Meteo (`SRC1`) is drawn solid since Day 2: it is fetched per event for the weather
> factor, though not yet polled as a continuous stream.

> **Diagram note:** `SRC3` and `OBJ` were both named `S3` in an earlier revision of this
> file, which silently collapsed the Citizen PWA and the object store into a single Mermaid
> node and drew an edge from the fusion engine back into the citizen app. Renamed.

---

## 4. Spatio-Temporal Clustering & Indexing

INDRA processes incoming reports through a 3-step spatial pipeline:

1. **Coordinate Validation**: Validates latitude $[-90, 90]$ and longitude $[-180, 180]$, stripping coordinate jitter and normalizing timestamps to UTC.
2. **Administrative Geocoding**: Resolves coordinates to official administrative boundaries:  
   $$\text{GPS Lat/Lng} \longrightarrow \text{Country: India} \longrightarrow \text{State: Bihar} \longrightarrow \text{District: Patna}$$
3. **Hybrid Spatial Clustering**:
   - **PostGIS `ST_ClusterDBSCAN`**: Identifies dense arbitrary spatial shapes of disaster boundaries (`eps = 5km`, `min_samples = 2`).
   - **Uber H3 (`H3_HEX`)**: Partitions the geographic area into discrete hexagonal cells (Resolution 8, edge length $\approx 460\text{m}$) for high-speed spatial hashing, heatmaps, and spatial indexing.

---

## 5. Explainable Verification: The Verification Receipt

INDRA does **not** treat confidence as a black box. For every generated incident, the system computes and prints an **unalterable Verification Receipt** with exact mathematical weights summing to $100\%$:

$$C = 0.25 \cdot S_{\text{weather}} + 0.20 \cdot S_{\text{reports}} + 0.20 \cdot S_{\text{spatio-temporal}} + 0.15 \cdot S_{\text{image}} + 0.15 \cdot S_{\text{reliability}} + 0.05 \cdot S_{\text{anomaly}}$$

```
┌────────────────────────────────────────────────────────────────────────┐
│                        THE VERIFICATION RECEIPT                        │
│                     CONFIDENCE SCORE: 94 / 100                         │
├────────────────────────────────────────────────────────────────────────┤
│  ✓ Weather Agreement (25%)          : Open-Meteo/AWS recorded 92mm     │
│  ✓ Independent Reports (20%)        : 103 verified independent reports │
│  ✓ Location & Time Consistency (20%): PostGIS & H3 cluster within 0.8km│
│  ✓ Image Evidence (15%)             : PyTorch floodwater prob: 0.91    │
│  ✓ Source Reliability (15%)         : Verified app users & AWS sensors │
│  ✓ Historical Anomaly (5%)          : 140mm vs 35mm seasonal baseline   │
└────────────────────────────────────────────────────────────────────────┘
```

> **Status (see §0, updated Day 2):** the weighted arithmetic, the quadrant assignment, and
> the review-status routing are all real and unit-tested. The receipt above is the *designed*
> output. **Today four of the six factors carry real evidence and none is random:**
> `weather_station` (live Open-Meteo 24 h rainfall mapped onto IMD rainfall categories),
> `report_density` (deduplicated report count on a curve saturating at 25),
> `spatial_coherence` (raised cosine over the DBSCAN cluster span) and `source_reliability`
> (a documented per-source lookup, max over the cluster). `vision_analysis` and
> `anomaly_detection` are **explicitly offline**. Each receipt carries a `provenance` field
> marking every factor `"computed"` or `"offline"` (severity reads
> `heuristic_from_cluster_size`, or `human_override` after a review), so the distinction
> survives into the API response. An offline factor scores `0.0` with the evidence string
> `"Telemetry factor offline"` — **stating that a signal is absent is preferred over
> inventing a number for it.** Consequence: the maximum reachable confidence is **0.80**, so
> the 94 above is illustrative; the live Patna demo cluster scores ~0.43.

### Duplicate Merging Engine
Reports are grouped and merged before fusion using the composite duplicate rule:
$$\text{Duplicate if: } [\text{Cosine Similarity} \ge 0.88] + [\Delta \text{GPS} \le 1.0\text{ km}] + [\Delta t \le 15\text{ mins}]$$

All three gates are ANDed, and all three are live in `services/dedup.py`. Two caveats worth
knowing: the cosine threshold of **0.88 is strict enough to miss paraphrases** (measured:
same-event paraphrase 0.815, genuinely distinct reports 0.519, unrelated text 0.136 — so
~0.75–0.80 is the separating band), and if the embedding model cannot load, the service
degrades to a normalized Levenshtein ratio at ≥ 0.75 rather than failing.

> **Known defect (Day 3, fix scheduled Day 4):** a suppressed duplicate is left unassigned in
> `raw_reports`, so a later genuine report can pull it into the event and count it as
> corroboration. See §0.

### Event merging across streaming arrivals

Reports arrive one at a time, so a cluster crosses `min_samples` long before the last
report about an incident has landed. Without a merge step, reports 1–2 create one event and
reports 3–5 create a rival event a few hundred metres away — the platform reproducing the
exact fragmentation it exists to remove. `pipeline.py` therefore folds a new cluster into a
recent overlapping event (within its impact radius plus one DBSCAN `eps`, inside a 2-hour
window, excluding `REJECTED` events) and re-scores it, instead of creating a competitor.

---

## 6. Human-in-the-Loop Review & Unalterable Audit Trails

To guarantee accountability, every human intervention is recorded with an immutable SHA-256 hash in PostgreSQL:

- **$\mathbf{\ge 90\%}$**: Automatically Verified & Published to Command Center.
- **$\mathbf{70\% - 90\%}$ (Probable)**: Flagged for Emergency Analyst review.
- **$\mathbf{< 70\%}$ (Suspicious)**: Retained in quarantine buffer. If severity is Critical, escalated to Emergency Review.

> These are the real figures — `AUTO_PUBLISH_THRESHOLD=0.90` and `HUMAN_REVIEW_THRESHOLD=0.70`
> in `.env`, applied by `fusion_engine.determine_review_status()`. Earlier revisions of this
> document and the README quoted a 60% lower bound, which never matched the code.

> **Status (see §0, updated Day 3):** built. Every pipeline decision and every human review
> appends one row to a single SHA-256 chain (`services/audit.py`):
> `sha256(canonical_json{prev_hash, event_id, operator_id, action, reason, details, logged_at})`,
> genesis `"0"*64`, appended under `pg_advisory_xact_lock`, with the `BEFORE UPDATE OR DELETE`
> trigger rejecting mutation. `PATCH /api/events/{id}/review` (COMMANDER/ADMIN) is the human
> half: approve or reject from `QUARANTINED` / `PENDING_HUMAN_REVIEW`, or override severity,
> with a required reason. An approved event becomes `HUMAN_APPROVED` and **stays approved when
> later reports merge into it**. `GET /api/events/{id}/provenance` returns the audit rows and a
> chain check. Because honest scores currently top out at 0.80, the ≥ 90% auto-publish tier is
> unreachable today, so **in practice every event reaches the command center via a human**.
> Limit: a truncated tail or emptied table still verifies as a valid chain (no external
> anchor for the head hash).

```
+-------------------------------------------------------------------------------+
| AUDIT LOG OUTPUT:                                                             |
| Admin A | 15:42 | Verified EVENT-28231827-A | Reason: AWS + citizen evidence |
| Hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855       |
+-------------------------------------------------------------------------------+
```

---

## 7. Deployment Strategy: Modular Monolith

Rather than introducing 15 fragile microservices during an active hackathon sprint, INDRA follows a **Modular Monolith** pattern:
- **FastAPI Monolith**: Serves Auth, Citizen PWA APIs, Weather Ingestion, Alert Queries, and WebSocket feeds.
- **AI Worker Process**: Runs NLP embeddings, OpenCV computer vision, and DBSCAN clustering.
- **Redpanda / Kafka Buffer**: Absorbs sudden mass-reporting traffic surges (e.g. 10,000 simultaneous reports) and feeds them to workers at a controlled rate without dropping packets.
- **Infrastructure**: Single `docker compose up` orchestrating PostGIS, Redis, Redpanda, and MinIO.

> **Status (see §0):** three deviations from the above, all deliberate.
>
> 1. **There is no separate AI worker process.** `workers/report_consumer.py` runs as an
>    `asyncio` task inside the FastAPI process, started from the app's lifespan hook. The
>    embedding model and the pipeline therefore share the API's event loop. This is fine at
>    demo scale and is the right call for a hackathon, but it means CPU-heavy scoring can
>    stall request handling, and it is the first thing to split out if load becomes real.
> 2. **`docker compose` brings up three services, not four** — PostGIS, Redis, Redpanda.
>    MinIO is not in the file. Adding it is an infra decision for the team, not a backend
>    one.
> 3. **Redis is started but unused.** No backend code opens a Redis connection. Because
>    WebSocket fan-out is an in-process list rather than Redis pub/sub, **the backend cannot
>    currently be run with more than one worker** without clients silently missing events.
>    Run it single-process until that changes.

---

## 8. The 10-Scene Hackathon Demonstration Sequence

1. **Scene 1 (Baseline)**: India map displays normal operational telemetry with live Open-Meteo feeds.
2. **Scene 3 (The Spike)**: `scripts/run_patna_demo.py` simulates a cloudburst surge—127 reports enter via Kafka in seconds.
3. **Scene 5 (Fusion)**: Duplicate detection collapses 127 reports into 1 major flood event; PostGIS binds coordinates to Central Patna.
4. **Scene 7 (Evidence)**: OpenCV confirms waist-deep water; Open-Meteo confirms 92mm rainfall anomaly.
5. **Scene 8 (Intelligence)**: INDRA outputs the 94% Verification Receipt and tags the event as `Critical Verified Event`.
6. **Scene 10 (Action)**: WebSocket pushes incident polygon to the Next.js dashboard; emergency broadcast alert is triggered.

### What each scene actually does today

This matters more than any other status note in this document, because it is the part a
judge watches happen. **Know which scenes are live and which are narration.**

| Scene | Today |
|---|---|
| 1 — Baseline | 🟡 The map and telemetry render, but from seeded/mock data. **No feed is polled on a schedule**; Open-Meteo is only called per event, for the weather factor. |
| 3 — The Spike | 🟡 `run_patna_demo.py` prints the narrative and replays `patna_flood_scenario.json`. The **live** surge path is `POST /api/reports/submit` → Kafka, which does work and is the one to demo. |
| 5 — Fusion | ✅ **Real.** Dedup + `ST_ClusterDBSCAN` + event merging genuinely collapse many reports into one event with one `event_code`. This is the strongest scene and the honest centre of the pitch. |
| 7 — Evidence | 🟡 **Half real.** The rainfall evidence is a live Open-Meteo fetch (modelled precipitation, not a rain gauge — the receipt says so). There is no OpenCV; the vision factor reads `"Telemetry factor offline"`. Do not claim image evidence. |
| 8 — Intelligence | 🟡 **Real receipt, honest inputs.** The 6-factor breakdown is computed and deterministic: four factors measured, two offline and labelled. The "94%" is illustrative — the live cluster scores ~0.43 and is `QUARANTINED`. |
| 8½ — Human review | ✅ **Real (Day 3).** A commander logs in, approves the quarantined event with a reason → `HUMAN_APPROVED`, `EVENT_REVIEWED` over the WebSocket, and a hash-chained audit row visible in provenance. The next corroborating report raises confidence without undoing the approval. |
| 10 — Action | 🟡 WebSocket push to the dashboard is **real** (`VERIFIED_EVENT`, `EVENT_REVIEWED`). The emergency broadcast / NDRF dispatch is **not implemented** — there is no alert engine. |

The defensible version of this demo is: *submit reports live, watch them collapse into one
event, open the receipt and point at which factors are measured and which say "Telemetry
factor offline", explain why the machine quarantined it, then approve it as a commander and
show the audit chain.* That story is entirely true, and it survives follow-up questions. The
version that claims image evidence, a 94% auto-publish, or Scene 10's dispatch does not.
