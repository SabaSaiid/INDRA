# 🛡️ INDRA DPDP Act 2023 Compliance & Data Protection Framework

**Document:** `Saba/specs/INDRA_DPDP_Compliance_and_Data_Protection.md`  
**Classification:** Legal & Technical Compliance Architecture  
**Statutory Framework:** Digital Personal Data Protection Act (DPDP Act), 2023 (Republic of India)  
**System:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Author / Team:** Saba Saeed • Team Sixth Sense  

---

## 1. Statutory Context & Legal Requirements

In August 2023, the Parliament of India enacted the **Digital Personal Data Protection Act (DPDP Act 2023)**, establishing stringent national standards for processing digital personal data. 

While Section 17(1) of the Act permits reasonable exemptions for state agencies responding to medical emergencies, epidemics, and national disasters, INDRA adopts an uncompromising **Privacy-by-Design** architecture. Civilian crowdsourced data must never become a surveillance hazard for citizens reporting distress during a crisis.

---

## 2. Core Pillars of INDRA's Privacy-by-Design Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        INDRA FIVE-TIER DPDP COMPLIANCE SHIELD                          │
├──────────────────────────┬─────────────────────────────────────────────────────────────┤
│ Compliance Pillar        │ Architectural Implementation                                │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 1. Zero-PII Ingestion    │ Phone numbers and personal IDs are never required for       │
│                          │ citizen flood or emergency reporting.                       │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 2. Client-Side WASM Blur │ Faces and vehicle registration plates are blurred in the    │
│                          │ browser via WebAssembly *before* upload to server.          │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 3. Spatial Geo-Fuzzing   │ Public maps display coordinates truncated to ~500m ($0.005°)│
│                          │ while exact precision is restricted to rescue commanders.   │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 4. Anonymous Dockets     │ Cryptographic UUIDv4 dockets allow citizens to track report │
│                          │ lifecycle without persistent login profiles.                │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 5. Right to Erasure      │ Automated withdrawal endpoint (`/api/reports/withdraw`)     │
│                          │ purges media assets and cascades deletions across DB.       │
└──────────────────────────┴─────────────────────────────────────────────────────────────┘
```

---

## 3. Client-Side WASM Media Privacy Pipeline

To ensure raw, unredacted faces or vehicle license plates are never transmitted across cellular networks or stored in cloud buckets:
1. **Local Pre-Processing:**
   * When a citizen captures an image in the PWA, a lightweight WebAssembly module (`libwasm-privacy.wasm`) runs client-side.
   * Leverages an optimized UltraFace neural network (quantized INT8, $< 1.2\text{ MB}$ weight binary).
2. **Deterministic Blurring:**
   * Bounding boxes with face detection confidence $p \ge 0.65$ undergo Gaussian kernel blurring ($\sigma = 15$) directly on the HTML5 Canvas.
   * Vehicle license plates undergo mosaic pixelation ($16\times16$ blocks).
3. **Payload Sanitization:**
   * Only the sanitized, blurred canvas output is encoded to WebP and dispatched to the ingestion endpoint.

---

## 4. Differential Privacy & Spatial Geo-Fuzzing

To protect citizen residential privacy during disaster monitoring:

### 4.1 Resolution Tiering by Persona
* **Public / Citizen Route (`/events`, `/reports`):**
  * Report coordinates are truncated to 2 decimal places ($\approx 1.1\text{ km}$ precision) or snapped to the centroid of the containing **Uber H3 Resolution-7 Hexagon**.
  * User names are anonymized to generic tokens (e.g., `Citizen-Patna-North`).
* **Operational Command Route (`SEOC_ADMIN`, `NDRF_COMMANDER`):**
  * Authorized rescue officers access exact micro-coordinates (WGS84, 6 decimal places $\approx 0.1\text{ m}$) exclusively within an active disaster operational boundary.
  * Access to unmasked coordinates generates an immutable entry in `audit_logs` recording the officer's badge ID and access justification.

---

## 5. Right to Erasure & Data Withdrawal Protocol

Citizens possess the absolute right to revoke their report under Section 12 of the DPDP Act 2023:
* **Endpoint:** `POST /api/reports/withdraw`
* **Payload:**
  ```json
  {
    "docket_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "withdrawal_token": "sha256-signed-citizen-token",
    "reason": "MISTAKEN_REPORT"
  }
  ```
* **Execution Flow:**
  1. Validates the citizen's cryptographic token matching the docket.
  2. Permanently removes raw and processed image blobs from SeaweedFS / S3 storage.
  3. Sets `report.is_active = FALSE` and redacts text description to `[REDACTED_BY_DATA_FIDUCIARY_REQUEST]`.
  4. Triggers background spatial reclustering to remove the report from any active event hulls.
  5. Appends a cryptographic withdrawal receipt to `audit_logs`.

---

*INDRA DPDP Compliance Architecture • Team Sixth Sense • October 2026*
