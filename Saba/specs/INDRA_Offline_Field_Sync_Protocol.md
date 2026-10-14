# INDRA Offline Field Synchronisation Protocol (OFSP)

**Document Reference:** INDRA-FIELD-SPEC-02  
**Classification:** Core System Architecture · Disaster Response  
**Status:** Approved for Implementation  

---

## 1. Scope & Objective

During catastrophic meteorological events (super-cyclones, major cloudbursts, severe landslides), terrestrial cellular towers and fiber backbones often experience extensive blackouts. First responders, NDRF battalions, and civil defense volunteers operating in disconnected sectors must continue capturing geospatial incident assessments, casualty counts, and shelter occupancy figures without uninterrupted network access.

The **INDRA Offline Field Synchronisation Protocol (OFSP)** provides:
1. Zero-data-loss local persistence via encrypted browser IndexedDB.
2. Opportunistic store-and-forward telemetry queueing.
3. Conflict-free replicated delta merging (CRDT) for concurrent edits.
4. Seamless background synchronization through Progressive Web App (PWA) ServiceWorkers.

---

## 2. Local Storage Architecture

The field client initializes an encrypted IndexedDB instance titled `indra_offline_vault_v1`:

```
┌────────────────────────────────────────────────────────┐
│                   indra_offline_vault_v1               │
├──────────────────┬──────────────────┬──────────────────┤
│ reports_outbox   │ map_tiles_cache  │ critical_shelters│
│ (local mutations)│ (vector mbtiles) │ (read-only sync) │
└──────────────────┴──────────────────┴──────────────────┘
```

### 2.1 Outbox Record Schema

Each local mutation record is assigned a monotonic sequence number and UUIDv4 before insertion:

```typescript
export interface OfflineIncidentPayload {
  localId: string;              // UUIDv4 generated on device
  serverId?: string;            // Present if updating an existing synced record
  hazardType: 'FLOOD' | 'CYCLONE' | 'LANDSLIDE' | 'EXTREME_RAIN';
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  coordinates: {
    latitude: number;
    longitude: number;
    accuracyMeters: number;
    recordedAt: string;         // ISO-8601 UTC
  };
  casualties: {
    injured: number;
    critical: number;
    deceased: number;
  };
  mediaBlobs: Array<{
    hash: string;
    mimeType: string;
    blobData: Blob;
  }>;
  status: 'PENDING_UPLOAD' | 'IN_TRANSIT' | 'MERGED' | 'CONFLICT';
  vectorClock: Record<string, number>;
}
```

---

## 3. Conflict Resolution Strategy

When multiple rescue operators annotate the same shelter status or road blockage while operating offline in disparate sectors:

1. **State Partitioning:** Independent scalar fields (e.g. `waterLevelMeters`, `roadPassable`) use Last-Write-Wins (LWW) governed by physical UTC timestamp calibrated via device GPS time signal.
2. **Set Collections (Casualties & Supplies):** Managed via Observed-Removed-Set (OR-Set) CRDT semantics. Removing a casualty record requires tombstones to prevent resurrecting records across delayed sync loops.
3. **Escalations:** Any severity upgrade (`MEDIUM -> CRITICAL`) is monotonically dominant and cannot be overwritten by older lower-severity reports.

---

## 4. Background Sync & Bandwidth Throttle

The ServiceWorker registers a `sync` event handler (`indra-emergency-outbox-sync`):

```javascript
self.addEventListener('sync', (event) => {
  if (event.tag === 'indra-emergency-outbox-sync') {
    event.waitUntil(drainOfflineOutboxQueue());
  }
});
```

- **Compression:** Batched mutation packets are compressed using `gzip` or `zstd` before transit, decreasing cellular payload size by up to 78%.
- **Adaptive Backoff:** If the gateway returns `503 Service Unavailable` or `429 Too Many Requests`, retry delays follow truncated exponential backoff ($t_n = \min(300, 2^n \times 2)$ seconds) with 20% random jitter.
