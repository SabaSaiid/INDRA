# INDRA Real-Time Event Deduplication & Fusion Architecture
**Document Reference:** INDRA-ARCH-SPEC-08  
**Classification:** Technical Specification · SIH 2026  
**Status:** Active Draft  

---

## 1. Executive Summary

During severe weather incidents and cloudburst events, citizen reports flood emergency operation centres with overlapping, noisy, and non-uniform observations. A single flash flood on a metropolitan thoroughfare may generate hundreds of localized reports across WhatsApp, Twitter, SMS, and citizen portal forms.

INDRA employs a dual-stage spatial-temporal deduplication and event clustering engine designed to:
1. Prevent duplicate notifications from inundating state disaster response operators.
2. Group nearby reports into a unified ground-truth **Verified Event**.
3. Establish a deterministic confidence score without loss of raw forensic evidence.

---

## 2. Core Deduplication Pipeline

```
Raw Citizen Reports
       │
       ▼
┌───────────────────────────────┐
│ Ingestion & Hash Checking     │  SHA-256 fingerprint on text & media
└──────────────┬────────────────┘
               │ (Deduplicated raw stream)
               ▼
┌───────────────────────────────┐
│ IndicBERT NLP Normalization   │  Extracts hazard type, severity cues, sentiment
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Spatial-Temporal Clustering   │  DBSCAN with Haversine distance (< 500m)
│ (H3 Resolution 8/9 Indexing)  │  Temporal window (t <= 45 minutes)
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Consensus Scoring Engine      │  Multi-source verification weight calculation
└──────────────┬────────────────┘
               │
               ▼
Verified Incident Cluster (Published)
```

---

## 3. Spatial-Temporal Clustering Parameters

| Parameter | Value | Description |
|---|---|---|
| `epsilon_spatial` | 500 meters | Maximum geodesic distance between incident points for cluster inclusion |
| `epsilon_temporal`| 2,700 seconds (45 min) | Time window for grouping concurrent observations |
| `min_samples` | 3 reports | Minimum cluster size required for auto-escalation |
| `h3_index_resolution` | 8 (~0.7 km² area) | Base spatial indexing unit for rapid neighborhood querying |
| `h3_sub_resolution` | 9 (~0.1 km² area) | Precision micro-binning for high-density urban flooding |

---

## 4. Hash Fingerprinting & Anti-Spam Guardrails

Every incoming observation is immediately evaluated against the 24-hour ingestion cache:
- **Text Canonicalization:** Strips punctuation, whitespace, diacritics, and normalizes vernacular phrasing.
- **Media Perceptual Hash (pHash):** 64-bit DCT-based image fingerprinting with Hamming distance $\le 4$ detection to prevent viral or recycled historical flood photos from triggering fresh disaster alerts.
- **Rate-Limiting per Device Fingerprint:** Maximum 5 reports per 15-minute window per anonymized client ID unless tagged with verified field rescuer credentials.

---

## 5. Failure Modes & Fallback

If the spatial clustering engine experiences database lock contention or cluster explosion:
1. The ingestion pipeline falls back to bounding-box spatial partitions based on administrative district boundaries.
2. Raw reports are persisted immediately to append-only staging tables with status `UNFUSED_STAGED`.
3. Background workers replay deduplication jobs with exponential backoff once CPU load drops below 75%.
