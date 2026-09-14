'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
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

// Event type legend
const eventTypeIcons = [
  { type: 'Severe Rainfall', color: '#EF4444', Icon: CloudRain },
  { type: 'Flood', color: '#F59E0B', Icon: Waves },
  { type: 'Thunderstorm', color: '#8B5CF6', Icon: Zap },
  { type: 'Strong Winds', color: '#2563EB', Icon: Wind },
  { type: 'Fog', color: '#64748B', Icon: CloudFog },
];

// Bay of Bengal Cyclone Track Coordinates (Geodesic curved path)
const cycloneTrackGeoJSON: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { name: 'Cyclone DANA — Forecast Path' },
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

export default function GlobeEventMap() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const cycloneEyeMarkerRef = useRef<maplibregl.Marker | null>(null);

  const [mounted, setMounted] = useState(false);
  const [isGlobe, setIsGlobe] = useState(true);
  const [basemap, setBasemap] = useState<BasemapMode>('satellite');
  const [timeRange, setTimeRange] = useState('24h');
  const [markers, setMarkers] = useState<MapMarker[]>(mapMarkers);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [webGLSupported, setWebGLSupported] = useState(true);

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

  // Fetch live events or use mock data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const events = await fetchEvents({ time_range: timeRange });
        if (!cancelled && events.length > 0) {
          setMarkers(apiEventsToMapMarkers(events));
        }
      } catch {
        // mock markers default
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [timeRange]);

  // Render weather markers on map
  const renderMarkers = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    // Clear existing markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    markers.forEach((marker) => {
      const color = severityColors[marker.severity] || '#64748B';
      const isPulsing = marker.severity === 'critical' || marker.severity === 'high';

      // Create custom DOM marker element
      const el = document.createElement('div');
      el.className = 'cursor-pointer group';
      el.style.width = '28px';
      el.style.height = '28px';
      el.style.position = 'relative';

      // Concentric pulse animation ring
      if (isPulsing) {
        const pulse = document.createElement('div');
        pulse.className = `pulse-ring pulse-ring-${marker.severity}`;
        pulse.style.width = '36px';
        pulse.style.height = '36px';
        pulse.style.top = '-4px';
        pulse.style.left = '-4px';
        el.appendChild(pulse);
      }

      // Pin core dot
      const dot = document.createElement('div');
      dot.style.width = '24px';
      dot.style.height = '24px';
      dot.style.borderRadius = '50%';
      dot.style.backgroundColor = color;
      dot.style.border = '3px solid #ffffff';
      dot.style.boxShadow = '0 2px 10px rgba(0,0,0,0.45)';
      dot.style.display = 'flex';
      dot.style.alignItems = 'center';
      dot.style.justifyContent = 'center';
      dot.style.transition = 'transform 0.2s ease';
      dot.style.position = 'relative';
      dot.style.zIndex = '10';

      const innerGlow = document.createElement('div');
      innerGlow.style.width = '6px';
      innerGlow.style.height = '6px';
      innerGlow.style.borderRadius = '50%';
      innerGlow.style.backgroundColor = '#ffffff';
      dot.appendChild(innerGlow);

      el.appendChild(dot);

      el.addEventListener('mouseenter', () => {
        dot.style.transform = 'scale(1.25)';
      });
      el.addEventListener('mouseleave', () => {
        dot.style.transform = 'scale(1.0)';
      });

      // Custom Glassmorphic Popup
      const popupHtml = `
        <div style="font-family: inherit; min-width: 220px; color: #0f172a;">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px;">
            <span style="
              font-size: 10px; font-weight: 700; text-transform: uppercase;
              padding: 3px 8px; border-radius: 6px;
              background-color: ${severityConfig[marker.severity]?.bg || '#f1f5f9'};
              color: ${severityConfig[marker.severity]?.textColor || '#334155'};
              letter-spacing: 0.5px;
            ">
              ${severityConfig[marker.severity]?.label || marker.severity}
            </span>
            <span style="font-size: 11px; color: #64748b; font-weight: 500;">
              ${marker.verification === 'verified' ? '✓ Verified' : 'Under Review'}
            </span>
          </div>
          <div style="font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 2px;">
            ${marker.city}, ${marker.state}
          </div>
          <div style="font-size: 12px; font-weight: 600; color: #2563eb; margin-bottom: 6px;">
            ${marker.eventType}
          </div>
          <p style="font-size: 12px; color: #475569; line-height: 1.45; margin: 0 0 10px 0;">
            ${marker.description}
          </p>
          <div style="display: flex; gap: 6px;">
            <button
              onclick="window.location.href='/teams'"
              style="
                flex: 1; padding: 6px 10px; border-radius: 6px;
                background-color: #0284c7; color: white;
                font-size: 11px; font-weight: 600; border: none; cursor: pointer;
                box-shadow: 0 1px 3px rgba(0,0,0,0.15);
              "
            >
              Dispatch Unit
            </button>
            <button
              onclick="window.location.href='/events'"
              style="
                padding: 6px 10px; border-radius: 6px;
                background-color: #f1f5f9; color: #334155;
                font-size: 11px; font-weight: 600; border: 1px solid #cbd5e1; cursor: pointer;
              "
            >
              Intel
            </button>
          </div>
        </div>
      `;

      const popup = new maplibregl.Popup({
        offset: 16,
        closeButton: true,
        closeOnClick: false,
        maxWidth: '300px',
      }).setHTML(popupHtml);

      const m = new maplibregl.Marker({ element: el })
        .setLngLat([marker.lng, marker.lat])
        .setPopup(popup)
        .addTo(map);

      markersRef.current.push(m);
    });
  }, [markers]);

  // Add Bay of Bengal Cyclone Track overlay
  const setupCycloneOverlay = useCallback((map: maplibregl.Map) => {
    try {
      if (!map.getSource('cyclone-track')) {
        map.addSource('cyclone-track', {
          type: 'geojson',
          data: cycloneTrackGeoJSON,
        });

        // Glowing outer path
        map.addLayer({
          id: 'cyclone-glow',
          type: 'line',
          source: 'cyclone-track',
          layout: {
            'line-join': 'round',
            'line-cap': 'round',
          },
          paint: {
            'line-color': '#f59e0b',
            'line-width': 8,
            'line-opacity': 0.4,
          },
        });

        // Core dashed trajectory
        map.addLayer({
          id: 'cyclone-core',
          type: 'line',
          source: 'cyclone-track',
          layout: {
            'line-join': 'round',
            'line-cap': 'round',
          },
          paint: {
            'line-color': '#ef4444',
            'line-width': 3,
            'line-dasharray': [2, 2],
          },
        });
      }

      // Add animated Cyclone Eye marker at tip
      if (!cycloneEyeMarkerRef.current) {
        const eyeEl = document.createElement('div');
        eyeEl.className = 'cyclone-eye-marker cursor-pointer';
        eyeEl.style.width = '32px';
        eyeEl.style.height = '32px';
        eyeEl.style.position = 'relative';

        const ring = document.createElement('div');
        ring.className = 'pulse-ring pulse-ring-critical';
        ring.style.width = '42px';
        ring.style.height = '42px';
        ring.style.top = '-5px';
        ring.style.left = '-5px';
        eyeEl.appendChild(ring);

        const iconBox = document.createElement('div');
        iconBox.style.width = '30px';
        iconBox.style.height = '30px';
        iconBox.style.borderRadius = '50%';
        iconBox.style.backgroundColor = '#ef4444';
        iconBox.style.border = '2px solid white';
        iconBox.style.boxShadow = '0 0 16px rgba(239, 68, 68, 0.8)';
        iconBox.style.display = 'flex';
        iconBox.style.alignItems = 'center';
        iconBox.style.justifyContent = 'center';
        iconBox.style.color = '#ffffff';
        iconBox.style.fontSize = '14px';
        iconBox.innerHTML = '🌀';

        eyeEl.appendChild(iconBox);

        const eyePopup = new maplibregl.Popup({ offset: 16 }).setHTML(`
          <div style="font-family: inherit; padding: 4px;">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
              <span style="background:#fee2e2; color:#dc2626; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px;">
                CATEGORY 2 CYCLONE
              </span>
            </div>
            <div style="font-weight:700; font-size:14px; color:#0f172a;">Cyclone DANA Eye</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">Sustained Winds: 120 km/h</div>
            <div style="font-size:11px; color:#ea580c; font-weight:600; margin-top:4px;">Landfall: Odisha Coast in ~14h</div>
          </div>
        `);

        cycloneEyeMarkerRef.current = new maplibregl.Marker({ element: eyeEl })
          .setLngLat([85.8, 21.8])
          .setPopup(eyePopup)
          .addTo(map);
      }
    } catch {
      // Source or layer might already be active
    }
  }, []);

  // Initialize MapLibre GL
  useEffect(() => {
    if (!mounted || !mapContainerRef.current || mapRef.current) return;

    const style = BASEMAP_STYLES[basemap];

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style,
      center: [82.0, 22.0], // Centered on India
      zoom: 4.6,
      pitch: 30,
      bearing: 0,
      maxPitch: 85,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

    map.on('load', () => {
      // Set projection to globe or mercator
      map.setProjection({ type: isGlobe ? 'globe' : 'mercator' });
      setupCycloneOverlay(map);
      renderMarkers();
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
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      if (cycloneEyeMarkerRef.current) {
        cycloneEyeMarkerRef.current.remove();
        cycloneEyeMarkerRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  // Update basemap style
  const handleBasemapChange = (newBasemap: BasemapMode) => {
    setBasemap(newBasemap);
    if (!mapRef.current) return;

    mapRef.current.setStyle(BASEMAP_STYLES[newBasemap]);
    mapRef.current.once('style.load', () => {
      mapRef.current?.setProjection({ type: isGlobe ? 'globe' : 'mercator' });
      if (mapRef.current) {
        setupCycloneOverlay(mapRef.current);
        renderMarkers();
      }
    });
  };

  // Toggle Globe vs Flat Mercator projection
  const toggleProjection = () => {
    const nextGlobe = !isGlobe;
    setIsGlobe(nextGlobe);
    if (mapRef.current) {
      mapRef.current.setProjection({ type: nextGlobe ? 'globe' : 'mercator' });
    }
  };

  // Re-render markers when marker data changes
  useEffect(() => {
    if (mapRef.current && mapRef.current.isStyleLoaded()) {
      renderMarkers();
    }
  }, [renderMarkers]);

  // Cinematic Quick Flight Handlers
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

  // Handle Fullscreen Resize
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
    <div className={isFullscreen ? 'fixed inset-0 z-50 p-3 sm:p-6 bg-slate-950/85 backdrop-blur-md flex flex-col' : 'relative'}>
      <Card hover={false} className={`overflow-hidden border border-slate-200/80 shadow-card flex flex-col ${isFullscreen ? 'flex-1 h-full' : ''}`}>
        {/* Header Bar */}
        <CardHeader
          title={
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" />
              <span>3D Planetary Weather Command — Earth Orbit</span>
            </div>
          }
          subtitle="Real-time multi-spectral GIS with seamless 3D spherical globe morphing"
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
                  title="Vector Street / Terrain"
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

              {/* Fullscreen Mode Button */}
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

        {/* Quick Hotspot Fly-To Ribbon */}
        <div className="flex items-center gap-1.5 px-4 py-2 bg-slate-50/90 border-y border-slate-100 overflow-x-auto text-xs scrollbar-none">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1 shrink-0 mr-1">
            <Compass className="w-3 h-3 text-primary" /> Sector Orbit:
          </span>
          <button
            onClick={() => flyToHotspot([82.0, 22.0], 4.6, 30, 0)}
            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
          >
            <span>🇮🇳</span> All India Focus
          </button>
          <button
            onClick={() => flyToHotspot([80.0, 15.0], 1.6, 0, 0, 3000)}
            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-primary/50 hover:bg-primary/5 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
          >
            <Sparkles className="w-3 h-3 text-indigo-500" /> Space Orbit (Globe)
          </button>
          <button
            onClick={() => flyToHotspot([88.0, 17.5], 5.8, 45, -15)}
            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-amber-500/50 hover:bg-amber-50/50 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
          >
            <span className="text-amber-500">🌀</span> Bay of Bengal (Cyclone Dana)
          </button>
          <button
            onClick={() => flyToHotspot([74.5, 14.5], 6.2, 45, 10)}
            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-blue-500/50 hover:bg-blue-50/50 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
          >
            <Waves className="w-3 h-3 text-blue-500" /> Western Ghats (Monsoon Surge)
          </button>
          <button
            onClick={() => flyToHotspot([78.5, 31.5], 6.0, 55, 20)}
            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 hover:border-slate-400 hover:bg-slate-100 text-slate-700 font-medium shrink-0 transition-all flex items-center gap-1"
          >
            <span>🏔️</span> Himalayan Belt (Cloudburst Zone)
          </button>
        </div>

        {/* Map Canvas Container */}
        <div
          className={`relative w-full overflow-hidden globe-space-bg ${
            isFullscreen ? 'flex-1 min-h-[500px]' : 'h-[440px]'
          }`}
        >
          <div ref={mapContainerRef} className="w-full h-full" />

          {/* Real-time Telemetry HUD (Bottom-Left) */}
          <div className="absolute bottom-3 left-3 z-10 pointer-events-none hidden sm:flex items-center gap-2 bg-slate-950/80 text-white backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-800/80 text-[11px] font-mono shadow-lg">
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
          </div>

          {/* Smooth Globe Zoom Hint Banner (Shows when in Globe mode at high zoom) */}
          <div className="absolute top-3 left-3 z-10 pointer-events-none bg-slate-900/75 text-white backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-700/60 text-xs flex items-center gap-2 shadow-md">
            <Eye className="w-3.5 h-3.5 text-blue-400" />
            <span>
              {telemetry.zoom <= 3.2
                ? '🌍 Outer Space Orbit — Scroll wheel in to descend to India'
                : '🇮🇳 National Tactical View — Scroll wheel out to morph into Globe'}
            </span>
          </div>

          {/* Floating Weather Severity Legend (Bottom-Right) */}
          <div className="absolute bottom-3 right-3 z-10 bg-white/95 backdrop-blur-md rounded-xl shadow-xl p-2.5 border border-slate-200/80 max-w-[210px]">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center justify-between">
              <span>Severe Events</span>
              <span className="text-primary font-mono">{markers.length} Live</span>
            </div>
            <div className="space-y-1">
              {eventTypeIcons.map(({ type, color, Icon }) => (
                <div key={type} className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <Icon className="w-3 h-3 text-slate-500 shrink-0" />
                  <span className="text-[11px] text-slate-700 font-medium truncate">{type}</span>
                </div>
              ))}
              <div className="pt-1 mt-1 border-t border-slate-100 flex items-center gap-1.5 text-[10px] text-amber-600 font-semibold">
                <span className="text-xs">🌀</span>
                <span>Cyclone Dana Track (Bay of Bengal)</span>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
