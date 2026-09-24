'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Card, CardHeader } from '@/components/ui/card';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { severityConfig, type MapMarker } from '@/lib/ui-config';
import {
  fetchEvents,
  apiEventsToMapMarkers,
  fetchAgencyAlerts,
  agencyAlertsToMapMarkers,
  fetchFieldReports,
  fieldReportsToMapMarkers,
} from '@/lib/api';
import type { MapLayer } from '@/lib/ui-config';
import { sanitizeIncidentCoordinate } from '@/lib/geo-resolver';
import { cn } from '@/lib/utils';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import {
  Globe,
  Map as MapIcon,
  Maximize2,
  Minimize2,
  Compass,
  Layers,
  Zap,
  Wind,
  CloudFog,
  Sparkles,
  Satellite,
  Moon,
  Eye,
  Radio,
  AlertTriangle,
  Shield,
  X,
  Target,
  Navigation,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Activity,
  CheckCircle2,
  Play,
  Pause,
  MapPin,
  FileSpreadsheet,
  Info,
  Terminal,
  RotateCcw,
  Check,
  Filter,
} from 'lucide-react';

export type BasemapMode = 'satellite' | 'topo' | 'dark' | 'street';

// Basemap Styles with Globe Projection, Glyphs & Atmospheric Sky
/**
 * The camera that frames all of India in the canvas it is given. The fixed
 * zoom 5.0 it replaces was tuned for one canvas size: on the dashboard's
 * shorter map it cut off the south of the peninsula and the pins on it, and a
 * taller canvas left sea at the edges. The pitch is applied on top, which only
 * widens what the top of the view shows.
 */
const INDIA_BOUNDS: [[number, number], [number, number]] = [[68.0, 6.5], [97.5, 35.5]];
function indiaCamera(map: maplibregl.Map): { center: [number, number]; zoom: number } {
  const cam = map.cameraForBounds(INDIA_BOUNDS, { padding: 24 });
  // The flat fit is computed without the 30° pitch, which shows more ground at
  // the top of the view, so it can sit about half a level closer; the centre
  // moves south by the same token to keep the peninsula's tip in frame.
  const zoom = Math.min(5.0, Math.max(3.6, (cam?.zoom ?? 4.4) + 0.6));
  const c = cam?.center ? maplibregl.LngLat.convert(cam.center) : null;
  return { center: c ? [c.lng, c.lat - 1.2] : [82.0, 21.0], zoom };
}

const BASEMAP_STYLES: Record<BasemapMode, any> = {
  satellite: {
    version: 8,
    projection: { type: 'globe' },
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      esri_satellite: {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        attribution: '© Esri, Earthstar Geographics',
      },
    },
    layers: [
      {
        id: 'esri-satellite-layer',
        type: 'raster',
        source: 'esri_satellite',
        minzoom: 0,
        maxzoom: 19,
      },
    ],
    sky: {
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0, 1.0,
        5, 0.2,
      ],
    },
  },
  topo: {
    version: 8,
    projection: { type: 'globe' },
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      esri_topo: {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        attribution: '© Esri, USGS, NOAA, Survey of India',
      },
    },
    layers: [
      {
        id: 'esri-topo-layer',
        type: 'raster',
        source: 'esri_topo',
        minzoom: 0,
        maxzoom: 19,
      },
    ],
    sky: {
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0, 0.6,
        5, 0.0,
      ],
    },
  },
  dark: {
    version: 8,
    projection: { type: 'globe' },
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      carto_dark: {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
          'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
          'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
        ],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors, © CARTO',
      },
    },
    layers: [
      {
        id: 'carto-dark-layer',
        type: 'raster',
        source: 'carto_dark',
        minzoom: 0,
        maxzoom: 19,
      },
    ],
    sky: {
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0, 1.0,
        5, 0.1,
      ],
    },
  },
  street: {
    version: 8,
    projection: { type: 'globe' },
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      carto_voyager: {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
          'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
        ],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors, © CARTO',
      },
    },
    layers: [
      {
        id: 'carto-voyager-layer',
        type: 'raster',
        source: 'carto_voyager',
        minzoom: 0,
        maxzoom: 19,
      },
    ],
    sky: {
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0, 0.8,
        5, 0.0,
      ],
    },
  },
};

// Severity color palette
const severityColors: Record<string, string> = {
  critical: '#EF4444',
  high: '#F59E0B',
  moderate: '#3B82F6',
  advisory: '#94A3B8',
  low: '#64748B',
};

// Severity priority ranking for collision avoidance
const severityRank: Record<string, number> = {
  critical: 4,
  high: 3,
  moderate: 2,
  advisory: 1,
  low: 1,
};

// Event type emojis
const eventTypeEmojis: Record<string, string> = {
  'Severe Rainfall': '🌧️',
  'Flood': '🌊',
  'Urban Flooding': '🌊',
  'Heavy Rainfall': '🌧️',
  'Thunderstorm': '⚡',
  'Strong Winds': '💨',
  'Fog': '🌫️',
};

/** What a marker's status honestly is, by layer. It used to read "AI Verified" for all of them. */
function markerStatusLabel(marker: MapMarker): string {
  const layer = marker.layer ?? 'event';
  if (layer === 'alert') return 'Official warning';
  if (layer === 'report') return 'Unverified citizen report';
  // Rejected events are dropped by the API, so an event here is one of these two.
  return marker.verification === 'verified' ? 'Verified event' : 'Event under review';
}

function markerSourceLabel(marker: MapMarker): string {
  const layer = marker.layer ?? 'event';
  if (layer === 'alert') return marker.title ? `${marker.title} via SACHET` : 'SACHET (CAP)';
  if (layer === 'report') return 'Citizen report';
  return 'INDRA fusion';
}

/**
 * The three kinds of live data this map draws, and how each is marked.
 *
 * The glyphs match the pin shapes: a filled circle is a fused, scored event;
 * a diamond is an official agency warning from SACHET; a hollow circle is a
 * raw citizen report that has not been clustered or corroborated.
 */
const LAYER_CHIPS: {
  layer: MapLayer;
  label: string;
  glyph: string;
  title: string;
  onClass: string;
}[] = [
  {
    layer: 'event',
    label: 'Events',
    glyph: '\u25CF',
    title: 'Fused, scored events produced by the verification pipeline',
    onClass: 'bg-rose-50 text-rose-700 border-rose-200',
  },
  {
    layer: 'alert',
    label: 'Agency',
    glyph: '\u25C6',
    title: 'Live CAP warnings from SACHET — IMD, CWC and state SDMAs',
    onClass: 'bg-violet-50 text-violet-700 border-violet-200',
  },
  {
    layer: 'report',
    label: 'Field',
    glyph: '\u25CB',
    title: 'Citizen reports not yet fused into an event — unverified',
    onClass: 'bg-slate-50 text-slate-700 border-slate-300',
  },
];

export default function GlobeEventMap({
  selectedEventId,
  onEventSelect,
  variant = 'full',
  canvasClassName,
}: {
  selectedEventId?: string;
  onEventSelect?: (marker: MapMarker | null) => void;
  variant?: 'full' | 'preview';
  /**
   * Height classes for the map canvas, replacing the fixed default. Pages pass
   * a viewport-relative height so the map fills the screen instead of leaving
   * a band of empty page under it.
   */
  canvasClassName?: string;
}) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Array<{ id: string; marker: maplibregl.Marker; el: HTMLElement; lng: number; lat: number }>>([]);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const autoOrbitAnimRef = useRef<number | null>(null);
  const renderProminentPinsRef = useRef<() => void>(() => {});

  const [mounted, setMounted] = useState(false);
  const [webGLSupported, setWebGLSupported] = useState(true);
  const [isGlobe, setIsGlobe] = useState(true);
  const isGlobeRef = useRef(true);
  const [basemap, setBasemap] = useState<BasemapMode>('satellite');
  const [timeRange, setTimeRange] = useState('7d');
  // Starts empty. Seeding the globe with invented markers put pins on Indian
  // cities that had reported nothing.
  const [markers, setMarkers] = useState<MapMarker[]>([]);
  const [markersError, setMarkersError] = useState<unknown>(null);
  // Three sources of live data, three layers, each toggleable and each drawn
  // differently. The map used to show fused events only — one pin — while 112
  // real agency warnings and every unfused citizen report sat in the database
  // with nowhere to appear (BUG-037).
  const [visibleLayers, setVisibleLayers] = useState<Record<MapLayer, boolean>>({
    event: true,
    alert: true,
    report: true,
  });
  const [visibleSeverities, setVisibleSeverities] = useState<Record<string, boolean>>({
    critical: true,
    high: true,
    moderate: true,
    advisory: true,
    low: true,
  });
  const [hiddenHazards, setHiddenHazards] = useState<Set<string>>(new Set());
  const [refreshTick, setRefreshTick] = useState(0);
  const [selectedMarker, setSelectedMarker] = useState<MapMarker | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isAutoOrbiting, setIsAutoOrbiting] = useState(false);
  const [isRosterOpen, setIsRosterOpen] = useState(false);
  const [smartDeclutter, setSmartDeclutter] = useState(true);
  // Issue 5: Debug HUD is opt-in, not shown by default.
  const [showTechReadout, setShowTechReadout] = useState(false);
  // Issue 2: Collapsible map legend.
  const [legendOpen, setLegendOpen] = useState(false);
  // Issue 3: Cluster popover state — which cluster is expanded and where to place it.
  const [clusterPopover, setClusterPopover] = useState<{
    items: MapMarker[];
    position: { x: number; y: number };
    maxSeverity: string;
  } | null>(null);

  // True once the map's style has finished loading and layers may be touched.
  //
  // This is deliberately React state and not a `map.isStyleLoaded()` call.
  // MapLibre keeps reporting `isStyleLoaded() === false` while sprites, glyphs
  // and the first tiles are still in flight, which is long after the one-shot
  // `load` event has already fired. Any code that reads `isStyleLoaded()` to
  // decide whether to draw therefore loses a race it cannot win: it sees
  // `false`, waits for a `load` that will never come a second time, and gives
  // up silently. Holding the answer in state instead re-runs the effects that
  // depend on it at the moment the style really is ready.
  const [styleReady, setStyleReady] = useState(false);

  // Layer toggles
  const [showEventsLayer, setShowEventsLayer] = useState(true);

  // Live telemetry state
  const [telemetry, setTelemetry] = useState({
    zoom: 5.0,
    lat: 22.0,
    lng: 82.0,
    pitch: 30,
    bearing: 0,
  });



  useEffect(() => {
    isGlobeRef.current = isGlobe;
  }, [isGlobe]);

  useEffect(() => {
    setMounted(true);
    if (typeof window !== 'undefined') {
      try {
        const canvas = document.createElement('canvas');
        const isSupported = !!(
          window.WebGLRenderingContext &&
          (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
        );
        if (!isSupported) {
          setWebGLSupported(false);
        }
      } catch {
        setWebGLSupported(false);
      }
    }
  }, []);

  // Dismiss overlays (legend, cluster popover) on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setLegendOpen(false);
        setClusterPopover(null);
        // The roster opens over the same corner and stayed open on Escape.
        setIsRosterOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Fetch all three live layers.
  //
  // allSettled, not all: a failure in any one layer must not blank the other
  // two. The events layer is the only one whose failure is surfaced as an
  // error, because an empty alert or report layer is a normal state and an
  // empty event layer on a working stack is not.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [events, alerts, reports] = await Promise.allSettled([
        fetchEvents({ time_range: timeRange }),
        fetchAgencyAlerts(200),
        // Seven days, the same window as the events layer. At 72 h a report
        // that never joined an event vanished from the map on its third day.
        fetchFieldReports(200, 168),
      ]);

      if (cancelled) return;

      const next: MapMarker[] = [];
      if (events.status === 'fulfilled') {
        next.push(...apiEventsToMapMarkers(events.value));
        setMarkersError(null);
      } else {
        setMarkersError(events.reason);
      }
      if (alerts.status === 'fulfilled') {
        next.push(...agencyAlertsToMapMarkers(alerts.value));
      }
      if (reports.status === 'fulfilled') {
        next.push(...fieldReportsToMapMarkers(reports.value));
      }

      // An empty map is the correct picture of an empty database.
      setMarkers(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [timeRange, refreshTick]);

  // A verified event finishing the pipeline is the one moment this map is
  // certainly stale. The backend has broadcast VERIFIED_EVENT since Day 1 and
  // nothing in the frontend has ever listened for it (BUG-036). Listens on the
  // shared connection; this component used to open a raw socket of its own.
  const { subscribe } = useIndraWebSocket();
  useEffect(() => {
    return subscribe(`globe-map-${variant}`, (msg) => {
      if (msg.type === 'VERIFIED_EVENT' || msg.type === 'NEW_REPORT' || msg.type === 'EVENT_REVIEWED') {
        setRefreshTick((t) => t + 1);
      }
    });
  }, [subscribe, variant]);

  // Official warnings arrive from the SACHET poller, which broadcasts nothing,
  // and expire on their own clock. Without this the warning layer stayed as it
  // was when the page opened: expired warnings kept their pins and new ones
  // never appeared until a reload.
  useEffect(() => {
    const id = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        setRefreshTick((t) => t + 1);
      }
    }, 120_000);
    return () => clearInterval(id);
  }, []);

  // Dynamically extract unique hazard types from loaded markers
  const availableHazards = React.useMemo(() => {
    const set = new Set<string>();
    markers.forEach((m) => {
      if (m.eventType) set.add(m.eventType);
    });
    return Array.from(set).sort();
  }, [markers]);

  const isAnyFilterActive =
    !visibleLayers.event ||
    !visibleLayers.alert ||
    !visibleLayers.report ||
    !visibleSeverities.critical ||
    !visibleSeverities.high ||
    !visibleSeverities.moderate ||
    !visibleSeverities.advisory ||
    !visibleSeverities.low ||
    hiddenHazards.size > 0;

  const resetAllFilters = useCallback(() => {
    setVisibleLayers({ event: true, alert: true, report: true });
    setVisibleSeverities({
      critical: true,
      high: true,
      moderate: true,
      advisory: true,
      low: true,
    });
    setHiddenHazards(new Set());
  }, []);

  const markersForDisplay = React.useMemo(() => {
    if (!showEventsLayer) return [];
    return markers.filter((m) => {
      if (!visibleLayers[m.layer ?? 'event']) return false;
      if (visibleSeverities[m.severity] === false) return false;
      if (hiddenHazards.has(m.eventType)) return false;
      return true;
    });
  }, [markers, visibleLayers, visibleSeverities, hiddenHazards, showEventsLayer]);

  // Compute item counts by layer, severity, and hazard for the interactive filter panel
  const filterCounts = React.useMemo(() => {
    const layers: Record<string, number> = { event: 0, alert: 0, report: 0 };
    const severities: Record<string, number> = {
      critical: 0,
      high: 0,
      moderate: 0,
      advisory: 0,
      low: 0,
    };
    const hazards: Record<string, number> = {};

    markers.forEach((m) => {
      const layer = m.layer ?? 'event';
      if (layers[layer] !== undefined) layers[layer]++;
      if (m.severity && severities[m.severity] !== undefined) {
        severities[m.severity]++;
      }
      if (m.eventType) {
        hazards[m.eventType] = (hazards[m.eventType] || 0) + 1;
      }
    });

    return { layers, severities, hazards };
  }, [markers]);

  // Select an incident
  const handleSelectIncident = useCallback(
    (marker: MapMarker) => {
      setSelectedMarker(marker);
      setLegendOpen(false);
      setClusterPopover(null);
      if (onEventSelect) onEventSelect(marker);

      const sanitized = sanitizeIncidentCoordinate({
        lat: marker.lat,
        lng: marker.lng,
        city: marker.city,
        state: marker.state,
      });

      const map = mapRef.current;
      if (map) {
        map.flyTo({
          center: [sanitized.lng, sanitized.lat],
          zoom: 6.8,
          pitch: 45,
          bearing: 15,
          essential: true,
          duration: 1800,
          // Offset target 90px to the right so it stays in the clear map area
          // without colliding with the 320px left-side inspector drawer.
          offset: [90, 0],
        });
      }
    },
    [onEventSelect]
  );

  // Sync external selectedEventId
  useEffect(() => {
    if (selectedEventId) {
      const match = markers.find((m) => m.id === selectedEventId);
      if (match) {
        handleSelectIncident(match);
      }
    }
  }, [selectedEventId, markers, handleSelectIncident]);

  // Update Horizon Occlusion for Markers on 3D Globe
  const updateMarkerOcclusion = useCallback(
    (map: maplibregl.Map, globeMode: boolean) => {
      if (!showEventsLayer) {
        markersRef.current.forEach(({ el }) => {
          el.style.display = 'none';
        });
        return;
      }

      if (!globeMode) {
        markersRef.current.forEach(({ el }) => {
          el.style.display = 'block';
          el.style.opacity = '1';
        });
        return;
      }

      const center = map.getCenter();
      const toRad = Math.PI / 180;
      const phi2 = center.lat * toRad;
      const lambda2 = center.lng * toRad;

      markersRef.current.forEach(({ el, lng, lat }) => {
        const phi1 = lat * toRad;
        const lambda1 = lng * toRad;
        const deltaLambda = lambda1 - lambda2;

        // Spherical angular distance (cosine of angle between camera center and marker)
        const cosTheta = Math.sin(phi1) * Math.sin(phi2) + Math.cos(phi1) * Math.cos(phi2) * Math.cos(deltaLambda);

        // In 3D Globe mode, points on the far side of the planet (over horizon) are hidden
        if (cosTheta < 0.05) {
          el.style.display = 'none';
        } else {
          el.style.display = 'block';
          const opacity = Math.min(1, Math.max(0, (cosTheta - 0.05) / 0.25));
          el.style.opacity = opacity.toFixed(2);
        }
      });
    },
    [showEventsLayer]
  );


  // Render Adaptive Tactical Pins via MapLibre DOM Matrix with LOD & Collision Avoidance
  const renderProminentPins = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    // Clear existing markers cleanly
    markersRef.current.forEach(({ marker }) => marker.remove());
    markersRef.current = [];

    if (!showEventsLayer) return;

    const zoom = map.getZoom();
    const isSpaceZoom = zoom < 2.4;
    const isCompactZoom = zoom >= 2.4 && zoom < 4.2;
    const isDetailZoom = zoom >= 6.2;

    // 1. Process and sanitize all marker coordinates
    const sanitizedMarkers = markersForDisplay.map((m) => {
      const coords = sanitizeIncidentCoordinate({
        lat: m.lat,
        lng: m.lng,
        city: m.city,
        state: m.state,
        title: m.title,
        eventType: m.eventType,
      });
      return {
        marker: m,
        coords,
      };
    });

    // 2. Spatial Clustering & Screen-space Collision Detection
    interface ClusterGroup {
      isCluster: boolean;
      items: Array<{ marker: MapMarker; coords: { lng: number; lat: number } }>;
      center: { lng: number; lat: number };
      maxSeverity: string;
      screenPos?: { x: number; y: number };
      hideLabel?: boolean;
    }

    let itemsToRender: ClusterGroup[] = [];

    if (isSpaceZoom) {
      // Tier 1: Space Orbit (zoom < 2.4) — All markers render as micro-radar pips without text labels
      itemsToRender = sanitizedMarkers.map((sm) => ({
        isCluster: false,
        items: [sm],
        center: sm.coords,
        maxSeverity: sm.marker.severity,
        hideLabel: true,
      }));
    } else {
      // Tier 2+ (zoom >= 2.4): Screen-space clustering and collision avoidance.
      // Issue 4: clustering now runs at ALL zoom tiers above space-orbit, not
      // just Tier 2. The radius shrinks as the user zooms in so badges that are
      // genuinely far apart on screen stop merging.
      const projected = sanitizedMarkers.map((sm) => {
        const pt = map.project([sm.coords.lng, sm.coords.lat]);
        return {
          ...sm,
          x: pt.x,
          y: pt.y,
          assigned: false,
        };
      });

      // Shrink cluster radius as zoom increases — tight at detail level.
      const CLUSTER_RADIUS = isCompactZoom ? 44 : isDetailZoom ? 28 : 36;

      for (let i = 0; i < projected.length; i++) {
        if (projected[i].assigned) continue;

        // Never cluster selected marker so user always sees their active selection
        const isSelected = selectedMarker?.id === projected[i].marker.id;
        if (isSelected) {
          projected[i].assigned = true;
          itemsToRender.push({
            isCluster: false,
            items: [projected[i]],
            center: projected[i].coords,
            maxSeverity: projected[i].marker.severity,
            screenPos: { x: projected[i].x, y: projected[i].y },
            hideLabel: false,
          });
          continue;
        }

        const group = [projected[i]];
        projected[i].assigned = true;

        for (let j = i + 1; j < projected.length; j++) {
          if (projected[j].assigned) continue;
          if (selectedMarker?.id === projected[j].marker.id) continue;

          const dx = projected[i].x - projected[j].x;
          const dy = projected[i].y - projected[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < CLUSTER_RADIUS) {
            group.push(projected[j]);
            projected[j].assigned = true;
          }
        }

        if (group.length > 1) {
          let sumLng = 0;
          let sumLat = 0;
          let highestRank = 0;
          let maxSev = 'low';

          group.forEach((g) => {
            sumLng += g.coords.lng;
            sumLat += g.coords.lat;
            const rank = severityRank[g.marker.severity] || 1;
            if (rank > highestRank) {
              highestRank = rank;
              maxSev = g.marker.severity;
            }
          });

          itemsToRender.push({
            isCluster: true,
            items: group,
            center: { lng: sumLng / group.length, lat: sumLat / group.length },
            maxSeverity: maxSev,
            screenPos: { x: projected[i].x, y: projected[i].y },
          });
        } else {
          itemsToRender.push({
            isCluster: false,
            items: [projected[i]],
            center: projected[i].coords,
            maxSeverity: projected[i].marker.severity,
            screenPos: { x: projected[i].x, y: projected[i].y },
            hideLabel: false,
          });
        }
      }

      // Label collision suppression for unclustered pins
      const singlePins = itemsToRender.filter((c) => !c.isCluster);
      singlePins.sort((a, b) => {
        if (a.items[0].marker.id === selectedMarker?.id) return -1;
        if (b.items[0].marker.id === selectedMarker?.id) return 1;
        return (severityRank[b.maxSeverity] || 1) - (severityRank[a.maxSeverity] || 1);
      });

      const LABEL_COLLISION_X = 68; // pixels
      const LABEL_COLLISION_Y = 24; // pixels

      for (let i = 0; i < singlePins.length; i++) {
        if (singlePins[i].hideLabel) continue;
        const posA = singlePins[i].screenPos;
        if (!posA) continue;

        for (let j = i + 1; j < singlePins.length; j++) {
          if (singlePins[j].hideLabel) continue;
          const posB = singlePins[j].screenPos;
          if (!posB) continue;

          const dx = Math.abs(posA.x - posB.x);
          const dy = Math.abs(posA.y - posB.y);

          if (dx < LABEL_COLLISION_X && dy < LABEL_COLLISION_Y) {
            singlePins[j].hideLabel = true;
          }
        }
      }

      // Suppress single pin labels that collide with cluster badges
      const clusters = itemsToRender.filter((c) => c.isCluster);
      singlePins.forEach((pin) => {
        if (pin.hideLabel || !pin.screenPos) return;
        for (const cl of clusters) {
          if (!cl.screenPos) continue;
          const dx = Math.abs(pin.screenPos.x - cl.screenPos.x);
          const dy = Math.abs(pin.screenPos.y - cl.screenPos.y);
          if (dx < 55 && dy < 38) {
            pin.hideLabel = true;
            break;
          }
        }
      });
    }

    // Issue 1: Sort so higher-severity clusters render last (on top in DOM).
    itemsToRender.sort((a, b) => (severityRank[a.maxSeverity] || 1) - (severityRank[b.maxSeverity] || 1));

    // Dynamic edge-aware tooltip positioning to prevent clipping at map container boundaries
    const positionTooltip = (tooltip: HTMLElement, anchorEl: HTMLElement) => {
      const mapContainer = mapContainerRef.current;
      if (!mapContainer) return;
      const mapRect = mapContainer.getBoundingClientRect();
      const anchorRect = anchorEl.getBoundingClientRect();

      const tooltipWidth = 220;
      const tooltipHeight = tooltip.offsetHeight || 65;

      const spaceAbove = anchorRect.top - mapRect.top;
      const spaceBelow = mapRect.bottom - anchorRect.bottom;
      // Flip below if not enough room above
      const placeBelow = spaceAbove < (tooltipHeight + 16) && spaceBelow >= (tooltipHeight + 10);

      if (placeBelow) {
        tooltip.style.bottom = 'auto';
        tooltip.style.top = '100%';
        tooltip.style.marginTop = '6px';
        tooltip.style.marginBottom = '0';
      } else {
        tooltip.style.top = 'auto';
        tooltip.style.bottom = '100%';
        tooltip.style.marginTop = '0';
        tooltip.style.marginBottom = '6px';
      }

      // Horizontal edge protection
      const anchorCenterFromLeft = (anchorRect.left + anchorRect.width / 2) - mapRect.left;
      const anchorCenterFromRight = mapRect.right - (anchorRect.left + anchorRect.width / 2);
      const halfW = tooltipWidth / 2;

      if (anchorCenterFromLeft < halfW + 12) {
        tooltip.style.left = '0';
        tooltip.style.right = 'auto';
        tooltip.style.transform = placeBelow ? 'translateY(2px)' : 'translateY(-2px)';
      } else if (anchorCenterFromRight < halfW + 12) {
        tooltip.style.left = 'auto';
        tooltip.style.right = '0';
        tooltip.style.transform = placeBelow ? 'translateY(2px)' : 'translateY(-2px)';
      } else {
        tooltip.style.left = '50%';
        tooltip.style.right = 'auto';
        tooltip.style.transform = placeBelow ? 'translateX(-50%) translateY(2px)' : 'translateX(-50%) translateY(-2px)';
      }
    };

    // 3. Render DOM Elements for each item
    itemsToRender.forEach((item) => {
      if (item.isCluster) {
        // --- RENDER TACTICAL CLUSTER ---
        const clusterEl = document.createElement('div');
        clusterEl.className = 'indra-tactical-marker select-none';
        clusterEl.style.cursor = 'pointer';
        // Issue 1: z-index by severity so urgent clusters always render on top.
        const sevRank = severityRank[item.maxSeverity] || 1;
        clusterEl.style.zIndex = String(10 + sevRank * 2); // critical=18, high=16, moderate=14, low=12

        const innerEl = document.createElement('div');
        innerEl.className = 'indra-marker-inner';
        clusterEl.appendChild(innerEl);

        const color = severityColors[item.maxSeverity] || '#EF4444';
        const dominantEmoji = eventTypeEmojis[item.items[0].marker.eventType] || '⚠️';

        // Issue 1: Badge size and background scale with severity.
        const isCritical = item.maxSeverity === 'critical';
        const isHigh = item.maxSeverity === 'high';
        const badgePadding = isCritical ? '5px 12px 5px 8px' : isHigh ? '4px 10px 4px 7px' : '3px 8px 3px 6px';
        const badgeBg = isCritical ? '#DC2626' : isHigh ? '#D97706' : 'rgba(30, 42, 59, 0.96)';
        const badgeFontSize = isCritical ? '13px' : isHigh ? '12px' : '11px';

        const clusterBadge = document.createElement('div');
        clusterBadge.className = 'indra-marker-cluster';
        clusterBadge.style.borderColor = color;
        clusterBadge.style.backgroundColor = badgeBg;
        clusterBadge.style.padding = badgePadding;
        clusterBadge.style.boxShadow = `0 4px 14px rgba(0,0,0,0.6), 0 0 12px ${color}80`;
        clusterBadge.innerHTML = `
          <span class="indra-marker-cluster-pulse" style="background-color: ${isCritical || isHigh ? '#fff' : color};"></span>
          <span style="font-size: ${badgeFontSize};">${dominantEmoji}</span>
          <span style="font-size: ${badgeFontSize}; font-weight: 800; color: #ffffff; margin-left: 2px;">${item.items.length}</span>
        `;
        innerEl.appendChild(clusterBadge);

        // Primary location and hazards for compact hover preview
        const cityCounts: Record<string, number> = {};
        const hazardIcons = new Set<string>();
        item.items.forEach(m => {
          const c = m.marker.city || m.marker.state;
          if (c) cityCounts[c] = (cityCounts[c] || 0) + 1;
          const em = eventTypeEmojis[m.marker.eventType];
          if (em) hazardIcons.add(em);
        });
        const primaryLocation = Object.entries(cityCounts).sort(([, a], [, b]) => b - a)[0]?.[0] || 'Subcontinent Region';
        const hazardList = Array.from(hazardIcons).slice(0, 3).join(' ');

        // Severity breakdown string
        const sevBreakdown: Record<string, number> = {};
        item.items.forEach(m => {
          const s = m.marker.severity || 'low';
          sevBreakdown[s] = (sevBreakdown[s] || 0) + 1;
        });
        const sevSummary = Object.entries(sevBreakdown)
          .sort(([, a], [, b]) => b - a)
          .map(([s, n]) => `${n} ${s}`)
          .join(', ');

        const tooltip = document.createElement('div');
        tooltip.className = 'indra-hud-popup';
        tooltip.style.position = 'absolute';
        tooltip.style.bottom = '100%';
        tooltip.style.left = '50%';
        tooltip.style.transform = 'translateX(-50%) translateY(-6px)';
        tooltip.style.opacity = '0';
        tooltip.style.pointerEvents = 'none';
        tooltip.style.zIndex = '50';
        tooltip.style.width = '220px';
        tooltip.innerHTML = `
          <div class="hud-header">
            <span class="hud-badge hud-${item.maxSeverity}">${item.maxSeverity} CLUSTER</span>
            <span class="hud-time font-bold text-white">${item.items.length} incidents</span>
          </div>
          <div class="hud-location mt-1">📍 ${primaryLocation}</div>
          <div class="hud-sub">
            <span>${hazardList}</span>
            <span class="hud-sev-breakdown">${sevSummary}</span>
          </div>
          <div class="hud-action">
            <span>Click to inspect breakdown</span>
            <span style="font-size: 11px;">→</span>
          </div>
        `;
        innerEl.appendChild(tooltip);

        clusterEl.addEventListener('mouseenter', () => {
          positionTooltip(tooltip, clusterEl);
          innerEl.style.transform = 'scale(1.15) translateY(-2px)';
          tooltip.style.opacity = '1';
          clusterEl.style.zIndex = '50';
        });

        clusterEl.addEventListener('mouseleave', () => {
          innerEl.style.transform = 'scale(1) translateY(0)';
          tooltip.style.opacity = '0';
          clusterEl.style.zIndex = String(10 + sevRank * 2);
        });

        // Issue 3: Click opens a popover with deduplicated detail instead of
        // just zooming. The popover is rendered in React via clusterPopover state.
        clusterEl.addEventListener('click', (e) => {
          e.stopPropagation();
          setSelectedMarker(null);
          setLegendOpen(false);
          const rect = mapContainerRef.current?.getBoundingClientRect();
          const markerPos = item.screenPos || { x: 0, y: 0 };
          // Smart positioning: if the popover would go off the right/bottom edge, flip.
          const popX = rect ? Math.min(markerPos.x, rect.width - 300) : markerPos.x;
          const popY = rect ? Math.min(markerPos.y, rect.height - 260) : markerPos.y;
          setClusterPopover({
            items: item.items.map(m => m.marker),
            position: { x: Math.max(8, popX), y: Math.max(8, popY) },
            maxSeverity: item.maxSeverity,
          });
        });

        const mapMarker = new maplibregl.Marker({ element: clusterEl, anchor: 'center' })
          .setLngLat([item.center.lng, item.center.lat])
          .addTo(map);

        markersRef.current.push({
          id: `cluster-${item.items.map(m => m.marker.id).join('-')}`,
          marker: mapMarker,
          el: clusterEl,
          lng: item.center.lng,
          lat: item.center.lat,
        });
      } else {
        // --- RENDER SINGLE PIN (Issue 2: unified pill-badge system) ---
        const { marker, coords } = item.items[0];
        const color = severityColors[marker.severity] || '#64748B';
        const emoji = eventTypeEmojis[marker.eventType] || '⚠️';
        const isSelected = selectedMarker?.id === marker.id;
        const isPulsing = marker.severity === 'critical' || marker.severity === 'high' || isSelected;
        const layer = marker.layer ?? 'event';
        // Issue 1: z-index by severity rank, matching cluster approach.
        const pinSevRank = severityRank[marker.severity] || 1;

        const markerEl = document.createElement('div');
        markerEl.className = 'indra-tactical-marker select-none';
        markerEl.style.cursor = 'pointer';
        markerEl.style.zIndex = isSelected ? '22' : String(8 + pinSevRank * 2);

        const innerEl = document.createElement('div');
        innerEl.className = 'indra-marker-inner';
        innerEl.style.position = 'relative';
        innerEl.style.display = 'flex';
        innerEl.style.flexDirection = 'column';
        innerEl.style.alignItems = 'center';
        innerEl.style.transformOrigin = 'bottom center';
        innerEl.style.transition = 'transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1)';
        innerEl.style.transform = isSelected ? 'scale(1.2) translateY(-4px)' : 'scale(1) translateY(0)';
        markerEl.appendChild(innerEl);

        if (isSpaceZoom) {
          // --- Tier 1: Micro-Radar Pip for Space Orbit ---
          const pip = document.createElement('div');
          pip.className = 'indra-marker-pip';
          pip.style.backgroundColor = color;
          pip.style.borderColor = isSelected ? '#38bdf8' : '#ffffff';
          pip.style.boxShadow = isSelected
            ? '0 0 14px #38bdf8, 0 1px 4px rgba(0,0,0,0.8)'
            : `0 0 10px ${color}, 0 1px 4px rgba(0,0,0,0.8)`;
          innerEl.appendChild(pip);

          if (isPulsing) {
            const microPulse = document.createElement('div');
            microPulse.className = `pulse-ring pulse-ring-${marker.severity}`;
            microPulse.style.width = '18px';
            microPulse.style.height = '18px';
            microPulse.style.top = '-5px';
            microPulse.style.left = '50%';
            microPulse.style.transform = 'translateX(-50%)';
            microPulse.style.pointerEvents = 'none';
            innerEl.appendChild(microPulse);
          }
        } else {
          // --- Tier 2, 3, 4: Unified Pill Badge (Issue 2) ---
          // All markers use the same pill shape. Layer is indicated by a prefix
          // glyph (● event, ◆ alert, ○ report) and border style:
          //   - Events: solid border, filled background
          //   - Alerts: solid border, filled background, diamond prefix
          //   - Reports: dashed border, transparent background (unverified)
          const isReport = layer === 'report';
          const isAlert = layer === 'alert';
          const layerGlyph = isAlert ? '◆' : isReport ? '○' : '●';
          const badgeBg = isReport ? 'rgba(30,42,59,0.92)' : color;
          const badgeBorder = isSelected
            ? '1.5px solid #38bdf8'
            : isReport
              ? `1.5px dashed ${color}`
              : '1.5px solid rgba(255,255,255,0.5)';

          if (isPulsing) {
            const pulse = document.createElement('div');
            pulse.className = `pulse-ring pulse-ring-${marker.severity}`;
            pulse.style.width = '34px';
            pulse.style.height = '22px';
            pulse.style.top = '-4px';
            pulse.style.left = '50%';
            pulse.style.transform = 'translateX(-50%)';
            pulse.style.pointerEvents = 'none';
            pulse.style.borderRadius = '9999px';
            innerEl.appendChild(pulse);
          }

          const pillBadge = document.createElement('div');
          pillBadge.className = 'indra-marker-cluster';
          pillBadge.style.backgroundColor = badgeBg;
          pillBadge.style.border = badgeBorder;
          pillBadge.style.boxShadow = isSelected
            ? '0 0 16px #38bdf8, 0 4px 12px rgba(0,0,0,0.6)'
            : `0 3px 10px rgba(0,0,0,0.5), 0 0 8px ${color}60`;
          pillBadge.style.padding = isCompactZoom ? '2px 6px' : '3px 8px 3px 6px';
          pillBadge.style.fontSize = isCompactZoom ? '10px' : '11px';
          pillBadge.innerHTML = `
            <span style="font-size: 8px; opacity: 0.7; margin-right: 1px;">${layerGlyph}</span>
            <span>${emoji}</span>
          `;
          innerEl.appendChild(pillBadge);

          // City Pill (with smart collision suppression)
          // Issue 4: use word-wrap instead of truncating mid-word.
          const cityPill = document.createElement('div');
          cityPill.className = item.hideLabel ? 'indra-city-pill indra-city-pill-hidden' : 'indra-city-pill';
          cityPill.style.color = isSelected ? '#38bdf8' : '#f8fafc';
          cityPill.style.border = isSelected ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.25)';
          cityPill.style.maxWidth = '130px';
          cityPill.style.overflow = 'hidden';
          cityPill.style.textOverflow = 'ellipsis';
          cityPill.style.wordBreak = 'break-word';
          cityPill.innerText = marker.placeLabel || marker.city || 'Location unresolved';
          innerEl.appendChild(cityPill);
        }

        // Tactical Hover HUD Tooltip
        const tooltip = document.createElement('div');
        tooltip.className = 'indra-hud-popup';
        tooltip.style.position = 'absolute';
        tooltip.style.bottom = '100%';
        tooltip.style.left = '50%';
        tooltip.style.transform = 'translateX(-50%) translateY(-6px)';
        tooltip.style.opacity = '0';
        tooltip.style.pointerEvents = 'none';
        tooltip.style.zIndex = '50';
        tooltip.style.width = '220px';
        const layerLabel = layer === 'alert' ? '◆ Agency' : layer === 'report' ? '○ Report' : '● Event';
        tooltip.innerHTML = `
          <div class="hud-header">
            <span class="hud-badge hud-${marker.severity}">${marker.severity}</span>
            <span class="hud-time font-mono">${marker.timeAgo || layerLabel}</span>
          </div>
          <div class="hud-title">${emoji} ${marker.title || marker.eventType}</div>
          <div class="hud-location">📍 ${marker.placeLabel || [marker.city, marker.state].filter(Boolean).join(', ') || 'Location unresolved'}</div>
          ${marker.action ? `<div class="hud-action"><span>⚡ Action</span><span>${marker.action}</span></div>` : ''}
        `;
        innerEl.appendChild(tooltip);

        markerEl.addEventListener('mouseenter', () => {
          positionTooltip(tooltip, markerEl);
          innerEl.style.transform = 'scale(1.22) translateY(-3px)';
          tooltip.style.opacity = '1';
          markerEl.style.zIndex = '50';
        });

        markerEl.addEventListener('mouseleave', () => {
          innerEl.style.transform = isSelected ? 'scale(1.2) translateY(-4px)' : 'scale(1) translateY(0)';
          tooltip.style.opacity = '0';
          markerEl.style.zIndex = isSelected ? '25' : String(8 + pinSevRank * 2);
        });

        markerEl.addEventListener('click', (e) => {
          e.stopPropagation();
          handleSelectIncident(marker);
        });

        const mapMarker = new maplibregl.Marker({ element: markerEl, anchor: isSpaceZoom ? 'center' : 'bottom' })
          .setLngLat([coords.lng, coords.lat])
          .addTo(map);

        markersRef.current.push({
          id: marker.id,
          marker: mapMarker,
          el: markerEl,
          lng: coords.lng,
          lat: coords.lat,
        });
      }
    });

    updateMarkerOcclusion(map, isGlobeRef.current);
  }, [markersForDisplay, selectedMarker, handleSelectIncident, updateMarkerOcclusion, showEventsLayer, smartDeclutter]);

  useEffect(() => {
    renderProminentPinsRef.current = renderProminentPins;
  }, [renderProminentPins]);

  // Initialize MapLibre GL
  useEffect(() => {
    if (!mounted || !mapContainerRef.current || mapRef.current) return;

    const style = BASEMAP_STYLES[basemap];

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style,
      // Issue 5 fix: default to India-focused view (zoom 5.0 at the Indian subcontinent
      // centroid with pitch 30). This matches the view the "India" focus button produces,
      // so users no longer need to click it on every load. Zoom 5.0 keeps India centred
      // without spilling into adjacent countries the way zoom 4.6 did.
      center: [82.0, 22.0],
      zoom: 5.0,
      pitch: 30,
      bearing: 0,
      maxPitch: 85,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.jumpTo({ ...indiaCamera(map), pitch: 30 });

    // The canvas follows its container, not only the window: collapsing the
    // sidebar or a viewport-relative height change resizes the container
    // without a window resize, and MapLibre then drew a stretched frame.
    const resizeObserver =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => map.resize()) : null;
    resizeObserver?.observe(mapContainerRef.current);

    // Through the ref, never the closure. This handler is registered once, at
    // mount, and fires twice (style.load, then load). Calling the
    // renderProminentPins captured here used the empty marker list it saw at
    // mount: measured on 22 Sep, the pins effect drew 20 markers at t=1720 ms
    // and the late `load` at t=1874 ms cleared all 20 and drew none, leaving
    // the badge counting pins the map did not show (BUG-043 again).
    const onStyleReady = () => {
      try {
        map.setProjection({ type: isGlobeRef.current ? 'globe' : 'mercator' });
        renderProminentPinsRef.current();
      } catch (err) {
        console.error('[INDRA] onStyleReady error:', err);
      }
      // Announce readiness even if the block above threw, so that a failure to
      // set the projection cannot also cost us every pin on the map.
      setStyleReady(true);
    };

    if (map.isStyleLoaded()) {
      onStyleReady();
    } else {
      map.once('load', onStyleReady);
      map.once('style.load', onStyleReady);
    }

    map.on('move', () => {
      const center = map.getCenter();
      setTelemetry({
        zoom: parseFloat(map.getZoom().toFixed(2)),
        lat: parseFloat(center.lat.toFixed(2)),
        lng: parseFloat(center.lng.toFixed(2)),
        pitch: Math.round(map.getPitch()),
        bearing: Math.round(map.getBearing()),
      });
      updateMarkerOcclusion(map, isGlobeRef.current);
    });

    let lastRenderedZoom = map.getZoom();
    let zoomAnimFrame: number | null = null;

    const checkLODUpdate = () => {
      const currentZoom = map.getZoom();
      const crossedThreshold =
        (lastRenderedZoom < 2.4 && currentZoom >= 2.4) ||
        (lastRenderedZoom >= 2.4 && currentZoom < 2.4) ||
        (lastRenderedZoom < 4.2 && currentZoom >= 4.2) ||
        (lastRenderedZoom >= 4.2 && currentZoom < 4.2) ||
        (lastRenderedZoom < 6.2 && currentZoom >= 6.2) ||
        (lastRenderedZoom >= 6.2 && currentZoom < 6.2);

      if (crossedThreshold || Math.abs(currentZoom - lastRenderedZoom) > 0.3) {
        lastRenderedZoom = currentZoom;
        renderProminentPinsRef.current();
      }
    };

    map.on('zoom', () => {
      if (zoomAnimFrame) cancelAnimationFrame(zoomAnimFrame);
      zoomAnimFrame = requestAnimationFrame(checkLODUpdate);
    });

    map.on('moveend', () => {
      lastRenderedZoom = map.getZoom();
      renderProminentPinsRef.current();
    });

    mapRef.current = map;
    if (typeof window !== 'undefined') {
      (window as any).__indraMap = map;
    }

    return () => {
      resizeObserver?.disconnect();
      if (zoomAnimFrame) {
        cancelAnimationFrame(zoomAnimFrame);
      }
      if (autoOrbitAnimRef.current) {
        cancelAnimationFrame(autoOrbitAnimRef.current);
      }
      markersRef.current.forEach(({ marker }) => marker.remove());
      markersRef.current = [];
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  // Re-render pins when markers, globe mode, smart declutter, or selection changes.
  //
  // This used to read `mapRef.current.isStyleLoaded()` and bail out when it was
  // false, and nothing ever brought it back. The map's own `load` handler could
  // not cover for it either: it runs once, at which point the markers have not
  // arrived, so it drew an empty map and the real markers — which land about
  // 50 ms later, while the style still reports itself unloaded — were never
  // drawn at all. The console opened claiming "41 Incidents" and showed none of
  // them, and the pins appeared only once the operator happened to touch a
  // control, which re-ran this effect at a point where the style finally
  // admitted it was loaded.
  //
  // Depending on `styleReady` instead makes the arrival of the style a render
  // that React schedules, so whichever of the two finishes last — the style or
  // the markers — is the one that triggers the draw.
  useEffect(() => {
    if (!mapRef.current || !styleReady) return;
    renderProminentPins();
  }, [markersForDisplay, selectedMarker, smartDeclutter, renderProminentPins, styleReady]);

  // Layer visibility toggles — gated on `styleReady` for the same reason as the
  // pins above: `isStyleLoaded()` reports false for long enough after `load`
  // that a toggle flipped early would be dropped without a trace.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReady) return;

    updateMarkerOcclusion(map, isGlobeRef.current);
  }, [showEventsLayer, updateMarkerOcclusion, styleReady]);

  // Switch basemap style
  const handleBasemapChange = (newBasemap: BasemapMode) => {
    setBasemap(newBasemap);
    const map = mapRef.current;
    if (!map) return;

    map.setStyle(BASEMAP_STYLES[newBasemap]);
    map.once('style.load', () => {
      map.setProjection({ type: isGlobeRef.current ? 'globe' : 'mercator' });
      renderProminentPinsRef.current();
    });
  };

  // Toggle Globe vs Flat Mercator
  const toggleProjection = () => {
    const nextGlobe = !isGlobe;
    setIsGlobe(nextGlobe);
    isGlobeRef.current = nextGlobe;
    const map = mapRef.current;
    if (map) {
      map.setProjection({ type: nextGlobe ? 'globe' : 'mercator' });
      if (!nextGlobe && basemap === 'satellite') {
        handleBasemapChange('topo');
      } else if (nextGlobe && basemap === 'topo') {
        handleBasemapChange('satellite');
      } else {
        updateMarkerOcclusion(map, nextGlobe);
      }
    }
  };

  // Reset to True North
  const resetToNorth = () => {
    if (!mapRef.current) return;
    mapRef.current.easeTo({
      bearing: 0,
      pitch: 30,
      duration: 1000,
    });
  };

  // Planetary Auto-Orbit
  useEffect(() => {
    if (!isAutoOrbiting) {
      if (autoOrbitAnimRef.current) {
        cancelAnimationFrame(autoOrbitAnimRef.current);
        autoOrbitAnimRef.current = null;
      }
      return;
    }

    const orbitLoop = () => {
      if (mapRef.current) {
        const center = mapRef.current.getCenter();
        mapRef.current.setCenter([center.lng + 0.12, center.lat]);
      }
      autoOrbitAnimRef.current = requestAnimationFrame(orbitLoop);
    };

    autoOrbitAnimRef.current = requestAnimationFrame(orbitLoop);

    return () => {
      if (autoOrbitAnimRef.current) {
        cancelAnimationFrame(autoOrbitAnimRef.current);
      }
    };
  }, [isAutoOrbiting]);

  // Cinematic Hotspot Fly-to
  const flyToHotspot = (
    center: [number, number],
    zoom: number,
    pitch = 35,
    bearing = 0,
    duration = 2400,
    offset?: [number, number]
  ) => {
    if (!mapRef.current) return;
    mapRef.current.flyTo({
      center,
      zoom,
      pitch,
      bearing,
      essential: true,
      duration,
      ...(offset ? { offset } : {}),
    });
  };

  const focusIndia = () => {
    if (!mapRef.current) return;
    const { center, zoom } = indiaCamera(mapRef.current);
    flyToHotspot(center, zoom, 30, 0);
  };

  // Toggle Fullscreen
  const toggleFullscreen = () => {
    setIsFullscreen((prev) => {
      const next = !prev;
      setTimeout(() => {
        mapRef.current?.resize();
      }, 150);
      return next;
    });
  };

  if (!mounted) {
    return <MapCardSkeleton />;
  }

  if (!webGLSupported) {
    return (
      <Card hover={false} className="p-8 text-center border-amber-200 bg-amber-50/50">
        <div className="flex flex-col items-center justify-center gap-3">
          <AlertTriangle className="w-8 h-8 text-amber-500" />
          <h3 className="font-semibold text-slate-800">WebGL Hardware Acceleration Required</h3>
          <p className="text-xs text-slate-600 max-w-md">
            Your browser environment does not currently support WebGL rendering for 3D Earth Globe projection. Please enable hardware acceleration in your browser settings to experience planetary GIS.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className={isFullscreen ? 'fixed inset-0 z-50 p-3 sm:p-6 bg-slate-950/90 backdrop-blur-md flex flex-col' : 'relative h-full'}>
      <Card hover={false} padding={false} className={`overflow-hidden border border-slate-200/80 shadow-card flex flex-col indra-map-isolated isolate relative z-0 h-full ${isFullscreen ? 'flex-1' : ''}`}>
        {/* Compact Single-Line Header Bar */}
        <div className="flex items-center justify-between gap-2 px-3.5 py-2 border-b border-slate-200/80 bg-[#FDFAF5]">
          {/* Left: Live dot + Title + Incident chip */}
          <div className="flex items-center gap-2 min-w-0">
            <span className="flex-shrink-0 h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-sm font-semibold text-slate-800 truncate">
              {variant === 'preview' ? 'Tactical Geospatial Grid' : '3D Weather Intelligence Grid'}
            </span>
            {/* Issue 8: clarify this is a severity filter, not a total count */}
            {markersForDisplay.filter(m => m.severity === 'critical' || m.severity === 'high').length > 0 && (
              <span className="flex-shrink-0 flex items-center gap-1 text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 px-1.5 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping inline-block" />
                {markersForDisplay.filter(m => m.severity === 'critical' || m.severity === 'high').length} urgent
              </span>
            )}
          </div>

          {/* Right: compact controls */}
          <div className="flex items-center gap-1 flex-shrink-0">
            {/* Globe / 2D toggle */}
            <button
              onClick={toggleProjection}
              className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border font-medium transition-all ${
                isGlobe
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
              }`}
              title="Toggle 3D Globe / 2D Flat Map"
            >
              {isGlobe ? <Globe className="w-3 h-3" /> : <MapIcon className="w-3 h-3" />}
              <span className="hidden sm:inline">{isGlobe ? '3D Globe' : '2D Flat'}</span>
            </button>

            {/* Quick jump: India Focus */}
            <button
              onClick={focusIndia}
              className="hidden lg:flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border bg-white border-slate-200 hover:bg-slate-50 text-slate-700 font-medium transition-all"
              title="Focus on Indian Subcontinent"
            >
              <span>🇮🇳</span>
              <span>India</span>
            </button>

            {/* Quick jump: Global View. On the dashboard's narrower card it
                gives way below 2xl so the map's title is not truncated. */}
            <button
              onClick={() => flyToHotspot([80.0, 15.0], 1.6, 0, 0, 3000)}
              className={`hidden ${variant === 'preview' ? '2xl:flex' : 'lg:flex'} items-center gap-1 text-[11px] px-2 py-1 rounded-md border bg-white border-slate-200 hover:bg-slate-50 text-slate-700 font-medium transition-all`}
              title="Zoom out to Global View"
            >
              <Globe className="w-3 h-3 text-indigo-500" />
              <span>Global</span>
            </button>

            {/* Auto-orbit toggle */}
            <button
              onClick={() => setIsAutoOrbiting(!isAutoOrbiting)}
              className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border font-medium transition-all ${
                isAutoOrbiting
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
              title="Toggle Auto-Orbit"
            >
              {isAutoOrbiting ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
              <span className="hidden sm:inline">Orbit</span>
            </button>

            {/* North reset */}
            <button
              onClick={resetToNorth}
              className="p-1 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-primary hover:bg-slate-50"
              title="Reset to True North"
            >
              <Navigation className="w-3 h-3 transform -rotate-45" />
            </button>

            {/* Open full map link (preview mode) OR fullscreen (full mode) */}
            {variant === 'preview' ? (
              <Link
                href="/live-map"
                className="flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-primary hover:bg-primary-hover text-white transition-all"
                title="Open Live Tactical Map"
              >
                <span className="hidden sm:inline">Live Map</span>
                <ChevronRight className="w-3 h-3" />
              </Link>
            ) : (
              <button
                onClick={toggleFullscreen}
                className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-colors"
                title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              >
                {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
              </button>
            )}
          </div>
        </div>

        {/* Controls Ribbon — condensed into header above, kept only for full variant */}
        {variant !== 'preview' && (
        <div className="flex items-center justify-between gap-2 px-4 py-1.5 bg-slate-50/95 border-b border-slate-100 overflow-x-auto text-xs scrollbar-none">
          {/* Left: View Controls & Dynamic Active Incidents */}
          <div className="flex items-center gap-2.5 shrink-0">
            {/* Group 1: View Scope */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1 shrink-0">
                <Compass className="w-3 h-3 text-primary" /> View:
              </span>
              <button
                onClick={focusIndia}
                className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1 text-[11px]"
                title="Focus view on Indian subcontinent"
              >
                <span>🇮🇳</span> India Focus
              </button>
              <button
                onClick={() => flyToHotspot([80.0, 15.0], 1.6, 0, 0, 3000)}
                className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1 text-[11px]"
                title="Zoom out to Global Earth view"
              >
                <Globe className="w-3 h-3 text-indigo-500" /> Global View
              </button>
            </div>

            {/* Group 2: Jump to Active Event (Dynamically extracted from live alerts) */}
            <div className="flex items-center gap-1.5 shrink-0 pl-2.5 border-l border-slate-200">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1 shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping" />
                Active Incidents:
              </span>
              {markersForDisplay
                .filter((m) => m.severity === 'critical' || m.severity === 'high')
                .slice(0, 3)
                .map((marker) => {
                  const isSelected = selectedEventId === marker.id;
                  return (
                    <button
                      key={marker.id}
                      onClick={() => {
                        handleSelectIncident(marker);
                      }}
                      className={cn(
                        'px-2.5 py-1 rounded-md border text-[11px] font-medium shrink-0 transition-all flex items-center gap-1.5',
                        isSelected
                          ? 'bg-rose-50 border-rose-300 text-rose-800 font-semibold shadow-xs'
                          : marker.severity === 'critical'
                          ? 'bg-white border-rose-200 hover:border-rose-400 hover:bg-rose-50/50 text-slate-700'
                          : 'bg-white border-amber-200 hover:border-amber-400 hover:bg-amber-50/50 text-slate-700'
                      )}
                      title={`Jump to ${marker.title || marker.city} (${marker.city}, ${marker.state})`}
                    >
                      <span>{eventTypeEmojis[marker.eventType] || '⚠️'}</span>
                      <span className="truncate max-w-[120px]">{(marker.title || marker.city).split('—')[0].trim()}</span>
                    </button>
                  );
                })}
            </div>
          </div>

          {/* Right: Layer & Navigation Toggles */}
          <div className="flex items-center gap-1.5 shrink-0 pl-2 border-l border-slate-200">
            <button
              onClick={() => setShowEventsLayer(!showEventsLayer)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                showEventsLayer
                  ? 'bg-rose-50 text-rose-700 border-rose-200 font-semibold'
                  : 'bg-white text-slate-400 border-slate-200'
              }`}
              title="Toggle all map pins on/off"
            >
              <AlertTriangle className="w-3 h-3" />
              {/* Issue 8: label matches what this actually controls */}
              <span>All pins ({markersForDisplay.length})</span>
            </button>

            {/*
              The three live data layers. Each count is what is actually in the
              database, and each layer draws a different shape, so a raw citizen
              report can never be mistaken for a scored event.
            */}
            {LAYER_CHIPS.map((chip) => {
              const count = markers.filter(
                (m) => (m.layer ?? 'event') === chip.layer
              ).length;
              const on = visibleLayers[chip.layer];
              return (
                <button
                  key={chip.layer}
                  onClick={() =>
                    setVisibleLayers((prev) => ({ ...prev, [chip.layer]: !prev[chip.layer] }))
                  }
                  className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                    on
                      ? `${chip.onClass} font-semibold`
                      : 'bg-white text-slate-400 border-slate-200'
                  }`}
                  title={chip.title}
                  aria-pressed={on}
                >
                  <span aria-hidden>{chip.glyph}</span>
                  <span>
                    {chip.label} ({count})
                  </span>
                </button>
              );
            })}
            {/* Smart Declutter & Collision Avoidance Toggle */}
            <button
              onClick={() => setSmartDeclutter(!smartDeclutter)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                smartDeclutter
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold shadow-xs'
                  : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'
              }`}
              title="Toggle intelligent marker collision avoidance and spatial clustering"
            >
              <Layers className="w-3 h-3 text-emerald-600" />
              <span>Smart Pins: {smartDeclutter ? 'ON' : 'OFF'}</span>
            </button>

            {/* Auto-Orbit Button */}
            <button
              onClick={() => setIsAutoOrbiting(!isAutoOrbiting)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                isAutoOrbiting
                  ? 'bg-indigo-600 text-white border-indigo-600 font-semibold shadow-xs'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
              title="Toggle continuous planetary rotation"
            >
              {isAutoOrbiting ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
              <span>Auto-Orbit</span>
            </button>

            {/* Snap to North Button */}
            <button
              onClick={resetToNorth}
              className="p-1 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-primary hover:bg-slate-50"
              title="Reset view to True North"
            >
              <Navigation className="w-3.5 h-3.5 transform -rotate-45" />
            </button>
          </div>
        </div>
        )} {/* end variant !== 'preview' controls ribbon */}

        {/* Map Canvas & Overlays */}
        <div
          className={cn(
            'relative w-full overflow-hidden globe-space-bg',
            isFullscreen
              ? 'flex-1 min-h-[520px]'
              : canvasClassName
              ? canvasClassName
              : variant === 'preview'
              ? 'h-[360px]'
              : 'h-[500px] lg:h-[560px]'
          )}
        >
          <div ref={mapContainerRef} className="w-full h-full" />

          {/* Tactical Incident Inspector Drawer (Slides in upon selection) */}
          <AnimatePresence>
            {selectedMarker && (
              <motion.div
                initial={{ opacity: 0, x: -20, scale: 0.95 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: -20, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                className="absolute top-3 left-3 z-40 w-80 max-w-[calc(100%-24px)] max-h-[calc(100%-54px)] overflow-y-auto custom-scrollbar bg-slate-900/98 text-white backdrop-blur-2xl rounded-2xl shadow-2xl border border-slate-700/80 p-3.5 space-y-2.5"
              >
                {/* Header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider shrink-0"
                      style={{
                        backgroundColor: severityConfig[selectedMarker.severity]?.bg || '#f1f5f9',
                        color: severityConfig[selectedMarker.severity]?.textColor || '#334155',
                      }}
                    >
                      {severityConfig[selectedMarker.severity]?.label || selectedMarker.severity}
                    </span>
                    <span className="text-[10px] text-slate-300 font-mono flex items-center gap-1 truncate">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                      <span className="truncate">{markerStatusLabel(selectedMarker)}</span>
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedMarker(null);
                      if (onEventSelect) onEventSelect(null);
                    }}
                    className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shrink-0"
                    title="Close incident inspector"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* City & Event Title */}
                <div>
                  <h4 className="text-sm font-bold text-white tracking-tight flex items-center gap-1.5 leading-snug">
                    <span>{eventTypeEmojis[selectedMarker.eventType] || '⚠️'}</span>
                    <span className="truncate">{selectedMarker.placeLabel || selectedMarker.city || 'Location unresolved'}</span>
                  </h4>
                  <p className="text-[11px] font-semibold text-blue-400 mt-0.5 flex items-center gap-1">
                    <Target className="w-3 h-3 shrink-0" />
                    <span className="truncate">{selectedMarker.eventType}</span>
                  </p>
                </div>

                <p className="text-[11px] text-slate-300 line-clamp-2 leading-relaxed">
                  {selectedMarker.description}
                </p>

                {/* Source & Coordinates */}
                <div className="grid grid-cols-2 gap-1.5 pt-2 border-t border-slate-800 text-[10px]">
                  <div className="bg-slate-800/80 p-1.5 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[9px]">
                      <Layers className="w-3 h-3 text-blue-400" /> Source
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5 truncate">
                      {markerSourceLabel(selectedMarker)}
                    </div>
                  </div>
                  <div className="bg-slate-800/80 p-1.5 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[9px]">
                      <Activity className="w-3 h-3 text-emerald-400" /> Coordinates
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5 truncate">
                      {selectedMarker.lat.toFixed(2)}°N, {selectedMarker.lng.toFixed(2)}°E
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 pt-1">
                  {(selectedMarker.layer ?? 'event') === 'event' && (
                    <button
                      onClick={() => (window.location.href = '/teams')}
                      className="flex-1 py-1 px-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold text-xs transition-colors flex items-center justify-center gap-1.5 shadow-md"
                    >
                      <Shield className="w-3 h-3" />
                      <span>Dispatch Team</span>
                    </button>
                  )}
                  <button
                    onClick={() => flyToHotspot([selectedMarker.lng, selectedMarker.lat], 8.2, 55, 20, 2400, [90, 0])}
                    className="py-1 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors flex items-center gap-1"
                    title="Zoom in to tactical street level"
                  >
                    <Maximize2 className="w-3 h-3" />
                    <span>Zoom In</span>
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Collapsible Incident Roster HUD (Positioned to the left of MapLibre zoom controls) */}
          <div className="absolute top-3 right-14 z-30 flex flex-col items-end">
            {!isRosterOpen ? (
              <button
                onClick={() => setIsRosterOpen(true)}
                className="flex items-center gap-2 bg-slate-900/90 hover:bg-slate-900 text-white backdrop-blur-xl px-3 py-1.5 rounded-xl border border-slate-700/80 shadow-xl text-xs transition-all hover:scale-105 active:scale-95 group"
                title="Open Live Incidents Roster"
              >
                <span className="flex h-2 w-2 rounded-full bg-rose-500 animate-ping" />
                {/* Issue 8: clarify this is total map pins, not a filtered count */}
                <span className="font-semibold">{markersForDisplay.length} map pins</span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400 group-hover:text-white" />
              </button>
            ) : (
              <motion.div
                initial={{ opacity: 0, y: -8, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -8, scale: 0.95 }}
                className="w-72 max-h-[360px] bg-slate-900/95 text-white backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/80 p-3 flex flex-col"
              >
                <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-slate-800">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                    <Radio className="w-3 h-3 text-rose-400 animate-pulse" />
                    Live Incident Roster
                  </span>
                  <div className="flex items-center gap-1">
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                      {markersForDisplay.length} PINS
                    </span>
                    <button
                      onClick={() => setIsRosterOpen(false)}
                      className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
                      title="Collapse Roster"
                    >
                      <ChevronUp className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5 overflow-y-auto custom-scrollbar pr-1 flex-1">
                  {markersForDisplay.map((marker) => {
                    const isSelected = selectedMarker?.id === marker.id;
                    const color = severityColors[marker.severity] || '#64748B';
                    const emoji = eventTypeEmojis[marker.eventType] || '⚠️';
                    const layerGlyph = marker.layer === 'alert' ? '◆' : marker.layer === 'report' ? '○' : '●';

                    return (
                      <button
                        key={marker.id}
                        onClick={() => handleSelectIncident(marker)}
                        className={`w-full text-left p-2 rounded-xl border transition-all flex items-center justify-between group ${
                          isSelected
                            ? 'bg-blue-600/30 border-blue-400 shadow-sm'
                            : 'bg-slate-800/60 hover:bg-slate-800 border-slate-700/60'
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm">{emoji}</span>
                          <div className="truncate">
                            <div className="text-xs font-semibold text-white group-hover:text-blue-300 truncate">
                              <span className="text-[9px] opacity-60 mr-1">{layerGlyph}</span>
                              {marker.city}, {marker.state}
                            </div>
                            <div className="text-[10px] text-slate-400 truncate">
                              {marker.eventType}
                            </div>
                          </div>
                        </div>
                        <div
                          className="w-2 h-2 rounded-full shrink-0 ml-1.5"
                          style={{ backgroundColor: color }}
                        />
                      </button>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </div>

          {/* Issue 3: Cluster detail popover — rendered in React to avoid DOM duplication issues */}
          <AnimatePresence>
            {clusterPopover && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.15 }}
                className="absolute z-40"
                style={{ left: clusterPopover.position.x, top: clusterPopover.position.y }}
              >
                <div className="w-72 bg-slate-900/97 text-white backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/80 p-4">
                  {/* Close + header */}
                  <div className="flex items-center justify-between mb-2">
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider"
                      style={{
                        backgroundColor: severityColors[clusterPopover.maxSeverity] || '#64748B',
                        color: '#fff',
                      }}
                    >
                      {clusterPopover.maxSeverity} cluster
                    </span>
                    <button
                      onClick={() => setClusterPopover(null)}
                      className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Severity breakdown */}
                  {(() => {
                    const sevB: Record<string, number> = {};
                    clusterPopover.items.forEach(m => {
                      sevB[m.severity] = (sevB[m.severity] || 0) + 1;
                    });
                    return (
                      <div className="text-[10px] text-slate-400 mb-2 flex flex-wrap gap-1.5">
                        {Object.entries(sevB)
                          .sort(([, a], [, b]) => b - a)
                          .map(([s, n]) => (
                            <span
                              key={s}
                              className="px-1.5 py-0.5 rounded border"
                              style={{
                                borderColor: severityColors[s] || '#64748B',
                                color: severityColors[s] || '#64748B',
                              }}
                            >
                              {n} {s}
                            </span>
                          ))}
                      </div>
                    );
                  })()}

                  {/* Deduplicated incident list */}
                  {/* Issue 3: If items share (city, eventType, severity), group them to
                      avoid repeated identical rows. If no distinguishing data exists
                      beyond these three fields, show an honest summary rather than
                      fabricating detail. A future backend field (e.g. incident_ids[]
                      per cluster) would allow truly itemized detail here. */}
                  <div className="space-y-1.5 max-h-[200px] overflow-y-auto custom-scrollbar">
                    {(() => {
                      const groups: Record<string, { city: string; eventType: string; severity: string; count: number; emoji: string; descriptions: string[] }> = {};
                      clusterPopover.items.forEach(m => {
                        const key = `${m.city}|${m.eventType}|${m.severity}`;
                        if (!groups[key]) {
                          groups[key] = {
                            city: m.city,
                            eventType: m.eventType,
                            severity: m.severity,
                            count: 0,
                            emoji: eventTypeEmojis[m.eventType] || '⚠️',
                            descriptions: [],
                          };
                        }
                        groups[key].count++;
                        if (m.description && !groups[key].descriptions.includes(m.description)) {
                          groups[key].descriptions.push(m.description);
                        }
                      });
                      return Object.values(groups).map((g, i) => (
                        <div
                          key={i}
                          className="p-2 rounded-lg bg-slate-800/70 border border-slate-700/50"
                        >
                          <div className="text-xs font-semibold text-white flex items-center gap-1.5">
                            <span>{g.emoji}</span>
                            <span>{g.city || 'Unknown'}</span>
                            {g.count > 1 && (
                              <span className="text-[10px] font-mono text-slate-400">×{g.count}</span>
                            )}
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5">
                            {g.eventType} · <span style={{ color: severityColors[g.severity] || '#64748B' }}>{g.severity}</span>
                          </div>
                          {g.descriptions.length > 1 && (
                            <div className="text-[10px] text-slate-500 mt-1 line-clamp-2">
                              {g.descriptions[0]}
                            </div>
                          )}
                        </div>
                      ));
                    })()}
                  </div>

                  {/* Link to events page */}
                  <Link
                    href="/events"
                    className="mt-3 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors"
                  >
                    View all in Incident Events
                    <ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Click outside map to dismiss cluster popover */}
          {clusterPopover && (
            <div
              className="absolute inset-0 z-[38]"
              onClick={() => setClusterPopover(null)}
              onKeyDown={(e) => { if (e.key === 'Escape') setClusterPopover(null); }}
              tabIndex={-1}
              role="presentation"
            />
          )}

          {/* Click outside map to dismiss legend */}
          {legendOpen && (
            <div
              className="absolute inset-0 z-[38]"
              onClick={() => setLegendOpen(false)}
              role="presentation"
            />
          )}

          {/* Interactive Map Layers & Legend control panel — positioned cleanly above dock */}
          <AnimatePresence>
            {legendOpen && (
              <motion.div
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.95 }}
                transition={{ duration: 0.16, ease: 'easeOut' }}
                className="absolute bottom-12 left-3 z-40 w-72 sm:w-80 max-h-[calc(100%-60px)] overflow-y-auto custom-scrollbar bg-slate-900/98 text-white backdrop-blur-2xl rounded-2xl shadow-2xl border border-slate-700/80 p-3.5 space-y-3"
              >
                {/* Header */}
                <div className="flex items-center justify-between pb-2.5 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <div className="p-1 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                      <Layers className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-100">Layers & Legend</span>
                        {isAnyFilterActive && (
                          <span className="px-1.5 py-0.2 text-[8px] font-mono font-bold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded-full">
                            Filtered
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-400 font-mono">
                        Showing {markersForDisplay.length} of {markers.length} pins
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {isAnyFilterActive && (
                      <button
                        onClick={resetAllFilters}
                        className="flex items-center gap-1 px-1.5 py-1 text-[10px] font-medium text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 rounded-md transition-colors"
                        title="Reset all filters to show everything"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Reset</span>
                      </button>
                    )}
                    <button
                      onClick={() => setLegendOpen(false)}
                      className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                      title="Close panel (Esc)"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Section 1: Data Layers */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
                      Data Layers
                    </span>
                    <span className="text-[9px] font-mono text-slate-500">Toggle layers</span>
                  </div>
                  <div className="space-y-1">
                    {[
                      { layer: 'event' as MapLayer, label: 'Fused Incident', glyph: '●', color: 'text-white', desc: 'AI-fused multi-source' },
                      { layer: 'alert' as MapLayer, label: 'Agency Warning', glyph: '◆', color: 'text-amber-400', desc: 'Official IMD / NDMA' },
                      { layer: 'report' as MapLayer, label: 'Citizen Report', glyph: '○', color: 'text-blue-400', desc: 'Unverified field reports' },
                    ].map((layerItem) => {
                      const active = visibleLayers[layerItem.layer];
                      const count = filterCounts.layers[layerItem.layer] || 0;
                      return (
                        <button
                          key={layerItem.layer}
                          onClick={() =>
                            setVisibleLayers((prev) => ({ ...prev, [layerItem.layer]: !prev[layerItem.layer] }))
                          }
                          className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg border text-left text-[11px] transition-all ${
                            active
                              ? 'bg-slate-800/80 border-slate-700 text-slate-200 shadow-xs'
                              : 'bg-slate-900/40 border-slate-800/60 text-slate-500 hover:bg-slate-800/40 opacity-60'
                          }`}
                          title={`Click to toggle ${layerItem.label}`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`text-xs font-bold ${layerItem.color}`}>{layerItem.glyph}</span>
                            <div className="min-w-0">
                              <span className={`font-medium ${active ? 'text-slate-200' : 'text-slate-500 line-through'}`}>
                                {layerItem.label}
                              </span>
                              <span className="block text-[9px] text-slate-500 font-normal truncate">
                                {layerItem.desc}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0 pl-2">
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-950/60 text-slate-300 border border-slate-800">
                              {count}
                            </span>
                            <div
                              className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-all ${
                                active
                                  ? 'bg-blue-600 border-blue-500 text-white'
                                  : 'border-slate-700 bg-slate-800/50 text-transparent'
                              }`}
                            >
                              <Check className="w-2.5 h-2.5 stroke-[3]" />
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Section 2: Severity Hierarchy */}
                <div className="pt-2 border-t border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
                      Severity Hierarchy
                    </span>
                    <div className="flex items-center gap-1 text-[9px] font-mono">
                      <button
                        onClick={() =>
                          setVisibleSeverities({
                            critical: true,
                            high: true,
                            moderate: true,
                            advisory: true,
                            low: true,
                          })
                        }
                        className="text-slate-400 hover:text-slate-200 px-1 py-0.5 rounded hover:bg-slate-800 transition-colors"
                        title="Show all severity levels"
                      >
                        All
                      </button>
                      <span className="text-slate-600">|</span>
                      <button
                        onClick={() =>
                          setVisibleSeverities({
                            critical: true,
                            high: true,
                            moderate: false,
                            advisory: false,
                            low: false,
                          })
                        }
                        className="text-rose-400 hover:text-rose-300 px-1 py-0.5 rounded hover:bg-rose-950/40 transition-colors"
                        title="Show only Critical and High incidents"
                      >
                        Urgent only
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {[
                      { key: 'critical', label: 'Critical', color: '#EF4444', ring: 'border-red-500/50 hover:border-red-500/80' },
                      { key: 'high', label: 'High', color: '#F59E0B', ring: 'border-amber-500/50 hover:border-amber-500/80' },
                      { key: 'moderate', label: 'Moderate', color: '#3B82F6', ring: 'border-blue-500/50 hover:border-blue-500/80' },
                      { key: 'advisory', label: 'Advisory', color: '#7A8599', ring: 'border-slate-400/40 hover:border-slate-400/70' },
                      { key: 'low', label: 'Low', color: '#64748B', ring: 'border-slate-600/40 hover:border-slate-600/70' },
                    ].map((s) => {
                      const active = visibleSeverities[s.key] !== false;
                      const count = filterCounts.severities[s.key] || 0;
                      return (
                        <button
                          key={s.key}
                          onClick={() =>
                            setVisibleSeverities((prev) => ({
                              ...prev,
                              [s.key]: prev[s.key] === false ? true : false,
                            }))
                          }
                          className={`flex items-center justify-between px-2 py-1.5 rounded-lg border text-[11px] transition-all ${
                            active
                              ? `bg-slate-800/80 ${s.ring} text-slate-200 shadow-xs`
                              : 'bg-slate-900/30 border-slate-800/60 text-slate-500 opacity-45'
                          }`}
                          title={`Toggle ${s.label} severity`}
                        >
                          <div className="flex items-center gap-1.5 min-w-0">
                            <div
                              className={`w-2 h-2 rounded-full shrink-0 transition-transform ${
                                active ? 'scale-100 shadow-sm' : 'scale-75 opacity-40'
                              }`}
                              style={{ backgroundColor: s.color }}
                            />
                            <span className={`font-medium truncate ${active ? 'text-slate-200' : 'text-slate-500 line-through'}`}>
                              {s.label}
                            </span>
                          </div>
                          <span className="text-[9px] font-mono text-slate-400 bg-slate-950/60 px-1 rounded border border-slate-800/80">
                            {count}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Section 3: Hazard Types */}
                <div className="pt-2 border-t border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
                      Hazard Types
                    </span>
                    {hiddenHazards.size > 0 && (
                      <button
                        onClick={() => setHiddenHazards(new Set())}
                        className="text-[9px] font-mono text-blue-400 hover:text-blue-300 px-1 py-0.5 rounded hover:bg-blue-950/40 transition-colors"
                      >
                        Show all ({hiddenHazards.size} hidden)
                      </button>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(availableHazards.length > 0
                      ? availableHazards
                      : Object.keys(eventTypeEmojis)
                    ).map((hazard) => {
                      const isHidden = hiddenHazards.has(hazard);
                      const emoji = eventTypeEmojis[hazard] || '⚠️';
                      const count = filterCounts.hazards[hazard] ?? 0;
                      const cleanName = hazard.replace('Severe ', '').replace('Heavy ', '');
                      return (
                        <button
                          key={hazard}
                          onClick={() => {
                            setHiddenHazards((prev) => {
                              const next = new Set(prev);
                              if (next.has(hazard)) {
                                next.delete(hazard);
                              } else {
                                next.add(hazard);
                              }
                              return next;
                            });
                          }}
                          className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition-all ${
                            !isHidden
                              ? 'bg-slate-800/80 border-slate-700 text-slate-200 hover:bg-slate-700/80 shadow-xs'
                              : 'bg-slate-900/30 border-slate-800/50 text-slate-500 opacity-45 line-through'
                          }`}
                          title={`${hazard} (${count} pins) — click to ${isHidden ? 'show' : 'hide'}`}
                        >
                          <span className="text-xs">{emoji}</span>
                          <span className="font-medium truncate max-w-[80px]">{cleanName}</span>
                          {count > 0 && (
                            <span className="text-[8px] font-mono bg-slate-950/70 text-slate-400 px-1 rounded">
                              {count}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Footer summary */}
                <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        isAnyFilterActive ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'
                      }`}
                    />
                    <span className="font-mono">
                      {isAnyFilterActive
                        ? `${markersForDisplay.length}/${markers.length} pins active`
                        : `All ${markers.length} items visible`}
                    </span>
                  </div>
                  {isAnyFilterActive && (
                    <button
                      onClick={resetAllFilters}
                      className="text-amber-400 hover:text-amber-300 font-medium hover:underline text-[10px]"
                    >
                      Reset all
                    </button>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Issue 5: Technical readout — telemetry HUD and horizon status banner */}
          {showTechReadout && (
            <div className="absolute bottom-3 sm:left-[215px] z-10 pointer-events-none hidden sm:flex items-center gap-2 bg-slate-950/85 text-white backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-800/80 text-[11px] font-mono shadow-lg">
              <span className="flex items-center gap-1 text-emerald-400 font-bold">
                <Radio className="w-3 h-3 animate-pulse" />
                {isGlobe ? 'GLOBE: WGS-84' : 'FLAT: 2D SURVEY'}
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-300">
                ZOOM <strong className="text-white">{telemetry.zoom}</strong>
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-300">
                {telemetry.lat >= 0 ? `${telemetry.lat}°N` : `${Math.abs(telemetry.lat)}°S`},{' '}
                {telemetry.lng >= 0 ? `${telemetry.lng}°E` : `${Math.abs(telemetry.lng)}°W`}
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-300">
                PITCH <strong className="text-white">{telemetry.pitch}°</strong>
              </span>
              {isAutoOrbiting && (
                <>
                  <span className="text-slate-600">|</span>
                  <span className="text-indigo-400 animate-pulse font-semibold">ORBIT: 0.12°/F</span>
                </>
              )}
              <span className="text-slate-600">|</span>
              <span className="text-slate-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>Horizon Occlusion</span>
              </span>
            </div>
          )}

          {/* Bottom-Left Tactical Control Dock */}
          <div className="absolute bottom-3 left-3 z-30 flex items-center gap-1.5">
            {/* Tech Readout Toggle */}
            <button
              onClick={() => setShowTechReadout(!showTechReadout)}
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[10px] font-mono font-medium backdrop-blur-xl shadow-lg transition-all ${
                showTechReadout
                  ? 'bg-emerald-950/90 text-emerald-300 border-emerald-600/60 shadow-[0_0_8px_rgba(16,185,129,0.3)]'
                  : 'bg-slate-900/90 text-slate-400 border-slate-700/80 hover:text-white hover:bg-slate-900'
              }`}
              title={showTechReadout ? 'Hide technical telemetry readout' : 'Show technical telemetry readout'}
            >
              <Terminal className="w-3 h-3 text-emerald-400" />
              <span className="hidden sm:inline">Tech</span>
            </button>

            {/* Map Layers & Legend Toggle */}
            <button
              onClick={() => {
                const next = !legendOpen;
                setLegendOpen(next);
                if (next) {
                  setSelectedMarker(null);
                  setClusterPopover(null);
                }
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-medium backdrop-blur-xl shadow-lg transition-all ${
                legendOpen
                  ? 'bg-blue-600 text-white border-blue-400 shadow-[0_0_10px_rgba(37,99,235,0.4)]'
                  : isAnyFilterActive
                  ? 'bg-slate-900/95 text-amber-300 border-amber-500/60 shadow-[0_0_8px_rgba(245,158,11,0.25)]'
                  : 'bg-slate-900/90 text-slate-300 border-slate-700/80 hover:text-white hover:bg-slate-900'
              }`}
              title={
                legendOpen
                  ? 'Close layers & filters panel (Esc)'
                  : isAnyFilterActive
                  ? 'Filters active — click to edit layers & legend'
                  : 'Open map layers, severity & hazard controls'
              }
            >
              <Layers
                className={`w-3.5 h-3.5 ${
                  legendOpen ? 'text-white' : isAnyFilterActive ? 'text-amber-400' : 'text-blue-400'
                }`}
              />
              <span>Layers & Legend</span>
              {isAnyFilterActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              )}
              {legendOpen ? (
                <ChevronUp className="w-3 h-3 opacity-80" />
              ) : (
                <ChevronDown className="w-3 h-3 opacity-60" />
              )}
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}
