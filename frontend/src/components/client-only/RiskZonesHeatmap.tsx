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
import {
  Radio,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Info,
  Maximize2,
  Compass,
  RotateCcw,
  Sparkles,
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
  activeFilter?: 'all' | 'critical' | 'high' | 'medium' | 'low';
  viewMode?: 'severity' | 'fly';
  connectOvi?: boolean;
  onZoneSelect?: (zone: RiskZoneFeature | null) => void;
  className?: string;
}

export default function RiskZonesHeatmap({
  zones,
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
  const [radarAngle, setRadarAngle] = useState(0);

  // Radar sweep animation when in "Fly / Real" mode
  useEffect(() => {
    if (viewMode !== 'fly') return;
    let animId: number;
    let start: number | null = null;

    const animate = (timestamp: number) => {
      if (!start) start = timestamp;
      const elapsed = timestamp - start;
      // Cycle every 4.5 seconds
      const progress = (elapsed % 4500) / 4500;
      setRadarAngle(progress * 100);
      animId = requestAnimationFrame(animate);
    };

    animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, [viewMode]);

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

  // Handle click on zone beacon
  const handleZoneClick = (z: RiskZoneFeature, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = selectedZone?.id === z.id ? null : z;
    setSelectedZone(next);
    onZoneSelect?.(next);
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

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      className={cn(
        'relative w-full h-full min-h-[300px] flex items-center justify-center select-none overflow-hidden rounded-xl bg-gradient-to-b from-[#FAF8F5] to-[#F3EFE8]/70 border border-[#E8E2D4]/60 p-1 sm:p-2',
        className
      )}
    >
      {/* ── Top-right Fly / Radar Telemetry Badge (when fly active) ── */}
      {viewMode === 'fly' && (
        <div className="absolute top-2 right-2 z-20 flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-900/90 text-white text-[10px] font-mono shadow-sm backdrop-blur-xs border border-slate-700">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
          <span>RADAR: DOPPLER SWEEP (0.22Hz)</span>
        </div>
      )}

      {/* ── Main Responsive India Risk SVG Map ── */}
      <svg
        viewBox={INDIA_MAP_VIEWBOX}
        className={cn(
          'w-full h-full max-h-[360px] sm:max-h-[390px] drop-shadow-sm transition-transform duration-300',
          viewMode === 'fly' && 'scale-[1.02]'
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
            <feDropShadow dx="0" dy="3" stdDeviation="5" floodColor="#0F172A" floodOpacity="0.12" />
          </filter>

          {/* ── Heatmap Color Gradients (Matching the Reference Screenshot) ── */}
          
          {/* 1. Southern Peninsula Blue Base */}
          <linearGradient id="southBlueGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#FEF08A" stopOpacity="0.55" />
            <stop offset="35%" stopColor="#93C5FD" stopOpacity="0.8" />
            <stop offset="65%" stopColor="#60A5FA" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.9" />
          </linearGradient>

          {/* 2. Primary Gangetic Plains Heat Core (Red -> Orange -> Yellow -> Blue fade) */}
          <radialGradient id="gangeticHeat" cx="46%" cy="34%" r="44%" fx="46%" fy="34%">
            <stop offset="0%" stopColor="#DC2626" stopOpacity="0.95" />
            <stop offset="28%" stopColor="#EF4444" stopOpacity="0.92" />
            <stop offset="52%" stopColor="#F97316" stopOpacity="0.88" />
            <stop offset="74%" stopColor="#EAB308" stopOpacity="0.82" />
            <stop offset="94%" stopColor="#60A5FA" stopOpacity="0.1" />
            <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.0" />
          </radialGradient>

          {/* 3. Northern Sub-pocket (Himachal / Punjab slope) */}
          <radialGradient id="northHeat" cx="35%" cy="19%" r="13%" fx="35%" fy="19%">
            <stop offset="0%" stopColor="#DC2626" stopOpacity="0.95" />
            <stop offset="55%" stopColor="#F97316" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#F97316" stopOpacity="0.0" />
          </radialGradient>

          {/* 4. Assam / Northeast Warm Flare */}
          <radialGradient id="northeastHeat" cx="81%" cy="36%" r="20%" fx="81%" fy="36%">
            <stop offset="0%" stopColor="#F59E0B" stopOpacity="0.88" />
            <stop offset="55%" stopColor="#EAB308" stopOpacity="0.65" />
            <stop offset="100%" stopColor="#E2E8F0" stopOpacity="0.0" />
          </radialGradient>

          {/* 5. Smooth J&K Neutral Wash Fade */}
          <linearGradient id="northNeutralFade" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#E2E8F0" stopOpacity="0.75" />
            <stop offset="14%" stopColor="#E2E8F0" stopOpacity="0.5" />
            <stop offset="26%" stopColor="#EF4444" stopOpacity="0.0" />
          </linearGradient>

          {/* Real-time Breathing Glow Filter */}
          {connectOvi && (
            <filter id="liveGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          )}

          {/* Fly Mode Radar Scan Gradient */}
          <linearGradient id="radarSweepGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#10B981" stopOpacity="0.0" />
            <stop offset="70%" stopColor="#10B981" stopOpacity="0.15" />
            <stop offset="98%" stopColor="#10B981" stopOpacity="0.75" />
            <stop offset="100%" stopColor="#34D399" stopOpacity="0.9" />
          </linearGradient>
        </defs>

        {/* ── 1. Base Silhouette & Drop Shadow ── */}
        <path
          d={COMBINED_INDIA_PATH}
          fill="#FAF8F5"
          filter="url(#indiaShadow)"
        />

        {/* ── 2. Regional Risk Heatmap Contours (Clipped to India Silhouette) ── */}
        <g clipPath="url(#indiaSilhouetteClip)">
          {/* Base South Peninsula Cool Blue */}
          <rect
            x="0"
            y="0"
            width="600"
            height="680"
            fill="url(#southBlueGrad)"
            className={cn(connectOvi && 'transition-opacity duration-1000')}
          />

          {/* Gangetic Core: Crimson / Red / Orange / Golden Heat Contours */}
          <rect
            x="0"
            y="0"
            width="600"
            height="680"
            fill="url(#gangeticHeat)"
            className={cn(connectOvi && 'animate-pulse')}
            style={{ animationDuration: '4s' }}
          />

          {/* Northern Himalayan High-Risk Sub-Pocket */}
          <rect
            x="0"
            y="0"
            width="600"
            height="680"
            fill="url(#northHeat)"
          />

          {/* Northeast / Assam Monsoon Inundation Flare */}
          <rect
            x="0"
            y="0"
            width="600"
            height="680"
            fill="url(#northeastHeat)"
          />

          {/* Smooth Northern Neutral Wash (Ladakh / J&K) */}
          <rect
            x="0"
            y="0"
            width="600"
            height="680"
            fill="url(#northNeutralFade)"
          />

          {/* Fly / Radar Scan Beam Overlay */}
          {viewMode === 'fly' && (
            <g>
              <rect
                x="0"
                y={`${radarAngle * 6.5 - 80}`}
                width="600"
                height="80"
                fill="url(#radarSweepGrad)"
              />
              <line
                x1="0"
                y1={`${radarAngle * 6.5}`}
                x2="600"
                y2={`${radarAngle * 6.5}`}
                stroke="#10B981"
                strokeWidth="1.8"
                strokeOpacity="0.85"
              />
            </g>
          )}
        </g>

        {/* ── 3. Internal State Boundaries ── */}
        <g fill="none">
          {INDIA_STATES.map((state) => {
            const isHovered = hoveredState?.id === state.id;
            return (
              <path
                key={state.id}
                d={state.d}
                stroke={isHovered ? '#1E293B' : '#475569'}
                strokeWidth={isHovered ? 1.6 : 0.75}
                strokeOpacity={isHovered ? 0.9 : 0.45}
                fill={isHovered ? 'rgba(255, 255, 255, 0.35)' : 'transparent'}
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
          stroke="#334155"
          strokeWidth="1.15"
          strokeOpacity="0.65"
        />

        {/* ── 5. Sri Lanka Outline (Matching Reference Image) ── */}
        <path
          d={SRI_LANKA_PATH}
          fill="#F1F5F9"
          stroke="#64748B"
          strokeWidth="0.8"
          strokeOpacity="0.75"
        />

        {/* ── 6. Interactive Risk Zone Beacons ── */}
        <g>
          {projectedZones.map((zone) => {
            const isSelected = selectedZone?.id === zone.id;
            const isHovered = hoveredZone?.id === zone.id;

            // Colors based on risk level
            const isCrit = zone.level === 'critical';
            const isHigh = zone.level === 'high';
            const isMed = zone.level === 'medium';
            const isLow = zone.level === 'low';

            const fillColor = isCrit
              ? '#DC2626'
              : isHigh
              ? '#F97316'
              : isMed
              ? '#EAB308'
              : '#3B82F6';

            const outerRadius = isCrit ? (isSelected ? 9 : 7) : isHigh ? 6 : 4.5;
            const innerRadius = isCrit ? (isSelected ? 4 : 3.2) : isHigh ? 2.8 : 2.2;

            return (
              <g
                key={zone.id}
                className="cursor-pointer transition-transform"
                onClick={(e) => handleZoneClick(zone, e)}
                onMouseEnter={() => setHoveredZone(zone)}
                onMouseLeave={() => setHoveredZone(null)}
              >
                {/* Pulsing Outer Ring for Critical and High zones */}
                {(isCrit || isHigh || isSelected) && (
                  <circle
                    cx={zone.svgX}
                    cy={zone.svgY}
                    r={outerRadius * 1.8}
                    fill={fillColor}
                    opacity={isSelected ? 0.5 : 0.3}
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
                  strokeWidth={isCrit || isSelected ? 1.2 : 0.8}
                  className="transition-all duration-150 hover:scale-125"
                />
              </g>
            );
          })}
        </g>
      </svg>

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
              left: Math.min(Math.max(tooltipPos.x - 70, 10), (containerRef.current?.clientWidth || 300) - 180),
              top: Math.max(tooltipPos.y - 75, 10),
              pointerEvents: 'none',
            }}
            className="z-30 px-2.5 py-1.5 rounded-lg bg-slate-900/95 text-white shadow-xl text-xs font-sans border border-slate-700 backdrop-blur-xs min-w-[150px]"
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
                  <span>{hoveredZone.reportsCount} reports</span>
                </div>
              </div>
            ) : hoveredState ? (
              <div>
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="font-bold text-white tracking-tight">{hoveredState.name}</span>
                  <span
                    className={cn(
                      'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold uppercase',
                      hoveredState.level === 'critical' && 'bg-red-500/20 text-red-400 border border-red-500/30',
                      hoveredState.level === 'high' && 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
                      hoveredState.level === 'medium' && 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
                      hoveredState.level === 'low' && 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    )}
                  >
                    {hoveredState.level}
                  </span>
                </div>
                <div className="text-[10px] text-slate-300">{hoveredState.hazard}</div>
                <div className="text-[9px] text-slate-400 font-mono mt-0.5">
                  {hoveredState.alerts} active district alerts
                </div>
              </div>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Active Zone Selection Badge (if pinned) ── */}
      {selectedZone && (
        <div className="absolute bottom-2 left-2 z-20 flex items-center gap-2 px-2.5 py-1 rounded-md bg-white/95 text-slate-800 text-[11px] shadow-sm border border-[#E8E2D4]">
          <span
            className={cn(
              'w-2 h-2 rounded-full',
              selectedZone.level === 'critical' && 'bg-red-500',
              selectedZone.level === 'high' && 'bg-orange-500',
              selectedZone.level === 'medium' && 'bg-amber-500',
              selectedZone.level === 'low' && 'bg-blue-500'
            )}
          />
          <span className="font-semibold">{selectedZone.name}</span>
          <span className="text-slate-400 font-mono">({selectedZone.hazard})</span>
          <button
            type="button"
            onClick={() => {
              setSelectedZone(null);
              onZoneSelect?.(null);
            }}
            className="text-slate-400 hover:text-slate-700 ml-1 text-xs"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
