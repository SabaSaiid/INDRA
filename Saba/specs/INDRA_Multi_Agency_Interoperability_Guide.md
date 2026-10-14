# INDRA Multi-Agency Interoperability & Ingestion Interface Guide

**Document Reference:** INDRA-INT-SPEC-05  
**Classification:** Enterprise Systems Integration · Open Standards  
**Status:** Approved for Core Integration  

---

## 1. Overview & Architecture

INDRA functions as the unified synthesis hub for federal and state emergency infrastructure. By homogenizing disparate data streams from multiple statutory authorities, INDRA establishes an authoritative common operating picture (COP).

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   IMD Doppler   │    │  CWC Hydrology  │    │  Citizen & IoT  │
│   Radar Stream  │    │  Sensor Telemetry│   │  Field Sensors  │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └───────────────┬──────┴──────────────────────┘
                         ▼
           ┌────────────────────────────┐
           │   INDRA Ingestion Gateway  │
           │ (mTLS + HMAC-SHA256 Auth)  │
           └─────────────┬──────────────┘
                         ▼
           ┌────────────────────────────┐
           │ Common Schema Normalizer   │
           └─────────────┬──────────────┘
                         ▼
        State Emergency Operations Centers (EOC)
```

---

## 2. Ingestion Adapters

### 2.1 Indian Meteorological Department (IMD) Radar Feed
- **Protocol:** SFTP / Webhook push upon radial velocity or reflectivity scan completion.
- **Format:** HDF5 or NetCDF4 raster cubes converted into GeoJSON vector contour shapes.
- **Update Frequency:** 10 minutes during active convective weather warnings.

### 2.2 Central Water Commission (CWC) River Level Stream
- **Protocol:** Secure HTTPS REST polling or MQTT publish/subscribe.
- **Payload Schema:**
```json
{
  "stationId": "CWC-GODAVARI-044",
  "riverName": "Godavari",
  "basin": "Godavari Middle",
  "measuredAt": "2026-10-15T02:00:00Z",
  "waterLevelMeters": 14.82,
  "dangerLevelMeters": 15.00,
  "warningLevelMeters": 13.50,
  "trend": "RISING_RAPIDLY",
  "dischargeCusecs": 342000
}
```

---

## 3. Webhook Delivery Specification to State EOCs

INDRA broadcasts prioritized notifications to connected State Disaster Management Authority (SDMA) systems using signed HTTPS webhooks.

### 3.1 Security & Signature Validation
Every outgoing HTTP request includes the header `X-Indra-Signature`:

$$\text{Signature} = \text{HMAC-SHA256}(\text{SharedSecret}, \text{Timestamp} + "." + \text{PayloadBody})$$

Receiving EOC endpoints must compute and match the signature within a 300-second drift tolerance to protect against replay attacks.

### 3.2 Dispatch Payload Schema
```json
{
  "id": "evt_alert_20261015_00491",
  "version": "1.0",
  "timestamp": "2026-10-15T02:00:15Z",
  "urgency": "Immediate",
  "severity": "Extreme",
  "event": "Dam Spillway Water Release Warning",
  "sender": "INDRA-Central-Gateway",
  "affectedPolygon": {
    "type": "Polygon",
    "coordinates": [[[78.4867, 17.3850], [78.4980, 17.3910], [78.5020, 17.3780], [78.4867, 17.3850]]]
  },
  "recommendedAction": "Evacuate low-lying riverbank habitations within 90 minutes"
}
```
