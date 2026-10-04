# 📡 INDRA Tactical Field Rescue & Mesh Networking Specification

**Document:** `Saba/INDRA_Field_Rescue_Mesh_Networking.md`  
**Classification:** Mission-Critical Field Architecture  
**Target Operators:** National Disaster Response Force (NDRF), State Disaster Response Force (SDRF), Quick Response Teams (QRT)  
**System:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Author / Team:** Saba Saeed • Team Sixth Sense  

---

## 1. The Operational Challenge: Zero-Connectivity Search & Rescue

During severe inundations (such as the 2018 Kerala floods, 2023 North India deluge, or 2024 Wayanad landslides), cellular transmission towers lose backup diesel power within 4 to 12 hours. Rescuers operating inflatable rescue boats (IRBs) or trekking through severed mountain roads are forced into complete digital isolation.

Standard web applications that depend on persistent HTTP/WebSocket connections fail catastrophically in these conditions. INDRA solves this via an **offline-first Delay-Tolerant Networking (DTN) and tactical mesh architecture**.

---

## 2. Delay-Tolerant Networking (DTN) Store-and-Forward Architecture

```
   [Rescuer Handset A]               [Rescuer Handset B]            [Rescue Boat Gateway]
    (Offline SQLite)                  (Offline SQLite)               (LoRaWAN + Iridium)
           │                                 │                                │
           ▼                                 ▼                                ▼
   ┌───────────────┐                 ┌───────────────┐                ┌───────────────┐
   │ BLE Broadcast │ ◄──────────────►│ BLE Broadcast │◄──────────────►│ LoRa Repeater │
   │ Bundle Store  │   Ad-Hoc Mesh   │ Bundle Store  │  Store-Forward │ Satellite Mod │
   └───────────────┘                 └───────────────┘                └───────┬───────┘
                                                                              │ (Satellite / 4G)
                                                                              ▼
                                                                     ┌─────────────────┐
                                                                     │ SEOC HQ SERVER  │
                                                                     │ Central PostGIS │
                                                                     └─────────────────┘
```

### 2.1 RFC 4838 Bundle Protocol Adaptation
* When an NDRF rescuer logs a rescued citizen or victim triage status in the field, the report is serialized into an immutable binary **DTN Bundle**.
* Each bundle contains:
  * Unique Bundle ID (`URN:INDRA:BUNDLE:{res_id}:{timestamp}:{sha256}`)
  * TTL (Time-To-Live, default $72\text{ hours}$)
  * START Triage Rating (`IMMEDIATE_RED`, `DELAYED_YELLOW`, `MINOR_GREEN`, `DECEASED_BLACK`)
  * GPS coordinates and elevation
  * Cryptographic HMAC signature of the rescuer's field terminal

---

## 3. Bluetooth Low Energy (BLE 5.0) Local Mesh Fabric

Within an operational sector ($300\text{ m}$ radius across water):
1. **Ad-Hoc Discovery:**
   * Rescuer handsets continuously advertise an INDRA Tactical Service UUID (`0000INDRA-0000-1000-8000-00805F9B34FB`) via BLE 5.0 Extended Advertising packets.
   * Devices discover neighboring handsets and initiate automatic peer-to-peer GATT connections without requiring manual pairing.
2. **Gossip Protocol Synchronization:**
   * Handsets exchange summary bloom filters of cached bundle IDs.
   * If Handset B holds new triage check-ins unknown to Handset A, the missing bundles are transmitted point-to-point.
   * Duplicate bundles are eliminated locally using SQLite primary key constraints.

---

## 4. Long-Range (LoRaWAN) Vehicle & Boat Uplink

For inter-team communication across flooded districts ($3\text{--}15\text{ km}$ range):
* **Hardware Integration:**
  * Rescue command trucks and inflatable rescue boats are equipped with low-power LoRaWAN gateways operating on India's license-free **$865\text{--}867\text{ MHz}$** ISM band.
* **Modulation Parameters:**
  * Spreading Factor: $\text{SF}10$ for high link margin through torrential rainfall.
  * Bandwidth: $125\text{ kHz}$.
  * Coding Rate: $4/5$.
* **Packet Structure:**
  * Compact 51-byte payload transmitting compressed distress coordinates, water depth, and survivor count.

---

## 5. Bidirectional State Reconciliation (Return-to-Base)

When any rescue unit returns to an area with restored cellular coverage or high-bandwidth satellite link (e.g. BharatNet / BSNL VSAT terminal):
1. The client background worker detects network restoration via the Web Network Information API.
2. Fires a batch synchronization request:
   ```http
   POST /api/field/mesh-reconcile
   Content-Type: application/json
   X-INDRA-Battalion: NDRF-BN-09-PATNA
   ```
3. The central backend deduplicates ingested reports against existing records, updates the live tactical situation globe, and seals the new ground-truth confirmations in the permanent SHA-256 audit ledger.

---

*INDRA Tactical Rescue Mesh Architecture • Team Sixth Sense • October 2026*
