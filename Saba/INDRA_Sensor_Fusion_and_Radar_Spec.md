# 🛰️ INDRA Sensor Fusion & Doppler Radar Ingestion Specification

**Document:** `Saba/INDRA_Sensor_Fusion_and_Radar_Spec.md`  
**Classification:** Technical Architecture Specification  
**System:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Author / Team:** Saba Saeed • Team Sixth Sense  
**Target Release:** INDRA Enterprise v2.0 (MoES SIH26069)  

---

## 1. Executive Summary

During severe cyclonic storms and monsoon deluges, single-modality sensors consistently fail due to physical obstruction, sensor drift, or cellular backhaul degradation. INDRA solves this through a **multi-tier sensor fusion architecture** that correlates:
1. **IMD Doppler Weather Radar (DWR):** Cloud reflectivity sweeps ($Z$ in dBZ) measuring rainfall rate aloft.
2. **Ground Automated Weather Stations (AWS):** Physical surface tipping-bucket gauges.
3. **Tactical Drone / UAV Telemetry:** Low-altitude optical and thermal flood boundary delineation.
4. **Hydrological River Basin Telemetry:** Central Water Commission (CWC) stage discharge gauges.

---

## 2. IMD Doppler Weather Radar (DWR) Pipeline

### 2.1 Physics & Reflectivity Formulation
IMD operates 37+ S-band and C-band Doppler Weather Radars across the Indian coast and metropolitan areas. The radar emits microwave pulses and measures backscattered power:
$$Z = \int_{0}^{\infty} N(D) D^6 \, dD \quad [\text{mm}^6/\text{m}^3]$$

To convert radar reflectivity factor $Z$ into operational surface rainfall intensity $R$ (in $\text{mm/hr}$), INDRA applies the standard **Marshall-Palmer Z-R Relationship**:
$$Z = 200 \times R^{1.6} \iff R = \left(\frac{Z}{200}\right)^{\frac{1}{1.6}}$$

For high-intensity convective squalls and cyclone rainbands, INDRA dynamically switches to tropical monsoon coefficients:
$$Z = 300 \times R^{1.4}$$

### 2.2 Color-Coded Reflectivity Scale
| Reflectivity Range (dBZ) | Rainfall Category | Operational Meaning | Map Styling Color |
| :--- | :--- | :--- | :--- |
| **$< 20\text{ dBZ}$** | Trace / Drizzle | Very light mist; negligible hazard | `#4A6670` (Subtle Slate) |
| **$20\text{--}35\text{ dBZ}$** | Moderate Rain | $2.5\text{--}10\text{ mm/hr}$; road traction warning | `#4C7A5B` (Verified Green) |
| **$35\text{--}45\text{ dBZ}$** | Heavy Downpour | $10\text{--}30\text{ mm/hr}$; urban drainage saturation | `#B8873A` (Amber Alert) |
| **$45\text{--}55\text{ dBZ}$** | Severe Convective Storm | $30\text{--}70\text{ mm/hr}$; localized flash flooding | `#B5482E` (Terracotta High) |
| **$\ge 55\text{ dBZ}$** | Cloudburst / Hail | $> 70\text{ mm/hr}$; structural damage & mudslides | `#8C2F26` (Critical Maroon) |

---

## 3. Tactical Drone (UAV) Aerial Telemetry Ingestion

### 3.1 Field Drone Protocol
When NDRF or civil defense deploy tactical quadcopters over inundated districts:
* **UAV Telemetry Packet (`drone_telemetry`):**
  ```json
  {
    "drone_id": "NDRF-UAV-BATTALION-04",
    "mission_id": "MISSION-PATNA-NORTH-08",
    "telemetry": {
      "latitude": 25.6125,
      "longitude": 85.1442,
      "altitude_agl_m": 85.4,
      "ground_speed_kmh": 22.1,
      "heading_deg": 142.0,
      "camera_pitch_deg": -45.0,
      "battery_pct": 74
    },
    "edge_detections": {
      "water_detected": true,
      "estimated_flood_area_m2": 45200.0,
      "stranded_persons_count": 6,
      "confidence": 0.94
    },
    "timestamp_iso": "2026-10-04T13:20:00Z"
  }
  ```

### 3.2 Drone Footprint Georeferencing
The spatial ground footprint of the drone camera is computed dynamically from altitude $h$ and field-of-view $\theta$:
$$W_{\text{footprint}} = 2 \times h \times \tan\left(\frac{\theta_{\text{horiz}}}{2}\right)$$
The resulting quadrilateral polygon is projected onto the PostGIS map canvas as an active aerial reconnaissance layer.

---

## 4. Directed Acyclic Graph (DAG) for Multi-Sensor Fusion

```
   [IMD Radar Sweep (dBZ)]    [Surface AWS Rain (mm)]    [UAV Aerial GeoJSON]
              │                          │                         │
              ▼                          ▼                         ▼
   ┌──────────────────────┐   ┌──────────────────────┐  ┌──────────────────────┐
   │ Spatial Grid Mapper  │   │ In-Memory H3 Cache   │  │ Edge Vision Parser   │
   │ (Marshall-Palmer Z-R)│   │ (Haversine 5km Gate) │  │ (START Triage Tagger)│
   └──────────┬───────────┘   └──────────┬───────────┘  └──────────┬───────────┘
              │                          │                         │
              └──────────────────┐       │       ┌─────────────────┘
                                 ▼       ▼       ▼
                     ┌───────────────────────────────────────┐
                     │     INDRA MULTI-SENSOR FUSION CORE    │
                     │  • Spatial Concordance Matrix         │
                     │  • Temporal Coincidence Window (±15m) │
                     │  • Physics Elevation Slope Check      │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     UNIFIED HAZARD EVENT PROFILE      │
                     │  • 100-Point Verification Receipt     │
                     │  • Concave Hull Impact Polygon        │
                     │  • Automatic Severity Level Rating    │
                     └───────────────────────────────────────┘
```

---

*INDRA Sovereign Remote Sensing Architecture • Team Sixth Sense • October 2026*
