# INDRA Early Warning Dissemination Protocol (EWDP)
**Document Reference:** INDRA-ALERT-SPEC-04  
**Classification:** Technical Specification · Multi-Agency Relay  
**Status:** Approved for Implementation  

---

## 1. Overview

The Early Warning Dissemination Protocol (EWDP) defines the rules, formats, and dispatch priorities governing how INDRA relays official early warnings (IMD, CWC, SDMA via NDMA SACHET) and auto-escalated emergency ground observations to field responders and civilian channels.

The primary objective is sub-second distribution of actionable, localized alerts while eliminating warning fatigue through geographical polygon intersection and severity gating.

---

## 2. Ingestion & In-Force Warning Normalization

INDRA continuously ingests Common Alerting Protocol (CAP v1.2) XML/JSON feeds from SACHET.

```
       SACHET CAP Feed (Polled every 2 min)
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ Feed Parser & XML Canonicalizer               │
│ - Validate ISO-8601 timestamps (sent/expires) │
│ - Extract <area> geometry (WKT / GeoJSON)     │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PostGIS Polygon Spatial Indexing              │
│ - ST_GeomFromGeoJSON(<polygon>)               │
│ - Map to administrative districts & H3 cells  │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ In-Force Warning Registry (Active Alerts Table)│
│ - Deduplicate on <identifier> and <sender>    │
│ - Auto-retire when current_timestamp > expires│
└───────────────────────────────────────────────┘
```

---

## 3. Broadcast Priority Tiers

| Tier | Severity | Latency SLA | Target Channels |
|---|---|---|---|
| **P0 - Imminent Danger** | CRITICAL (Red Warning / Cloudburst / Flash Flood) | < 3 seconds | Cell Broadcast, Siren Nodes, Push Notification, SMS to Field Leads |
| **P1 - Severe Risk** | HIGH (Orange Warning / Inundation > 60cm) | < 15 seconds | Rescuer Portal, Telegram Bot, App Banner, Webhook to EOC |
| **P2 - Advisory** | MODERATE (Yellow Warning / Waterlogging) | < 60 seconds | Public Dashboard, Email Digest, RSS Feed |
| **P3 - Informational** | LOW / GREEN (Watch status) | < 5 minutes | Background telemetry log, Daily incident summary |

---

## 4. Multi-Language Vernacular Dispatch

Alert messages are formatted dynamically into the destination district's primary regional languages:
- **Hindi (Devanagari):** Standard North and Central Indian state EOCs.
- **Bengali, Marathi, Tamil, Telugu, Gujarati, Odia:** Targeted state emergency operational channels.
- **Hinglish Phonetic:** Optimized for SMS gateways and cellular fallback where Unicode support is limited.

---

## 5. Low-Bandwidth Cellular Broadcast Fallback & SMS Routing

### 5.1 Cellular Fallback Architecture
When IP connectivity to mobile nodes is disrupted:
1. **Cell Broadcast Service (CBS):** Broadcasts geographically bounded P0 alerts via Telecom Service Providers (TSPs) directly to BTS towers covering target H3 index cells.
2. **SMPP 3.4 SMS Gateway Pool:** Secondary fallback utilizing prioritized round-robin across national telecom aggregators (BSNL, Airtel, Jio).
3. **SMS Payload Compaction:** Restricts messages to 160 GSM 7-bit characters with condensed coordinates and emergency shelter shortcodes:
   ```
   [INDRA-ALERT:CRITICAL] FLASH FLOOD in Khairatabad. Evacuate to Govt High School Shelter (Code: SHELT-402). Do NOT enter underpasses. Call 112.
   ```

### 5.2 Circuit Breakers & Delivery Acknowledgment
- **Gateway Circuit Breaker:** If a telecom provider fails $> 5\%$ of dispatch attempts over a 60-second window, traffic automatically trips to the secondary SMPP route.
- **Field Rescuer Delivery Receipts (DLR):** Responders acknowledge P0 alerts via USSD/SMS bounce-back tokens (`ACK <alertId>`), tracked in the EOC operational dashboard to ensure battalion commander readiness.
