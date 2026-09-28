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
  const [radarAngle, setRadarAngle] = useState(0);

  // Radar sweep animation when in "Fly / Real" mode
  useEffect(() => {
    if (viewMode !== 'fly') return;
    let animId: number;
    let start: number | null = null;

    const animate = (timestamp: number) => {
      if (!start) start = timestamp;
      const elapsed = timestamp - start;
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

  // Real dynamic thermal spots from geoCells (H3 report density) and zones (verified events)
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

    // 1. Process real H3 report clusters (from raw_reports)
    if (geoCells && geoCells.length > 0) {
      const maxCount = Math.max(...geoCells.map((c) => c.report_count), 1);
      geoCells.forEach((cell, idx) => {
        const [x, y] = projectCoordinates(cell.lng, cell.lat);
        if (x < 10 || x > 590 || y < 10 || y > 670) return;

        const ratio = cell.report_count / maxCount;
        const isDense = ratio > 0.35;
        const isMed = ratio > 0.12;

        spots.push({
          id: `h3-${cell.h3 || idx}`,
          x,
          y,
          outerRadius: Math.round(26 + ratio * 36),
          midRadius: Math.round(15 + ratio * 22),
          coreRadius: Math.round(7 + ratio * 14),
          coreColor: isDense ? '#EF4444' : isMed ? '#F97316' : '#EAB308',
          midColor: isDense ? '#F97316' : '#EAB308',
          outerColor: isDense ? '#FBBF24' : '#60A5FA',
          coreOpacity: Math.min(0.95, 0.45 + ratio * 0.5),
          midOpacity: Math.min(0.75, 0.3 + ratio * 0.4),
          outerOpacity: Math.min(0.45, 0.15 + ratio * 0.25),
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
        outerRadius: isCrit ? 58 : isHigh ? 44 : isMed ? 32 : 22,
        midRadius: isCrit ? 34 : isHigh ? 26 : isMed ? 18 : 13,
        coreRadius: isCrit ? 16 : isHigh ? 12 : isMed ? 8 : 5,
        coreColor: isCrit ? '#DC2626' : isHigh ? '#F97316' : isMed ? '#EAB308' : '#3B82F6',
        midColor: isCrit ? '#F97316' : isHigh ? '#F59E0B' : isMed ? '#FBBF24' : '#60A5FA',
        outerColor: isCrit ? '#F59E0B' : isHigh ? '#FBBF24' : '#93C5FD',
        coreOpacity: isCrit ? 0.92 : isHigh ? 0.8 : isMed ? 0.65 : 0.45,
        midOpacity: isCrit ? 0.7 : isHigh ? 0.55 : isMed ? 0.45 : 0.3,
        outerOpacity: isCrit ? 0.4 : isHigh ? 0.3 : isMed ? 0.2 : 0.15,
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

      {/* ── Live Data Status Indicator ── */}
      <div className="absolute top-2 left-2 z-20 flex items-center gap-1.5 px-2 py-0.8 rounded-md bg-white/90 text-slate-700 text-[10px] font-mono shadow-xs border border-[#E8E2D4]">
        <span className={cn("w-1.5 h-1.5 rounded-full", connectOvi ? "bg-emerald-500 animate-pulse" : "bg-slate-400")} />
        <span className="font-semibold">{zones.length} Verified Incidents</span>
        {geoCells.length > 0 && (
          <span className="text-slate-400">({geoCells.length} H3 Clusters)</span>
        )}
      </div>

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

          {/* Thermal Diffusion Blur Filter for organic heat dissipation */}
          <filter id="thermalDiffusion" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="20" result="blur" />
          </filter>

          {/* National Baseline Atmospheric Gradient */}
          <linearGradient id="nationalAtmosphere" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#F8FAFC" stopOpacity="0.9" />
            <stop offset="35%" stopColor="#F1F5F9" stopOpacity="0.8" />
            <stop offset="65%" stopColor="#E2E8F0" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#93C5FD" stopOpacity="0.4" />
          </linearGradient>

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
            className={cn(connectOvi && 'transition-opacity duration-1000')}
            opacity={connectOvi ? 0.95 : 0.85}
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

        {/* ── 3. Internal State Boundaries with Dynamic Threat Tint ── */}
        <g>
          {INDIA_STATES.map((state) => {
            const stateKey = state.name.toLowerCase().replace(/[^a-z]/g, '');
            const threat = stateThreatMap.get(stateKey);
            const isHovered = hoveredState?.id === state.id;

            let fill = 'transparent';
            let stroke = '#64748B';
            let strokeWidth = 0.55;
            let strokeOpacity = 0.35;

            if (threat) {
              if (threat.level === 'critical') {
                fill = isHovered ? 'rgba(239, 68, 68, 0.28)' : 'rgba(239, 68, 68, 0.12)';
                stroke = isHovered ? '#B91C1C' : '#DC2626';
                strokeWidth = isHovered ? 1.5 : 0.85;
                strokeOpacity = isHovered ? 0.95 : 0.7;
              } else if (threat.level === 'high') {
                fill = isHovered ? 'rgba(249, 115, 22, 0.24)' : 'rgba(249, 115, 22, 0.09)';
                stroke = isHovered ? '#C2410C' : '#EA580C';
                strokeWidth = isHovered ? 1.4 : 0.8;
                strokeOpacity = isHovered ? 0.9 : 0.65;
              } else if (threat.level === 'medium') {
                fill = isHovered ? 'rgba(234, 179, 8, 0.20)' : 'rgba(234, 179, 8, 0.07)';
                stroke = isHovered ? '#B45309' : '#D97706';
                strokeWidth = isHovered ? 1.3 : 0.75;
                strokeOpacity = isHovered ? 0.85 : 0.6;
              } else {
                fill = isHovered ? 'rgba(59, 130, 246, 0.18)' : 'rgba(59, 130, 246, 0.05)';
                stroke = isHovered ? '#1D4ED8' : '#3B82F6';
                strokeWidth = isHovered ? 1.2 : 0.65;
                strokeOpacity = isHovered ? 0.8 : 0.55;
              }
            } else if (isHovered) {
              fill = 'rgba(255, 255, 255, 0.35)';
              stroke = '#1E293B';
              strokeWidth = 1.3;
              strokeOpacity = 0.85;
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
          stroke="#334155"
          strokeWidth="1.15"
          strokeOpacity="0.65"
        />

        {/* ── 5. Sri Lanka Outline (Official Reference Geometry) ── */}
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
