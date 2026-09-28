'use client';

import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  INDIA_STATES,
  COMBINED_INDIA_PATH,
  SRI_LANKA_PATH,
  INDIA_MAP_VIEWBOX,
  projectCoordinates,
  type StateMapFeature,
} from '@/data/india-map-paths';
import { cn } from '@/lib/utils';
import type { GeoHeatmapCell } from '@/lib/api';
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Compass,
  Crosshair,
  Radio,
  ShieldCheck,
  AlertTriangle,
  Info,
  Maximize2,
  ExternalLink,
  MapPin,
  Activity,
  Layers,
  ChevronRight,
  Flame,
  CheckCircle2,
} from 'lucide-react';

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
  geoCells?: GeoHeatmapCell[];
  activeFilter?: 'all' | 'critical' | 'high' | 'medium' | 'low';
  viewMode?: 'severity' | 'fly';
  connectOvi?: boolean;
  onZoneSelect?: (zone: RiskZoneFeature | null) => void;
  className?: string;
}

export interface RegionPreset {
  id: string;
  name: string;
  viewBox: string;
}

const REGION_PRESETS: RegionPreset[] = [
  { id: 'all', name: 'All India', viewBox: INDIA_MAP_VIEWBOX },
  { id: 'north', name: 'North & Himalayas', viewBox: '90 10 320 280' },
  { id: 'gangetic', name: 'Gangetic Plains', viewBox: '175 160 330 270' },
  { id: 'west', name: 'West Coast', viewBox: '35 240 290 310' },
  { id: 'northeast', name: 'Northeast Front', viewBox: '410 175 190 200' },
  { id: 'south', name: 'Peninsular South', viewBox: '115 390 310 285' },
];

export default function RiskZonesHeatmap({
  zones,
  geoCells = [],
  activeFilter = 'all',
  viewMode = 'severity',
  connectOvi = true,
  onZoneSelect,
  className,
}: RiskZonesHeatmapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredState, setHoveredState] = useState<StateMapFeature | null>(null);
  const [hoveredZone, setHoveredZone] = useState<RiskZoneFeature | null>(null);
  const [selectedZone, setSelectedZone] = useState<RiskZoneFeature | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const [currentViewBox, setCurrentViewBox] = useState<string>(INDIA_MAP_VIEWBOX);
  const [activeRegion, setActiveRegion] = useState<string>('all');
  const [radarY, setRadarY] = useState(0);

  // Radar sweep animation when in "Fly / Real" mode
  useEffect(() => {
    if (viewMode !== 'fly') return;
    let animId: number;
    let start: number | null = null;

    const animate = (timestamp: number) => {
      if (!start) start = timestamp;
      const elapsed = timestamp - start;
      const progress = (elapsed % 4200) / 4200; // 4.2s sweep cycle
      setRadarY(progress * 680);
      animId = requestAnimationFrame(animate);
    };

    animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, [viewMode]);

  // Handle region preset selection
  const handleRegionSelect = (region: RegionPreset) => {
    setActiveRegion(region.id);
    setCurrentViewBox(region.viewBox);
  };

  // Handle smooth step zoom
  const handleZoom = (direction: 'in' | 'out') => {
    const parts = currentViewBox.split(' ').map(Number);
    if (parts.length !== 4) return;
    const [x, y, w, h] = parts;
    const factor = direction === 'in' ? 0.78 : 1.28;
    const newW = Math.max(120, Math.min(585, w * factor));
    const newH = Math.max(140, Math.min(660, h * factor));
    const newX = Math.max(0, Math.min(500, x + (w - newW) / 2));
    const newY = Math.max(0, Math.min(600, y + (h - newH) / 2));
    setCurrentViewBox(`${Math.round(newX)} ${Math.round(newY)} ${Math.round(newW)} ${Math.round(newH)}`);
    setActiveRegion('custom');
  };

  const handleResetZoom = () => {
    setCurrentViewBox(INDIA_MAP_VIEWBOX);
    setActiveRegion('all');
    setSelectedZone(null);
    onZoneSelect?.(null);
  };

  // Filter features based on activeFilter
  const filteredZones = useMemo(() => {
    if (activeFilter === 'all') return zones;
    return zones.filter((z) => z.level === activeFilter);
  }, [zones, activeFilter]);

  // Projected coordinates for zones
  const projectedZones = useMemo(() => {
    return filteredZones.map((z) => {
      const [x, y] = projectCoordinates(z.lng, z.lat);
      return { ...z, svgX: x, svgY: y };
    });
  }, [filteredZones]);

  // Real dynamic thermal spots from geoCells (H3 report density) and zones (verified events)
  // Optimized for peak framerate by batching top report clusters + verified incidents
  const thermalSpots = useMemo(() => {
    const spots: Array<{
      id: string;
      x: number;
      y: number;
      outerRadius: number;
      midRadius: number;
      coreRadius: number;
      coreColor: string;
      midColor: string;
      outerColor: string;
      coreOpacity: number;
      midOpacity: number;
      outerOpacity: number;
    }> = [];

    // 1. Process top real H3 report clusters (from raw_reports)
    if (geoCells && geoCells.length > 0) {
      const maxCount = Math.max(...geoCells.map((c) => c.report_count), 1);
      // Select top 45 densest clusters for optimal GPU performance
      const topCells = [...geoCells].sort((a, b) => b.report_count - a.report_count).slice(0, 45);

      topCells.forEach((cell, idx) => {
        const [x, y] = projectCoordinates(cell.lng, cell.lat);
        if (x < 10 || x > 590 || y < 10 || y > 670) return;

        const ratio = cell.report_count / maxCount;
        const isDense = ratio > 0.35;
        const isMed = ratio > 0.12;

        spots.push({
          id: `h3-${cell.h3 || idx}`,
          x,
          y,
          outerRadius: Math.round(28 + ratio * 36),
          midRadius: Math.round(16 + ratio * 22),
          coreRadius: Math.round(8 + ratio * 14),
          coreColor: isDense ? '#EF4444' : isMed ? '#F97316' : '#EAB308',
          midColor: isDense ? '#F97316' : '#EAB308',
          outerColor: isDense ? '#FBBF24' : '#60A5FA',
          coreOpacity: Math.min(0.92, 0.45 + ratio * 0.45),
          midOpacity: Math.min(0.72, 0.3 + ratio * 0.38),
          outerOpacity: Math.min(0.42, 0.15 + ratio * 0.22),
        });
      });
    }

    // 2. Process real verified disaster events (from events table)
    zones.forEach((zone) => {
      const [x, y] = projectCoordinates(zone.lng, zone.lat);
      if (x < 10 || x > 590 || y < 10 || y > 670) return;

      const isCrit = zone.level === 'critical';
      const isHigh = zone.level === 'high';
      const isMed = zone.level === 'medium';

      spots.push({
        id: `zone-spot-${zone.id}`,
        x,
        y,
        outerRadius: isCrit ? 60 : isHigh ? 46 : isMed ? 34 : 24,
        midRadius: isCrit ? 36 : isHigh ? 28 : isMed ? 20 : 14,
        coreRadius: isCrit ? 18 : isHigh ? 13 : isMed ? 9 : 6,
        coreColor: isCrit ? '#DC2626' : isHigh ? '#F97316' : isMed ? '#EAB308' : '#3B82F6',
        midColor: isCrit ? '#F97316' : isHigh ? '#F59E0B' : isMed ? '#FBBF24' : '#60A5FA',
        outerColor: isCrit ? '#F59E0B' : isHigh ? '#FBBF24' : '#93C5FD',
        coreOpacity: isCrit ? 0.94 : isHigh ? 0.82 : isMed ? 0.65 : 0.45,
        midOpacity: isCrit ? 0.72 : isHigh ? 0.58 : isMed ? 0.45 : 0.3,
        outerOpacity: isCrit ? 0.42 : isHigh ? 0.32 : isMed ? 0.22 : 0.15,
      });
    });

    return spots;
  }, [geoCells, zones]);

  // Dynamically calculate threat metrics per state from real events and reports
  const stateThreatMap = useMemo(() => {
    const map = new Map<
      string,
      {
        level: 'critical' | 'high' | 'medium' | 'low';
        eventsCount: number;
        totalReports: number;
        primaryHazard: string;
      }
    >();

    zones.forEach((z) => {
      const stateKey = (z.state || '').trim().toLowerCase().replace(/[^a-z]/g, '');
      if (!stateKey) return;

      const existing = map.get(stateKey) || {
        level: 'low' as const,
        eventsCount: 0,
        totalReports: 0,
        primaryHazard: z.hazard,
      };

      existing.eventsCount += 1;
      existing.totalReports += z.reportsCount || 1;

      const sevPrecedence = { critical: 4, high: 3, medium: 2, low: 1 };
      if (sevPrecedence[z.level] > sevPrecedence[existing.level]) {
        existing.level = z.level;
        existing.primaryHazard = z.hazard;
      }

      map.set(stateKey, existing);
    });

    return map;
  }, [zones]);

  // Handle click on zone beacon
  const handleZoneClick = (z: RiskZoneFeature, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = selectedZone?.id === z.id ? null : z;
    setSelectedZone(next);
    onZoneSelect?.(next);

    // If selected, gently pan to focus area
    if (next) {
      const [x, y] = projectCoordinates(next.lng, next.lat);
      const panW = 280;
      const panH = 300;
      const panX = Math.max(10, Math.min(320, x - panW / 2));
      const panY = Math.max(10, Math.min(380, y - panH / 2));
      setCurrentViewBox(`${Math.round(panX)} ${Math.round(panY)} ${panW} ${panH}`);
      setActiveRegion('custom');
    }
  };

  // Handle mouse move for floating tooltip position
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setTooltipPos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  }, []);

  const isFlyMode = viewMode === 'fly';

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      className={cn(
        'relative w-full h-full min-h-[310px] flex flex-col items-center justify-between select-none overflow-hidden rounded-xl border transition-colors duration-500 p-2',
        isFlyMode
          ? 'bg-[#09111E] border-slate-800 text-white shadow-inner'
          : 'bg-gradient-to-b from-[#FAF8F5] to-[#F3EFE8]/75 border-[#E8E2D4]/70 shadow-xs'
      )}
    >
      {/* ── Top HUD Bar: Regional Focus Chips + Zoom Controls ── */}
      <div className="w-full flex items-center justify-between gap-1.5 z-20 mb-1 flex-wrap">
        {/* Left: Region Quick Filters */}
        <div className="flex items-center gap-1 overflow-x-auto no-scrollbar py-0.5">
          {REGION_PRESETS.map((reg) => (
            <button
              key={reg.id}
              type="button"
              onClick={() => handleRegionSelect(reg)}
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-medium transition-all cursor-pointer whitespace-nowrap border',
                activeRegion === reg.id
                  ? isFlyMode
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 shadow-xs font-semibold'
                    : 'bg-[#1B2432] text-white border-[#1B2432] shadow-xs font-semibold'
                  : isFlyMode
                  ? 'bg-slate-800/80 text-slate-300 border-slate-700/60 hover:bg-slate-700/60'
                  : 'bg-white/80 text-slate-600 border-[#E4DEC9] hover:bg-[#F2ECE1] hover:text-slate-900'
              )}
            >
              {reg.name}
            </button>
          ))}
        </div>

        {/* Right: Map Zoom & Reset Actions */}
        <div className="flex items-center gap-1 ml-auto">
          <div className="inline-flex rounded-lg bg-white/80 border border-[#E0D7C6] p-0.5 shadow-2xs">
            <button
              type="button"
              onClick={() => handleZoom('in')}
              title="Zoom In"
              className="p-1 rounded text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => handleZoom('out')}
              title="Zoom Out"
              className="p-1 rounded text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={handleResetZoom}
              title="Reset View"
              className="p-1 rounded text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* ── Status Telemetry Badges (Over Map) ── */}
      <div className="w-full flex items-center justify-between text-[10px] font-mono px-1 z-20 pointer-events-none">
        {/* Left: Real-time Ingestion Readout */}
        <div
          className={cn(
            'flex items-center gap-1.5 px-2 py-0.5 rounded-md backdrop-blur-xs border shadow-xs pointer-events-auto',
            isFlyMode
              ? 'bg-slate-900/90 text-slate-200 border-slate-700'
              : 'bg-white/90 text-slate-700 border-[#E8E2D4]'
          )}
        >
          <span
            className={cn(
              'w-2 h-2 rounded-full',
              connectOvi ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'
            )}
          />
          <span className="font-semibold">{zones.length} Verified Incidents</span>
          {geoCells.length > 0 && (
            <span className="text-slate-400">({geoCells.length} H3 Clusters)</span>
          )}
        </div>

        {/* Right: Radar/Fly Mode Active Telemetry */}
        {isFlyMode && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 shadow-xs pointer-events-auto">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            <span>DOPPLER SWEEP: 0.24 Hz ACTIVE</span>
          </div>
        )}
      </div>

      {/* ── Main Responsive India Risk SVG Map Canvas ── */}
      <div className="relative w-full flex-1 flex items-center justify-center min-h-[250px] overflow-hidden my-1">
        <svg
          viewBox={currentViewBox}
          className={cn(
            'w-full h-full max-h-[350px] sm:max-h-[380px] drop-shadow-sm transition-all duration-500 ease-out',
            isFlyMode && 'brightness-110 contrast-105'
          )}
          style={{ overflow: 'visible' }}
        >
          <defs>
            {/* India Boundary Clip Path */}
            <clipPath id="indiaSilhouetteClip">
              <path d={COMBINED_INDIA_PATH} />
            </clipPath>

            {/* India Landmass Drop Shadow */}
            <filter id="indiaShadow" x="-10%" y="-10%" width="120%" height="120%">
              <feDropShadow
                dx="0"
                dy="4"
                stdDeviation="6"
                floodColor={isFlyMode ? '#000000' : '#0F172A'}
                floodOpacity={isFlyMode ? 0.5 : 0.12}
              />
            </filter>

            {/* Thermal Diffusion Blur Filter for organic thermodynamic heat dissipation */}
            <filter id="thermalDiffusion" x="-25%" y="-25%" width="150%" height="150%">
              <feGaussianBlur stdDeviation="18" result="blur" />
            </filter>

            {/* National Baseline Atmospheric Gradient */}
            <linearGradient id="nationalAtmosphere" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor={isFlyMode ? '#101B2E' : '#F8FAFC'} stopOpacity="0.95" />
              <stop offset="35%" stopColor={isFlyMode ? '#0F172A' : '#F1F5F9'} stopOpacity="0.9" />
              <stop offset="70%" stopColor={isFlyMode ? '#0D1A30' : '#E2E8F0'} stopOpacity="0.8" />
              <stop offset="100%" stopColor={isFlyMode ? '#1E293B' : '#93C5FD'} stopOpacity={isFlyMode ? 0.85 : 0.45} />
            </linearGradient>

            {/* Fly Mode Radar Scan Gradient */}
            <linearGradient id="radarSweepGrad" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#10B981" stopOpacity="0.0" />
              <stop offset="70%" stopColor="#10B981" stopOpacity="0.12" />
              <stop offset="97%" stopColor="#10B981" stopOpacity="0.75" />
              <stop offset="100%" stopColor="#34D399" stopOpacity="0.95" />
            </linearGradient>

            {/* Radar Sweep Trailing Phosphor Glow */}
            <linearGradient id="trailingPhosphor" x1="0%" y1="100%" x2="0%" y2="0%">
              <stop offset="0%" stopColor="#059669" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#059669" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* ── 0. Tactical Coordinate Graticule Grid (HUD Styling) ── */}
          <g opacity={isFlyMode ? 0.25 : 0.15} stroke={isFlyMode ? '#38BDF8' : '#64748B'} strokeWidth="0.6">
            {/* Latitude Parallels */}
            <line x1="20" y1="140" x2="580" y2="140" strokeDasharray="3 5" />
            <text x="24" y="136" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">30°N</text>
            <line x1="20" y1="360" x2="580" y2="360" strokeDasharray="3 5" />
            <text x="24" y="356" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">20°N</text>
            <line x1="20" y1="560" x2="580" y2="560" strokeDasharray="3 5" />
            <text x="24" y="556" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">10°N</text>

            {/* Longitude Meridians */}
            <line x1="120" y1="20" x2="120" y2="660" strokeDasharray="3 5" />
            <text x="124" y="655" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">72°E</text>
            <line x1="280" y1="20" x2="280" y2="660" strokeDasharray="3 5" />
            <text x="284" y="655" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">80°E</text>
            <line x1="450" y1="20" x2="450" y2="660" strokeDasharray="3 5" />
            <text x="454" y="655" fill={isFlyMode ? '#38BDF8' : '#64748B'} fontSize="8" fontFamily="monospace">88°E</text>
          </g>

          {/* ── 1. Base Silhouette & Drop Shadow ── */}
          <path
            d={COMBINED_INDIA_PATH}
            fill={isFlyMode ? '#0B132B' : '#FAF8F5'}
            filter="url(#indiaShadow)"
          />

          {/* ── 2. Dynamic 100% Real-Data Driven Heatmap Layer (Clipped to India Silhouette) ── */}
          <g clipPath="url(#indiaSilhouetteClip)">
            {/* Baseline National Landmass Gradient */}
            <rect
              x="0"
              y="0"
              width="600"
              height="680"
              fill="url(#nationalAtmosphere)"
            />

            {/* Real Thermal Emission Contours synthesized with Gaussian Diffusion */}
            <g
              filter="url(#thermalDiffusion)"
              className={cn(connectOvi && 'transition-opacity duration-700')}
              opacity={connectOvi ? (isFlyMode ? 0.98 : 0.95) : 0.85}
              style={{ willChange: 'opacity, transform' }}
            >
              {thermalSpots.map((spot) => (
                <g key={spot.id}>
                  {/* Outer warm diffusion halo */}
                  <circle
                    cx={spot.x}
                    cy={spot.y}
                    r={spot.outerRadius}
                    fill={spot.outerColor}
                    opacity={spot.outerOpacity}
                  />
                  {/* Mid-temperature contour */}
                  <circle
                    cx={spot.x}
                    cy={spot.y}
                    r={spot.midRadius}
                    fill={spot.midColor}
                    opacity={spot.midOpacity}
                  />
                  {/* High-intensity thermal core */}
                  <circle
                    cx={spot.x}
                    cy={spot.y}
                    r={spot.coreRadius}
                    fill={spot.coreColor}
                    opacity={spot.coreOpacity}
                  />
                </g>
              ))}
            </g>

            {/* Fly / Radar Scan Beam Overlay */}
            {isFlyMode && (
              <g>
                {/* Trailing phosphor afterglow */}
                <rect
                  x="0"
                  y={Math.max(0, radarY - 75)}
                  width="600"
                  height="75"
                  fill="url(#trailingPhosphor)"
                />
                {/* Leading sweep wave */}
                <rect
                  x="0"
                  y={Math.max(0, radarY - 45)}
                  width="600"
                  height="45"
                  fill="url(#radarSweepGrad)"
                />
                {/* Razor beam line */}
                <line
                  x1="0"
                  y1={radarY}
                  x2="600"
                  y2={radarY}
                  stroke="#34D399"
                  strokeWidth="1.8"
                  strokeOpacity="0.9"
                />
              </g>
            )}
          </g>

          {/* ── 3. Internal State Boundaries with Dynamic Threat Tint ── */}
          <g>
            {INDIA_STATES.map((state) => {
              const stateKey = state.name.toLowerCase().replace(/[^a-z]/g, '');
              const threat = stateThreatMap.get(stateKey);
              const isHovered = hoveredState?.id === state.id;

              let fill = 'transparent';
              let stroke = isFlyMode ? '#334155' : '#64748B';
              let strokeWidth = 0.55;
              let strokeOpacity = isFlyMode ? 0.45 : 0.35;

              if (threat) {
                if (threat.level === 'critical') {
                  fill = isHovered
                    ? 'rgba(239, 68, 68, 0.32)'
                    : isFlyMode
                    ? 'rgba(239, 68, 68, 0.18)'
                    : 'rgba(239, 68, 68, 0.13)';
                  stroke = isHovered ? '#B91C1C' : '#DC2626';
                  strokeWidth = isHovered ? 1.6 : 0.95;
                  strokeOpacity = isHovered ? 0.98 : 0.75;
                } else if (threat.level === 'high') {
                  fill = isHovered
                    ? 'rgba(249, 115, 22, 0.28)'
                    : isFlyMode
                    ? 'rgba(249, 115, 22, 0.15)'
                    : 'rgba(249, 115, 22, 0.10)';
                  stroke = isHovered ? '#C2410C' : '#EA580C';
                  strokeWidth = isHovered ? 1.5 : 0.85;
                  strokeOpacity = isHovered ? 0.92 : 0.7;
                } else if (threat.level === 'medium') {
                  fill = isHovered
                    ? 'rgba(234, 179, 8, 0.24)'
                    : isFlyMode
                    ? 'rgba(234, 179, 8, 0.12)'
                    : 'rgba(234, 179, 8, 0.08)';
                  stroke = isHovered ? '#B45309' : '#D97706';
                  strokeWidth = isHovered ? 1.4 : 0.78;
                  strokeOpacity = isHovered ? 0.88 : 0.65;
                } else {
                  fill = isHovered
                    ? 'rgba(59, 130, 246, 0.20)'
                    : isFlyMode
                    ? 'rgba(59, 130, 246, 0.08)'
                    : 'rgba(59, 130, 246, 0.05)';
                  stroke = isHovered ? '#1D4ED8' : '#3B82F6';
                  strokeWidth = isHovered ? 1.3 : 0.68;
                  strokeOpacity = isHovered ? 0.82 : 0.58;
                }
              } else if (isHovered) {
                fill = isFlyMode ? 'rgba(51, 65, 85, 0.4)' : 'rgba(255, 255, 255, 0.38)';
                stroke = isFlyMode ? '#38BDF8' : '#1E293B';
                strokeWidth = 1.4;
                strokeOpacity = 0.9;
              }

              return (
                <path
                  key={state.id}
                  d={state.d}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  strokeOpacity={strokeOpacity}
                  className="transition-all duration-150 cursor-pointer"
                  onMouseEnter={() => setHoveredState(state)}
                  onMouseLeave={() => setHoveredState(null)}
                />
              );
            })}
          </g>

          {/* ── 4. Outer Boundary Definition ── */}
          <path
            d={COMBINED_INDIA_PATH}
            fill="none"
            stroke={isFlyMode ? '#475569' : '#334155'}
            strokeWidth="1.2"
            strokeOpacity={isFlyMode ? 0.75 : 0.65}
          />

          {/* ── 5. Sri Lanka Outline (Official Reference Geometry) ── */}
          <path
            d={SRI_LANKA_PATH}
            fill={isFlyMode ? '#0F172A' : '#F1F5F9'}
            stroke={isFlyMode ? '#334155' : '#64748B'}
            strokeWidth="0.8"
            strokeOpacity="0.75"
          />

          {/* ── 6. Interactive Risk Zone Incident Beacons ── */}
          <g>
            {projectedZones.map((zone) => {
              const isSelected = selectedZone?.id === zone.id;
              const isHovered = hoveredZone?.id === zone.id;

              const isCrit = zone.level === 'critical';
              const isHigh = zone.level === 'high';
              const isMed = zone.level === 'medium';

              const fillColor = isCrit
                ? '#DC2626'
                : isHigh
                ? '#F97316'
                : isMed
                ? '#EAB308'
                : '#3B82F6';

              const outerRadius = isCrit ? (isSelected ? 10 : 7.5) : isHigh ? 6.5 : 5;
              const innerRadius = isCrit ? (isSelected ? 4.5 : 3.4) : isHigh ? 3 : 2.4;

              // Check if radar sweep is near this beacon in fly mode
              const isRadarNear = isFlyMode && Math.abs(radarY - zone.svgY) < 25;

              return (
                <g
                  key={zone.id}
                  className="cursor-pointer transition-transform"
                  onClick={(e) => handleZoneClick(zone, e)}
                  onMouseEnter={() => setHoveredZone(zone)}
                  onMouseLeave={() => setHoveredZone(null)}
                >
                  {/* Radar Swept Ping Wave (Fly Mode) */}
                  {isRadarNear && (
                    <circle
                      cx={zone.svgX}
                      cy={zone.svgY}
                      r={outerRadius * 2.8}
                      fill="none"
                      stroke="#34D399"
                      strokeWidth="1.2"
                      className="animate-ping"
                      style={{
                        transformOrigin: `${zone.svgX}px ${zone.svgY}px`,
                        animationDuration: '1.2s',
                      }}
                    />
                  )}

                  {/* Pulsing Outer Aura for Critical, High, or Selected zones */}
                  {(isCrit || isHigh || isSelected) && (
                    <circle
                      cx={zone.svgX}
                      cy={zone.svgY}
                      r={outerRadius * 1.8}
                      fill={fillColor}
                      opacity={isSelected ? 0.6 : 0.35}
                      className={isCrit ? 'animate-ping' : undefined}
                      style={{
                        transformOrigin: `${zone.svgX}px ${zone.svgY}px`,
                        animationDuration: '2.4s',
                      }}
                    />
                  )}

                  {/* Beacon Core Dot */}
                  <circle
                    cx={zone.svgX}
                    cy={zone.svgY}
                    r={innerRadius}
                    fill={fillColor}
                    stroke="#FFFFFF"
                    strokeWidth={isCrit || isSelected ? 1.4 : 0.9}
                    className="transition-all duration-150 hover:scale-130"
                  />

                  {/* Target Acquisition Crosshair (When Selected) */}
                  {isSelected && (
                    <g stroke="#EF4444" strokeWidth="1.2" opacity="0.95">
                      <circle cx={zone.svgX} cy={zone.svgY} r={outerRadius * 2.2} fill="none" strokeDasharray="3 3" />
                      <line x1={zone.svgX - 16} y1={zone.svgY} x2={zone.svgX - 8} y2={zone.svgY} />
                      <line x1={zone.svgX + 8} y1={zone.svgY} x2={zone.svgX + 16} y2={zone.svgY} />
                      <line x1={zone.svgX} y1={zone.svgY - 16} x2={zone.svgX} y2={zone.svgY - 8} />
                      <line x1={zone.svgX} y1={zone.svgY + 8} x2={zone.svgX} y2={zone.svgY + 16} />
                    </g>
                  )}
                </g>
              );
            })}
          </g>

          {/* ── 7. Compass Rose & Scale Bar Indicator in Corner ── */}
          <g opacity={isFlyMode ? 0.6 : 0.45} transform="translate(540, 580)">
            <circle cx="15" cy="15" r="14" fill={isFlyMode ? '#0F172A' : '#FFFFFF'} stroke={isFlyMode ? '#38BDF8' : '#475569'} strokeWidth="0.8" />
            <path d="M15,5 L18,15 L15,13 L12,15 Z" fill="#EF4444" />
            <path d="M15,25 L18,15 L15,17 L12,15 Z" fill={isFlyMode ? '#94A3B8' : '#475569'} />
            <text x="15" y="4" textAnchor="middle" fill="#EF4444" fontSize="7" fontWeight="bold" fontFamily="sans-serif">N</text>
          </g>
        </svg>
      </div>

      {/* ── Bottom HUD Footer: Scale Bar & Mode Info ── */}
      <div className="w-full flex items-center justify-between text-[9px] font-mono text-slate-500 px-1 pt-1 border-t border-[#F0EBE0]/80">
        <div className="flex items-center gap-2">
          <span>SOI Official Geometry (WGS84)</span>
          <span className="text-slate-300">•</span>
          <span>Max Lat: 37.08°N</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-12 h-1 bg-slate-300 rounded-full flex items-center">
            <div className="w-6 h-full bg-slate-600 rounded-l-full" />
          </div>
          <span>500 km</span>
        </div>
      </div>

      {/* ── Floating Tooltip / Popover for State or Zone Hover ── */}
      <AnimatePresence>
        {(hoveredZone || hoveredState) && tooltipPos && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.12 }}
            style={{
              position: 'absolute',
              left: Math.min(Math.max(tooltipPos.x - 70, 10), (containerRef.current?.clientWidth || 300) - 190),
              top: Math.max(tooltipPos.y - 80, 10),
              pointerEvents: 'none',
            }}
            className={cn(
              'z-30 px-2.5 py-1.5 rounded-lg shadow-xl text-xs font-sans border backdrop-blur-xs min-w-[160px]',
              isFlyMode
                ? 'bg-slate-900/95 text-white border-slate-700'
                : 'bg-slate-900/95 text-white border-slate-700'
            )}
          >
            {hoveredZone ? (
              <div>
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="font-bold text-white tracking-tight">{hoveredZone.name}</span>
                  <span
                    className={cn(
                      'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold uppercase',
                      hoveredZone.level === 'critical' && 'bg-red-500/20 text-red-400 border border-red-500/30',
                      hoveredZone.level === 'high' && 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
                      hoveredZone.level === 'medium' && 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
                      hoveredZone.level === 'low' && 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    )}
                  >
                    {hoveredZone.level}
                  </span>
                </div>
                <div className="text-[10px] text-slate-300">{hoveredZone.hazard}</div>
                <div className="text-[9px] text-slate-400 font-mono mt-0.5 flex items-center justify-between">
                  <span>{hoveredZone.state}</span>
                  <span>{hoveredZone.reportsCount} field reports</span>
                </div>
              </div>
            ) : hoveredState ? (
              <div>
                {(() => {
                  const stateKey = hoveredState.name.toLowerCase().replace(/[^a-z]/g, '');
                  const threat = stateThreatMap.get(stateKey);
                  return (
                    <>
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="font-bold text-white tracking-tight">{hoveredState.name}</span>
                        <span
                          className={cn(
                            'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold uppercase',
                            threat?.level === 'critical' && 'bg-red-500/20 text-red-400 border border-red-500/30',
                            threat?.level === 'high' && 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
                            threat?.level === 'medium' && 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
                            threat?.level === 'low' && 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
                            !threat && 'bg-slate-700/60 text-slate-300 border border-slate-600'
                          )}
                        >
                          {threat ? threat.level : 'NORMAL'}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-300">
                        {threat ? threat.primaryHazard : 'Baseline Atmospheric Conditions'}
                      </div>
                      <div className="text-[9px] text-slate-400 font-mono mt-0.5">
                        {threat
                          ? `${threat.eventsCount} verified disaster events • ${threat.totalReports} reports`
                          : 'Continuous IMD Doppler & State EOC feed active'}
                      </div>
                    </>
                  );
                })()}
              </div>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Active Zone Tactical Inspection Drawer (when beacon pinned) ── */}
      <AnimatePresence>
        {selectedZone && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className={cn(
              'absolute bottom-2 left-2 right-2 z-30 p-2.5 rounded-lg shadow-lg border backdrop-blur-md flex items-center justify-between gap-3',
              isFlyMode
                ? 'bg-slate-900/95 text-white border-slate-700'
                : 'bg-white/95 text-slate-900 border-[#E8E2D4]'
            )}
          >
            <div className="flex items-center gap-2.5 overflow-hidden">
              <span
                className={cn(
                  'w-3 h-3 rounded-full flex-shrink-0 animate-pulse',
                  selectedZone.level === 'critical' && 'bg-red-500',
                  selectedZone.level === 'high' && 'bg-orange-500',
                  selectedZone.level === 'medium' && 'bg-amber-500',
                  selectedZone.level === 'low' && 'bg-blue-500'
                )}
              />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-xs truncate">{selectedZone.name}</span>
                  <span
                    className={cn(
                      'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold uppercase flex-shrink-0',
                      selectedZone.level === 'critical' && 'bg-red-100 text-red-700 border border-red-200',
                      selectedZone.level === 'high' && 'bg-orange-100 text-orange-700 border border-orange-200',
                      selectedZone.level === 'medium' && 'bg-amber-100 text-amber-700 border border-amber-200',
                      selectedZone.level === 'low' && 'bg-blue-100 text-blue-700 border border-blue-200'
                    )}
                  >
                    {selectedZone.level}
                  </span>
                </div>
                <div className="text-[10px] text-slate-500 flex items-center gap-2 font-mono">
                  <span>{selectedZone.hazard}</span>
                  <span>•</span>
                  <span>{selectedZone.state}</span>
                  <span>•</span>
                  <span>{selectedZone.reportsCount} Corroborating Reports</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5 flex-shrink-0">
              <a
                href={`/events/${selectedZone.id.replace('live-ev-', '')}`}
                className="px-2.5 py-1 rounded-md bg-[#1B2432] text-white hover:bg-black transition-colors text-[10px] font-semibold flex items-center gap-1 cursor-pointer"
              >
                <span>Inspect</span>
                <ExternalLink className="w-3 h-3" />
              </a>
              <button
                type="button"
                onClick={() => {
                  setSelectedZone(null);
                  onZoneSelect?.(null);
                }}
                className="p-1 rounded text-slate-400 hover:text-slate-700 transition-colors text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
