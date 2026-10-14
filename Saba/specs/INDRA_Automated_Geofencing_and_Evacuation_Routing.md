# INDRA Dynamic Geofencing & Evacuation Pathfinding Specification

**Document Reference:** INDRA-GEO-SPEC-06  
**Classification:** Core Geospatial Routing Engine · SIH 2026  
**Status:** Approved for Implementation  

---

## 1. Context & Architectural Goals

During rapid-onset urban flash floods or river embankment breaches, static evacuation routes frequently steer civilians directly into low-lying submerged roadways, submerged railway underpasses, or collapsed bridges.

The INDRA Dynamic Evacuation Pathfinding subsystem dynamically modifies OpenStreetMap (OSM) weighted road graphs using real-time sensor inundation alerts to calculate safest-viable transit corridors to designated disaster relief shelters.

---

## 2. Dynamic Danger Contour Generation

Inundation polygons are generated dynamically by fusing hydrological sensor nodes, live river gauges, and verified citizen water-level reports:

```
┌───────────────────────────────┐
│ Live Inundation Depth Points  │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Inverse Distance Weighting    │  Continuous raster surface generation
│ (IDW) / Kriging Interpolation │  Cell resolution: 10m x 10m
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Contour Polygon Extraction    │  Marching Squares algorithm
│ (Depth Threshold >= 0.3m)     │  Generates dynamic exclusion geofences
└──────────────┬────────────────┘
               │
               ▼
Dynamic Hazard Geofence Vector Layer
```

---

## 3. Weighted Graph Routing Algorithm

INDRA executes a safety-biased modified Dijkstra/A* routing algorithm over the local road network graph $G = (V, E)$:

### 3.1 Edge Weight Penalty Formula

For each road segment $e \in E$:

$$W(e) = \text{Length}(e) \times \left(1 + \alpha \cdot \text{InundationDepth}(e)^2 + \beta \cdot \text{Slope}(e) + \gamma \cdot \text{CongestionFactor}(e)\right)$$

Where:
- $\alpha = 15.0$ (Severe non-linear penalty for standing water $> 0.2\text{m}$).
- $\beta = 2.5$ (Preference for higher topographic elevation).
- $\gamma = 1.8$ (Real-time traffic choke point penalty).
- If $\text{InundationDepth}(e) \ge 0.6\text{m}$, edge weight $W(e) = \infty$ (hard exclusion for pedestrian and light vehicular routing).

---

## 4. Evacuation Corridor GeoJSON API

The backend exposes `/api/v1/routing/safe-evac-route`:

```json
{
  "origin": [78.4867, 17.3850],
  "destinationShelterId": "SHELTER-HYD-CENTRAL-09",
  "routeStatus": "SAFE",
  "totalDistanceMeters": 3420,
  "estimatedTimeMinutes": 18,
  "elevationGainMeters": 14.2,
  "avoidedHazardZones": 3,
  "waypoints": [
    {"lat": 17.3850, "lng": 78.4867, "hazardDistanceMeters": 420},
    {"lat": 17.3882, "lng": 78.4891, "hazardDistanceMeters": 580},
    {"lat": 17.3940, "lng": 78.4950, "hazardDistanceMeters": 850}
  ]
}
```
