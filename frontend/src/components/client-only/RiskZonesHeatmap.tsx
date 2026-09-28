'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { cn } from '@/lib/utils';
import { RotateCcw } from 'lucide-react';

export interface RiskZoneFeature {
  id: string;
  name: string;
  state: string;
  lat: number;
  lng: number;
  level: 'critical' | 'high' | 'medium' | 'low';
  score: number; // 0.0 - 1.0
  hazard: string;
  reportsCount: number;
  verified: boolean;
}

interface RiskZonesHeatmapProps {
  zones: RiskZoneFeature[];
  activeFilter?: 'all' | 'critical' | 'high' | 'medium' | 'low';
  viewMode?: 'severity' | 'fly';
  connectOvi?: boolean;
  onZoneSelect?: (zone: RiskZoneFeature | null) => void;
  className?: string;
}

// Light carto basemap style matching the reference image
const LIGHT_MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    carto_light: {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
      ],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors, © CARTO',
    },
  },
  layers: [
    {
      id: 'carto-light-layer',
      type: 'raster',
      source: 'carto_light',
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

// India geographic bounds
const INDIA_BOUNDS: [[number, number], [number, number]] = [
  [68.1, 7.5],   // Southwest coordinates [lng, lat]
  [97.4, 35.5],  // Northeast coordinates [lng, lat]
];

export default function RiskZonesHeatmap({
  zones,
  activeFilter = 'all',
  viewMode = 'severity',
  connectOvi = true,
  onZoneSelect,
  className,
}: RiskZonesHeatmapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [hoveredZone, setHoveredZone] = useState<RiskZoneFeature | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const flyTourTimerRef = useRef<NodeJS.Timeout | null>(null);
  const currentTourIndexRef = useRef(0);
  const zonesRef = useRef(zones);
  zonesRef.current = zones;
  const onZoneSelectRef = useRef(onZoneSelect);
  onZoneSelectRef.current = onZoneSelect;

  // Filter features based on activeFilter
  const filteredZones = React.useMemo(() => {
    if (activeFilter === 'all') return zones;
    return zones.filter((z) => z.level === activeFilter);
  }, [zones, activeFilter]);

  // Convert zones to GeoJSON FeatureCollection
  const geojsonData: GeoJSON.FeatureCollection<GeoJSON.Point> = React.useMemo(() => ({
    type: 'FeatureCollection',
    features: filteredZones.map((z) => ({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [z.lng, z.lat],
      },
      properties: {
        id: z.id,
        name: z.name,
        state: z.state,
        level: z.level,
        score: z.score,
        hazard: z.hazard,
        reportsCount: z.reportsCount,
        verified: z.verified ? 1 : 0,
        // Intensity weight for heatmap: Critical=1.0, High=0.75, Medium=0.5, Low=0.25
        weight: z.level === 'critical' ? 1.0 : z.level === 'high' ? 0.75 : z.level === 'medium' ? 0.5 : 0.25,
      },
    })),
  }), [filteredZones]);

  // Initialize MapLibre instance
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: LIGHT_MAP_STYLE,
      center: [79.2, 22.8],
      zoom: 3.8,
      minZoom: 3.2,
      maxZoom: 10,
      maxBounds: [
        [60.0, 4.0],
        [105.0, 39.0],
      ],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });

    map.fitBounds(INDIA_BOUNDS, {
      padding: { top: 20, bottom: 20, left: 20, right: 20 },
      animate: false,
    });

    map.on('load', () => {
      // 1. Add Source
      map.addSource('risk-zones-source', {
        type: 'geojson',
        data: geojsonData,
      });

      // 2. Add Hardware-Accelerated Heatmap Layer
      map.addLayer({
        id: 'risk-zones-heatmap',
        type: 'heatmap',
        source: 'risk-zones-source',
        maxzoom: 9,
        paint: {
          // Point weight based on score
          'heatmap-weight': [
            'interpolate',
            ['linear'],
            ['get', 'weight'],
            0, 0.1,
            1, 1.0,
          ],
          // Heatmap intensity by zoom level
          'heatmap-intensity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3, 1.2,
            7, 2.5,
          ],
          // Color ramp matching reference: Blue (Low) -> Yellow (Medium) -> Orange (High) -> Red (Critical)
          'heatmap-color': [
            'interpolate',
            ['linear'],
            ['heatmap-density'],
            0.0, 'rgba(255, 255, 255, 0)',
            0.15, 'rgba(59, 130, 246, 0.55)',   // Blue (Low)
            0.38, 'rgba(234, 179, 8, 0.75)',    // Yellow (Medium)
            0.65, 'rgba(249, 115, 22, 0.85)',   // Orange (High)
            0.92, 'rgba(239, 68, 68, 0.95)',    // Red (Critical)
          ],
          // Heatmap radius: increases smoothly as you zoom in
          'heatmap-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3, 22,
            6, 42,
            9, 65,
          ],
          'heatmap-opacity': 0.88,
        },
      });

      // 3. Hotspot circle markers for interactive hover & inspection
      map.addLayer({
        id: 'risk-zones-points',
        type: 'circle',
        source: 'risk-zones-source',
        minzoom: 3.5,
        paint: {
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3.5, 4,
            7, 8,
          ],
          'circle-color': [
            'match',
            ['get', 'level'],
            'critical', '#EF4444',
            'high', '#F97316',
            'medium', '#EAB308',
            /* default / low */ '#3B82F6',
          ],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#FFFFFF',
          'circle-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3.5, 0.4,
            5.5, 0.85,
          ],
        },
      });

      // 4. Subtle Outer Pulse Glow for Critical / High zones
      map.addLayer({
        id: 'risk-zones-glow',
        type: 'circle',
        source: 'risk-zones-source',
        filter: ['in', ['get', 'level'], ['literal', ['critical', 'high']]],
        paint: {
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3.5, 8,
            7, 18,
          ],
          'circle-color': [
            'match',
            ['get', 'level'],
            'critical', '#EF4444',
            'high', '#F97316',
            '#F97316',
          ],
          'circle-opacity': 0.22,
          'circle-stroke-width': 1,
          'circle-stroke-color': [
            'match',
            ['get', 'level'],
            'critical', '#EF4444',
            'high', '#F97316',
            '#F97316',
          ],
          'circle-stroke-opacity': 0.45,
        },
      });

      setMapLoaded(true);
    });

    // Hover tooltip tracking
    map.on('mousemove', 'risk-zones-points', (e) => {
      if (e.features && e.features.length > 0) {
        map.getCanvas().style.cursor = 'pointer';
        const props = e.features[0].properties as any;
        const matched = zonesRef.current.find((z) => z.id === props.id);
        if (matched) {
          setHoveredZone(matched);
          setTooltipPos({ x: e.point.x, y: e.point.y });
        }
      }
    });

    map.on('mouseleave', 'risk-zones-points', () => {
      map.getCanvas().style.cursor = '';
      setHoveredZone(null);
      setTooltipPos(null);
    });

    map.on('click', 'risk-zones-points', (e) => {
      if (e.features && e.features.length > 0) {
        const props = e.features[0].properties as any;
        const matched = zonesRef.current.find((z) => z.id === props.id);
        if (matched) {
          onZoneSelectRef.current?.(matched);
          map.flyTo({
            center: [matched.lng, matched.lat],
            zoom: 6.5,
            duration: 1200,
          });
        }
      }
    });

    mapRef.current = map;

    // Optimized ResizeObserver to prevent canvas stretch/distortion
    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    resizeObserver.observe(mapContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (flyTourTimerRef.current) clearInterval(flyTourTimerRef.current);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync data dynamically without recreating the map
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const source = mapRef.current.getSource('risk-zones-source') as maplibregl.GeoJSONSource;
    if (source) {
      source.setData(geojsonData);
    }
  }, [geojsonData, mapLoaded]);

  // Handle "Fly / Real" mode
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;

    if (viewMode === 'fly') {
      const topZones = zones.filter((z) => z.level === 'critical' || z.level === 'high');
      if (topZones.length === 0) return;

      currentTourIndexRef.current = 0;
      const flyToNext = () => {
        const target = topZones[currentTourIndexRef.current % topZones.length];
        currentTourIndexRef.current++;
        mapRef.current?.flyTo({
          center: [target.lng, target.lat],
          zoom: 5.8,
          duration: 3500,
          essential: true,
        });
      };

      flyToNext();
      flyTourTimerRef.current = setInterval(flyToNext, 6500);

      return () => {
        if (flyTourTimerRef.current) clearInterval(flyTourTimerRef.current);
      };
    } else {
      if (flyTourTimerRef.current) clearInterval(flyTourTimerRef.current);
      mapRef.current.fitBounds(INDIA_BOUNDS, {
        padding: { top: 20, bottom: 20, left: 20, right: 20 },
        duration: 1500,
      });
    }
  }, [viewMode, mapLoaded, zones]);

  // Reset to full view helper
  const handleResetView = useCallback(() => {
    if (!mapRef.current) return;
    mapRef.current.fitBounds(INDIA_BOUNDS, {
      padding: { top: 20, bottom: 20, left: 20, right: 20 },
      duration: 1200,
    });
  }, []);

  return (
    <div className={cn('relative w-full h-full min-h-[320px] overflow-hidden rounded-xl bg-slate-50 border border-slate-100', className)}>
      {/* MapLibre WebGL Canvas Container */}
      <div ref={mapContainerRef} className="w-full h-full" />

      {/* Floating Tactical Overlay Controls */}
      <div className="absolute top-2.5 right-2.5 flex items-center gap-1.5 z-10">
        <button
          type="button"
          onClick={handleResetView}
          title="Reset to All-India View"
          className="p-1.5 rounded-md bg-white/95 text-slate-700 shadow-2xs border border-slate-200/80 hover:bg-white hover:text-slate-900 transition-all cursor-pointer backdrop-blur-xs text-[11px] font-mono flex items-center gap-1"
        >
          <RotateCcw className="w-3.5 h-3.5 text-slate-500" />
          <span className="hidden sm:inline">Reset</span>
        </button>
      </div>

      {/* OVI Status Pulse Badge inside map */}
      {connectOvi && (
        <div className="absolute bottom-2.5 left-2.5 z-10 flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/95 border border-emerald-200 shadow-2xs backdrop-blur-xs text-[10px] font-mono text-emerald-800">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="font-semibold">OVI Real-time</span>
          <span className="text-[9px] text-slate-400">· 60fps WebGL</span>
        </div>
      )}

      {/* Interactive Hover Tooltip */}
      {hoveredZone && tooltipPos && (
        <div
          className="absolute pointer-events-none z-30 transform -translate-x-1/2 -translate-y-full -mt-2 bg-slate-900/95 text-white p-2.5 rounded-lg shadow-xl border border-slate-700/80 backdrop-blur-md text-[11px] min-w-[180px]"
          style={{ left: `${tooltipPos.x}px`, top: `${tooltipPos.y}px` }}
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-800 pb-1 mb-1">
            <span className="font-semibold text-white truncate">{hoveredZone.name}</span>
            <span
              className={cn(
                'text-[9px] font-bold px-1.5 py-0.5 rounded uppercase',
                hoveredZone.level === 'critical'
                  ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                  : hoveredZone.level === 'high'
                  ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
                  : hoveredZone.level === 'medium'
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
              )}
            >
              {hoveredZone.level}
            </span>
          </div>

          <div className="space-y-0.5 text-slate-300 text-[10px]">
            <div className="flex justify-between">
              <span className="text-slate-400">State:</span>
              <span className="font-medium text-slate-200">{hoveredZone.state}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Primary Hazard:</span>
              <span className="font-medium text-slate-200">{hoveredZone.hazard}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Risk Score:</span>
              <span className="font-mono font-bold text-amber-400">{Math.round(hoveredZone.score * 100)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Citizen Reports:</span>
              <span className="font-mono text-slate-200">{hoveredZone.reportsCount}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
