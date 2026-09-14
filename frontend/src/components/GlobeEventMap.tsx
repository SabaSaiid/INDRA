'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Card, CardHeader } from '@/components/ui/card';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { mapMarkers, severityConfig, type MapMarker } from '@/lib/mock-data';
import { fetchEvents, apiEventsToMapMarkers } from '@/lib/api';
import {
  Globe,
  Map as MapIcon,
  Maximize2,
  Minimize2,
  Compass,
  Layers,
  CloudRain,
  Waves,
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
  ExternalLink,
  ChevronRight,
  Activity,
  CheckCircle2,
  Play,
  Pause,
} from 'lucide-react';

export type BasemapMode = 'satellite' | 'dark' | 'street';

// Basemap Styles with Globe Projection & Atmospheric Sky
const BASEMAP_STYLES: Record<BasemapMode, any> = {
  satellite: {
    version: 8,
    projection: { type: 'globe' },
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
  dark: {
    version: 8,
    projection: { type: 'globe' },
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
  low: '#64748B',
};

// Bay of Bengal Cyclone Track Coordinates
const cycloneTrackGeoJSON: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { name: 'Cyclone DANA — Forecast Track' },
      geometry: {
        type: 'LineString',
        coordinates: [
          [92.5, 11.2],
          [90.4, 13.8],
          [88.6, 16.2],
          [87.1, 18.5],
          [86.2, 20.4],
          [85.8, 21.8],
        ],
      },
    },
  ],
};

// NDRF Operational Bases across India
const ndrfBasesGeoJSON: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { name: '10th Bn NDRF (Patna)', city: 'Patna' }, geometry: { type: 'Point', coordinates: [85.05, 25.65] } },
    { type: 'Feature', properties: { name: '1st Bn NDRF (Guwahati)', city: 'Guwahati' }, geometry: { type: 'Point', coordinates: [91.68, 26.12] } },
    { type: 'Feature', properties: { name: '5th Bn NDRF (Pune)', city: 'Pune' }, geometry: { type: 'Point', coordinates: [73.85, 18.52] } },
    { type: 'Feature', properties: { name: '8th Bn NDRF (Ghaziabad)', city: 'Ghaziabad' }, geometry: { type: 'Point', coordinates: [77.45, 28.67] } },
    { type: 'Feature', properties: { name: '4th Bn NDRF (Arakkonam)', city: 'Chennai Region' }, geometry: { type: 'Point', coordinates: [79.67, 13.08] } },
    { type: 'Feature', properties: { name: '2nd Bn NDRF (Kolkata)', city: 'Kolkata' }, geometry: { type: 'Point', coordinates: [88.42, 22.58] } },
  ],
};

function buildEventsGeoJSON(markersList: MapMarker[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: markersList.map((m) => ({
      type: 'Feature',
      id: m.id,
      geometry: {
        type: 'Point',
        coordinates: [m.lng, m.lat],
      },
      properties: {
        id: m.id,
        city: m.city,
        state: m.state,
        eventType: m.eventType,
        severity: m.severity,
        verification: m.verification,
        description: m.description,
        color: severityColors[m.severity] || '#64748B',
        // Simulated sensor metrics for tactical telemetry
        rainfall: m.severity === 'critical' ? '86 mm/h' : m.severity === 'high' ? '54 mm/h' : '22 mm/h',
        wind: m.severity === 'critical' ? '68 km/h' : m.severity === 'high' ? '45 km/h' : '18 km/h',
        waterLevel: m.severity === 'critical' ? '+1.9m Danger' : m.severity === 'high' ? '+0.8m Alert' : 'Normal',
        populationAtRisk: m.severity === 'critical' ? '820,000' : m.severity === 'high' ? '340,000' : '95,000',
      },
    })),
  };
}

export default function GlobeEventMap({
  selectedEventId,
  onEventSelect,
}: {
  selectedEventId?: string;
  onEventSelect?: (marker: MapMarker | null) => void;
}) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const autoOrbitAnimRef = useRef<number | null>(null);

  const [mounted, setMounted] = useState(false);
  const [webGLSupported, setWebGLSupported] = useState(true);
  const [isGlobe, setIsGlobe] = useState(true);
  const [basemap, setBasemap] = useState<BasemapMode>('satellite');
  const [timeRange, setTimeRange] = useState('24h');
  const [markers, setMarkers] = useState<MapMarker[]>(mapMarkers);
  const [selectedMarker, setSelectedMarker] = useState<MapMarker | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isAutoOrbiting, setIsAutoOrbiting] = useState(false);

  // Layer toggles
  const [showEventsLayer, setShowEventsLayer] = useState(true);
  const [showCycloneLayer, setShowCycloneLayer] = useState(true);
  const [showNdrfLayer, setShowNdrfLayer] = useState(true);

  // Live telemetry state
  const [telemetry, setTelemetry] = useState({
    zoom: 4.6,
    lat: 22.0,
    lng: 82.0,
    pitch: 30,
    bearing: 0,
  });

  useEffect(() => {
    setMounted(true);
    if (typeof window !== 'undefined' && typeof (maplibregl as any).supported === 'function' && !(maplibregl as any).supported()) {
      setWebGLSupported(false);
    }
  }, []);

  // Fetch live events
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const events = await fetchEvents({ time_range: timeRange });
        if (!cancelled && events.length > 0) {
          const formatted = apiEventsToMapMarkers(events);
          setMarkers(formatted);
        }
      } catch {
        // mock fallback
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [timeRange]);

  // Sync external selectedEventId if passed from dashboard
  useEffect(() => {
    if (selectedEventId) {
      const match = markers.find((m) => m.id === selectedEventId);
      if (match) {
        handleSelectIncident(match);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEventId, markers]);

  // Build and sync native WebGL GeoJSON layers (100% Depth & Horizon Culled)
  const syncWebGLLayers = useCallback(
    (map: maplibregl.Map) => {
      const eventsGeo = buildEventsGeoJSON(markers);

      // Update or add Events GeoJSON Source
      if (map.getSource('events-source')) {
        (map.getSource('events-source') as maplibregl.GeoJSONSource).setData(eventsGeo);
      } else {
        map.addSource('events-source', {
          type: 'geojson',
          data: eventsGeo,
        });

        // 1. Impact Ground Radius (Translucent colored circle on globe surface)
        map.addLayer({
          id: 'events-impact-radius',
          type: 'circle',
          source: 'events-source',
          paint: {
            'circle-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],
              3, ['case', ['==', ['get', 'severity'], 'critical'], 22, ['==', ['get', 'severity'], 'high'], 16, 11],
              8, ['case', ['==', ['get', 'severity'], 'critical'], 64, ['==', ['get', 'severity'], 'high'], 48, 32],
            ],
            'circle-color': ['get', 'color'],
            'circle-opacity': 0.16,
            'circle-stroke-width': 1.5,
            'circle-stroke-color': ['get', 'color'],
            'circle-stroke-opacity': 0.65,
          },
        });

        // 2. Outer Soft Beacon Glow
        map.addLayer({
          id: 'events-beacon-glow',
          type: 'circle',
          source: 'events-source',
          paint: {
            'circle-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],
              2, 7,
              7, 16,
            ],
            'circle-color': ['get', 'color'],
            'circle-opacity': 0.35,
          },
        });

        // 3. Crisp Core Beacon
        map.addLayer({
          id: 'events-core',
          type: 'circle',
          source: 'events-source',
          paint: {
            'circle-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],
              2, 4.5,
              6, 7.5,
              10, 11,
            ],
            'circle-color': ['get', 'color'],
            'circle-stroke-width': 2.5,
            'circle-stroke-color': '#ffffff',
          },
        });

        // 4. Interactive Click & Hover handlers on WebGL layer
        map.on('click', 'events-core', (e) => {
          const feature = e.features?.[0];
          if (feature?.properties) {
            const found = markers.find((m) => m.id === feature.properties.id);
            if (found) {
              handleSelectIncident(found);
            }
          }
        });

        map.on('mouseenter', 'events-core', () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'events-core', () => {
          map.getCanvas().style.cursor = '';
        });
      }

      // Add or update Selected Target Spotlight Source & Layer
      const targetGeo: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: selectedMarker
          ? [
              {
                type: 'Feature',
                geometry: {
                  type: 'Point',
                  coordinates: [selectedMarker.lng, selectedMarker.lat],
                },
                properties: { id: selectedMarker.id },
              },
            ]
          : [],
      };

      if (map.getSource('target-spotlight-source')) {
        (map.getSource('target-spotlight-source') as maplibregl.GeoJSONSource).setData(targetGeo);
      } else {
        map.addSource('target-spotlight-source', {
          type: 'geojson',
          data: targetGeo,
        });

        map.addLayer({
          id: 'target-spotlight-ring',
          type: 'circle',
          source: 'target-spotlight-source',
          paint: {
            'circle-radius': 26,
            'circle-color': '#38bdf8',
            'circle-opacity': 0.15,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#38bdf8',
            'circle-stroke-opacity': 0.9,
          },
        });
      }

      // Add Cyclone DANA Trajectory
      if (!map.getSource('cyclone-track-source')) {
        map.addSource('cyclone-track-source', {
          type: 'geojson',
          data: cycloneTrackGeoJSON,
        });

        map.addLayer({
          id: 'cyclone-outer-glow',
          type: 'line',
          source: 'cyclone-track-source',
          paint: {
            'line-color': '#f59e0b',
            'line-width': 8,
            'line-opacity': 0.35,
          },
        });

        map.addLayer({
          id: 'cyclone-inner-track',
          type: 'line',
          source: 'cyclone-track-source',
          paint: {
            'line-color': '#ef4444',
            'line-width': 3,
            'line-dasharray': [2, 2],
          },
        });
      }

      // Add NDRF Bases Layer
      if (!map.getSource('ndrf-bases-source')) {
        map.addSource('ndrf-bases-source', {
          type: 'geojson',
          data: ndrfBasesGeoJSON,
        });

        map.addLayer({
          id: 'ndrf-bases-layer',
          type: 'circle',
          source: 'ndrf-bases-source',
          paint: {
            'circle-radius': 6,
            'circle-color': '#0ea5e9',
            'circle-stroke-width': 2,
            'circle-stroke-color': '#ffffff',
          },
        });
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [markers, selectedMarker]
  );

  // Initialize Map
  useEffect(() => {
    if (!mounted || !mapContainerRef.current || mapRef.current) return;

    const style = BASEMAP_STYLES[basemap];

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style,
      center: [82.0, 22.0],
      zoom: 4.6,
      pitch: 30,
      bearing: 0,
      maxPitch: 85,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

    map.on('load', () => {
      map.setProjection({ type: isGlobe ? 'globe' : 'mercator' });
      syncWebGLLayers(map);
    });

    map.on('move', () => {
      const center = map.getCenter();
      setTelemetry({
        zoom: parseFloat(map.getZoom().toFixed(2)),
        lat: parseFloat(center.lat.toFixed(2)),
        lng: parseFloat(center.lng.toFixed(2)),
        pitch: Math.round(map.getPitch()),
        bearing: Math.round(map.getBearing()),
      });
    });

    mapRef.current = map;

    return () => {
      if (autoOrbitAnimRef.current) {
        cancelAnimationFrame(autoOrbitAnimRef.current);
      }
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  // Sync layers whenever markers, selection, or layers change
  useEffect(() => {
    if (mapRef.current && mapRef.current.isStyleLoaded()) {
      syncWebGLLayers(mapRef.current);
    }
  }, [syncWebGLLayers]);

  // Layer visibility controls
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const setVisibility = (layerId: string, visible: boolean) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
      }
    };

    setVisibility('events-impact-radius', showEventsLayer);
    setVisibility('events-beacon-glow', showEventsLayer);
    setVisibility('events-core', showEventsLayer);

    setVisibility('cyclone-outer-glow', showCycloneLayer);
    setVisibility('cyclone-inner-track', showCycloneLayer);

    setVisibility('ndrf-bases-layer', showNdrfLayer);
  }, [showEventsLayer, showCycloneLayer, showNdrfLayer]);

  // Handle basemap switch
  const handleBasemapChange = (newBasemap: BasemapMode) => {
    setBasemap(newBasemap);
    const map = mapRef.current;
    if (!map) return;

    map.setStyle(BASEMAP_STYLES[newBasemap]);
    map.once('style.load', () => {
      map.setProjection({ type: isGlobe ? 'globe' : 'mercator' });
      syncWebGLLayers(map);
    });
  };

  // Toggle Globe vs Flat Mercator
  const toggleProjection = () => {
    const nextGlobe = !isGlobe;
    setIsGlobe(nextGlobe);
    if (mapRef.current) {
      mapRef.current.setProjection({ type: nextGlobe ? 'globe' : 'mercator' });
    }
  };

  // Select an incident & swoop camera smoothly
  const handleSelectIncident = (marker: MapMarker) => {
    setSelectedMarker(marker);
    if (onEventSelect) onEventSelect(marker);

    if (mapRef.current) {
      mapRef.current.flyTo({
        center: [marker.lng, marker.lat],
        zoom: 6.8,
        pitch: 45,
        bearing: 15,
        essential: true,
        duration: 2000,
      });
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
        mapRef.current.setCenter([center.lng + 0.15, center.lat]);
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
    duration = 2400
  ) => {
    if (!mapRef.current) return;
    mapRef.current.flyTo({
      center,
      zoom,
      pitch,
      bearing,
      essential: true,
      duration,
    });
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
    <div className={isFullscreen ? 'fixed inset-0 z-50 p-3 sm:p-6 bg-slate-950/90 backdrop-blur-md flex flex-col' : 'relative'}>
      <Card hover={false} className={`overflow-hidden border border-slate-200/80 shadow-card flex flex-col ${isFullscreen ? 'flex-1 h-full' : ''}`}>
        {/* Header Bar */}
        <CardHeader
          title={
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" />
              <span>3D Planetary Weather Command — Earth Orbit</span>
            </div>
          }
          subtitle="WebGL depth-culled severe incident radar with synchronized telemetry"
          action={
            <div className="flex items-center gap-2 flex-wrap justify-end">
              {/* Projection Switcher */}
              <button
                onClick={toggleProjection}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border font-medium transition-all ${
                  isGlobe
                    ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                    : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                }`}
                title="Toggle 3D Earth Globe vs 2D Flat Mercator"
              >
                {isGlobe ? <Globe className="w-3.5 h-3.5" /> : <MapIcon className="w-3.5 h-3.5" />}
                <span>{isGlobe ? '3D Globe' : '2D Flat'}</span>
              </button>

              {/* Basemap Switcher */}
              <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
                <button
                  onClick={() => handleBasemapChange('satellite')}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors ${
                    basemap === 'satellite'
                      ? 'bg-primary text-white font-semibold shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                  title="Photorealistic Satellite Earth"
                >
                  <Satellite className="w-3 h-3" />
                  <span className="hidden sm:inline">Satellite</span>
                </button>
                <button
                  onClick={() => handleBasemapChange('dark')}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors ${
                    basemap === 'dark'
                      ? 'bg-primary text-white font-semibold shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                  title="Dark Tactical Mode"
                >
                  <Moon className="w-3 h-3" />
                  <span className="hidden sm:inline">Dark</span>
                </button>
                <button
                  onClick={() => handleBasemapChange('street')}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors ${
                    basemap === 'street'
                      ? 'bg-primary text-white font-semibold shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                  title="Vector Terrain"
                >
                  <Layers className="w-3 h-3" />
                  <span className="hidden sm:inline">Terrain</span>
                </button>
              </div>

              {/* Time Range Filter */}
              <select
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value)}
                className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
                aria-label="Time range"
              >
                <option value="24h">Past 24h</option>
                <option value="48h">Past 48h</option>
                <option value="7d">Past 7d</option>
              </select>

              {/* Fullscreen Button */}
              <button
                onClick={toggleFullscreen}
                className="p-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-colors"
                title={isFullscreen ? 'Exit Fullscreen' : 'Command Center Fullscreen'}
              >
                {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
            </div>
          }
        />

        {/* Quick Hotspot & Layer Toggles Ribbon */}
        <div className="flex items-center justify-between gap-2 px-4 py-2 bg-slate-50/95 border-y border-slate-100 overflow-x-auto text-xs scrollbar-none">
          {/* Left Hotspots */}
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1 shrink-0 mr-1">
              <Compass className="w-3 h-3 text-primary" /> Sector Orbit:
            </span>
            <button
              onClick={() => flyToHotspot([82.0, 22.0], 4.6, 30, 0)}
              className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
            >
              <span>🇮🇳</span> All India
            </button>
            <button
              onClick={() => flyToHotspot([80.0, 15.0], 1.6, 0, 0, 3000)}
              className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
            >
              <Sparkles className="w-3 h-3 text-indigo-500" /> Space Orbit
            </button>
            <button
              onClick={() => flyToHotspot([88.0, 17.5], 5.8, 45, -15)}
              className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-amber-500/50 hover:bg-amber-50/50 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
            >
              <span className="text-amber-500">🌀</span> Cyclone DANA
            </button>
            <button
              onClick={() => flyToHotspot([74.5, 14.5], 6.2, 45, 10)}
              className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-blue-500/50 hover:bg-blue-50/50 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
            >
              <Waves className="w-3 h-3 text-blue-500" /> Western Ghats
            </button>
          </div>

          {/* Right Layer Toggles */}
          <div className="flex items-center gap-1.5 shrink-0 pl-2 border-l border-slate-200">
            <button
              onClick={() => setShowEventsLayer(!showEventsLayer)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                showEventsLayer
                  ? 'bg-rose-50 text-rose-700 border-rose-200 font-semibold'
                  : 'bg-white text-slate-400 border-slate-200'
              }`}
              title="Toggle Severe Alerts layer"
            >
              <AlertTriangle className="w-3 h-3" />
              <span>Alerts</span>
            </button>
            <button
              onClick={() => setShowCycloneLayer(!showCycloneLayer)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                showCycloneLayer
                  ? 'bg-amber-50 text-amber-700 border-amber-200 font-semibold'
                  : 'bg-white text-slate-400 border-slate-200'
              }`}
              title="Toggle Cyclone Track layer"
            >
              <span>🌀</span>
              <span>Cyclone</span>
            </button>
            <button
              onClick={() => setShowNdrfLayer(!showNdrfLayer)}
              className={`px-2 py-1 rounded-md border text-[11px] font-medium transition-all flex items-center gap-1 ${
                showNdrfLayer
                  ? 'bg-sky-50 text-sky-700 border-sky-200 font-semibold'
                  : 'bg-white text-slate-400 border-slate-200'
              }`}
              title="Toggle NDRF Taskforce bases"
            >
              <Shield className="w-3 h-3" />
              <span>NDRF Bases</span>
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

        {/* Map Canvas & Overlays */}
        <div
          className={`relative w-full overflow-hidden globe-space-bg ${
            isFullscreen ? 'flex-1 min-h-[520px]' : 'h-[460px]'
          }`}
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
                className="absolute top-3 left-3 z-20 w-80 max-w-[calc(100%-24px)] bg-slate-900/95 text-white backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/80 p-4"
              >
                {/* Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider"
                      style={{
                        backgroundColor: severityConfig[selectedMarker.severity]?.bg || '#f1f5f9',
                        color: severityConfig[selectedMarker.severity]?.textColor || '#334155',
                      }}
                    >
                      {severityConfig[selectedMarker.severity]?.label || selectedMarker.severity}
                    </span>
                    <span className="text-[11px] text-emerald-400 font-mono flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> AI Verified
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedMarker(null);
                      if (onEventSelect) onEventSelect(null);
                    }}
                    className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* City & Event Title */}
                <h4 className="text-base font-bold text-white tracking-tight">
                  {selectedMarker.city}, {selectedMarker.state}
                </h4>
                <p className="text-xs font-semibold text-blue-400 mt-0.5 flex items-center gap-1">
                  <Target className="w-3.5 h-3.5" />
                  {selectedMarker.eventType}
                </p>
                <p className="text-xs text-slate-300 mt-2 line-clamp-2 leading-relaxed">
                  {selectedMarker.description}
                </p>

                {/* Real-time Telemetry Grid */}
                <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-slate-800 text-[11px]">
                  <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[10px]">
                      <CloudRain className="w-3 h-3 text-blue-400" /> Rainfall
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5">
                      {selectedMarker.severity === 'critical' ? '86 mm/h' : '48 mm/h'}
                    </div>
                  </div>
                  <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[10px]">
                      <Wind className="w-3 h-3 text-amber-400" /> Wind Gusts
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5">
                      {selectedMarker.severity === 'critical' ? '68 km/h' : '34 km/h'}
                    </div>
                  </div>
                  <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[10px]">
                      <Waves className="w-3 h-3 text-rose-400" /> Water Level
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5">
                      {selectedMarker.severity === 'critical' ? '+1.9m Danger' : 'Normal'}
                    </div>
                  </div>
                  <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700/50">
                    <div className="text-slate-400 flex items-center gap-1 text-[10px]">
                      <Activity className="w-3 h-3 text-emerald-400" /> GPS Coordinates
                    </div>
                    <div className="font-mono font-bold text-white mt-0.5 truncate">
                      {selectedMarker.lat.toFixed(2)}°N, {selectedMarker.lng.toFixed(2)}°E
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 mt-3 pt-2">
                  <button
                    onClick={() => (window.location.href = '/teams')}
                    className="flex-1 py-1.5 px-3 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold text-xs transition-colors flex items-center justify-center gap-1.5 shadow-md"
                  >
                    <Shield className="w-3.5 h-3.5" />
                    <span>Dispatch NDRF</span>
                  </button>
                  <button
                    onClick={() => flyToHotspot([selectedMarker.lng, selectedMarker.lat], 8.2, 55, 20)}
                    className="py-1.5 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors"
                    title="Zoom in to tactical street level"
                  >
                    Close Zoom
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Interactive Severe Events Quick Deck (Synchronized Map Roster) */}
          <div className="absolute top-3 right-3 z-10 w-64 max-h-[360px] bg-slate-900/90 text-white backdrop-blur-xl rounded-2xl shadow-xl border border-slate-700/80 p-3 hidden sm:flex flex-col">
            <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-slate-800">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Radio className="w-3 h-3 text-rose-400 animate-pulse" />
                Live Incident Roster
              </span>
              <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                {markers.length} PINS
              </span>
            </div>

            <div className="space-y-1.5 overflow-y-auto custom-scrollbar pr-1 flex-1">
              {markers.map((marker) => {
                const isSelected = selectedMarker?.id === marker.id;
                const color = severityColors[marker.severity] || '#64748B';

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
                      <div
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <div className="truncate">
                        <div className="text-xs font-semibold text-white group-hover:text-blue-300 truncate">
                          {marker.city}, {marker.state}
                        </div>
                        <div className="text-[10px] text-slate-400 truncate">
                          {marker.eventType}
                        </div>
                      </div>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-white shrink-0 ml-1" />
                  </button>
                );
              })}
            </div>
          </div>

          {/* Real-time Telemetry HUD (Bottom-Left) */}
          <div className="absolute bottom-3 left-3 z-10 pointer-events-none hidden sm:flex items-center gap-2 bg-slate-950/85 text-white backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-800/80 text-[11px] font-mono shadow-lg">
            <span className="flex items-center gap-1 text-emerald-400 font-bold">
              <Radio className="w-3 h-3 animate-pulse" />
              {isGlobe ? 'GLOBE: WGS-84' : 'FLAT: MERCATOR'}
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
                <span className="text-indigo-400 animate-pulse font-semibold">ORBIT: 0.15°/F</span>
              </>
            )}
          </div>

          {/* Occlusion / Zoom Status Pill */}
          <div className="absolute bottom-3 right-3 sm:right-auto sm:left-[430px] z-10 pointer-events-none bg-slate-900/80 text-slate-300 backdrop-blur-md px-2.5 py-1 rounded-md border border-slate-800 text-[10px] font-mono flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            <span>WebGL Depth Buffer Active (Zero Occlusion Leak)</span>
          </div>
        </div>
      </Card>
    </div>
  );
}
