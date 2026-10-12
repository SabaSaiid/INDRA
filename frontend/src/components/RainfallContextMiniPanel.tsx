'use client';

/**
 * RainfallContextMiniPanel
 *
 * Tab 5 — Hazard Trends (Panel D).
 * Contextualizes hazard event counts against real-time rainfall station readings.
 * Displays:
 *   - Heavy+ alert count (stations ≥ 64.5 mm)
 *   - Maximum recorded rainfall reading
 *   - Monitored stations count
 *   - IMD intensity breakdown bar (Very light / Light / Moderate / Heavy / Very heavy / Extremely heavy)
 *   - City station status pills
 *
 * Data source: GET /api/geo/stations (fetchStations)
 */

import React, { useEffect, useState, useMemo } from 'react';
import { CloudRain, Droplets, Gauge, AlertCircle } from 'lucide-react';
import { fetchStations, type RainfallStation, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useSettings, formatRainfall } from '@/lib/useSettings';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { formatAgo, formatIst } from '@/lib/utils';

// IMD Classification
const IMD_CLASSES = [
  { key: 'very_light', label: 'Very Light / Dry', min: 0,     max: 2.5,   color: '#94A3B8' },
  { key: 'light',      label: 'Light',            min: 2.5,   max: 15.6,  color: '#60A5FA' },
  { key: 'moderate',   label: 'Moderate',         min: 15.6,  max: 64.5,  color: '#2563EB' },
  { key: 'heavy',      label: 'Heavy',            min: 64.5,  max: 115.6, color: '#F59E0B' },
  { key: 'very_heavy', label: 'Very Heavy',       min: 115.6, max: 204.5, color: '#EA580C' },
  { key: 'extreme',    label: 'Extremely Heavy',  min: 204.5, max: 99999, color: '#DC2626' },
] as const;

function getImdClass(mm: number | null) {
  if (mm == null) return null;
  return IMD_CLASSES.find((c) => mm >= c.min && mm < c.max) ?? IMD_CLASSES[IMD_CLASSES.length - 1];
}

interface StationStats {
  heavyCount: number;
  maxReading: number | null;
  maxStation: RainfallStation | null;
  distribution: Record<string, number>;
  total: number;
}

export default function RainfallContextMiniPanel({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const [stations, setStations] = useState<RainfallStation[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchStations()
      .then((rows) => { if (!cancelled) { setStations(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Calculations
  const stats = useMemo<StationStats | null>(() => {
    if (!stations || stations.length === 0) return null;

    let heavyCount = 0;
    let maxReading = -1;
    let maxStation: RainfallStation | null = null;
    const distribution: Record<string, number> = {
      very_light: 0,
      light: 0,
      moderate: 0,
      heavy: 0,
      very_heavy: 0,
      extreme: 0,
    };

    for (const st of stations) {
      const val = st.rainfall_mm;
      if (val != null) {
        if (val >= 64.5) heavyCount += 1;
        if (val > maxReading) {
          maxReading = val;
          maxStation = st;
        }
        const cls = getImdClass(val);
        if (cls) distribution[cls.key] += 1;
      }
    }

    return {
      heavyCount,
      maxReading: maxReading >= 0 ? maxReading : null,
      maxStation,
      distribution,
      total: stations.length,
    };
  }, [stations]);

  // Loading
  if (!stations && !error) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <div className="h-44 animate-pulse bg-[#F0EBE0] rounded-xl" />
      </div>
    );
  }

  // Error
  if (error && !stations) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <ErrorState
          label="rainfall station context"
          error={error instanceof ApiError && error.status === 404 ? 'GET /api/geo/stations not found' : error}
          compact
        />
      </div>
    );
  }

  // Empty
  if (stations && stations.length === 0) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <EmptyState title="No rainfall station data available" compact />
      </div>
    );
  }

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3
            className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            <CloudRain className="w-4 h-4 text-blue-500" />
            {t('analytics.hazard_rainfall_title') || 'Rainfall Ground Context'}
          </h3>
          <p className="text-[11px] text-[#7A8599] mt-0.5">
            Real-time weather station metrics contextualizing hydrometeorological hazard events
          </p>
        </div>
        <span className="text-[10px] font-mono text-[#7A8599] shrink-0">
          Open-Meteo · every 10 min
        </span>
      </div>

      {/* 3 Metric Cards */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Card 1: Heavy / Extreme stations */}
          <div className="bg-[#F7F3EA] rounded-xl p-3.5 border border-[#E8E2D4] flex items-center justify-between">
            <div>
              <div className="text-[10px] font-medium text-[#7A8599] uppercase tracking-wide">
                Heavy+ Stations (≥ 64.5 mm)
              </div>
              <div
                className={`text-2xl font-bold font-mono mt-0.5 ${
                  stats.heavyCount > 0 ? 'text-[#DC2626]' : 'text-[#1B2432]'
                }`}
              >
                {stats.heavyCount} <span className="text-xs font-sans text-[#7A8599]">of {stats.total}</span>
              </div>
              <div className="text-[10px] text-[#7A8599] mt-0.5">
                {stats.heavyCount > 0 ? 'Significant inundation risk' : 'No severe rainfall flagged'}
              </div>
            </div>
            <AlertCircle className={`w-6 h-6 shrink-0 ${stats.heavyCount > 0 ? 'text-red-500' : 'text-slate-400'}`} />
          </div>

          {/* Card 2: Maximum Reading */}
          <div className="bg-[#F7F3EA] rounded-xl p-3.5 border border-[#E8E2D4] flex items-center justify-between">
            <div className="min-w-0">
              <div className="text-[10px] font-medium text-[#7A8599] uppercase tracking-wide">
                Peak Rainfall Recorded
              </div>
              <div
                className="text-2xl font-bold font-mono text-[#1B2432] mt-0.5 truncate"
                title={stats.maxStation?.station_name}
              >
                {stats.maxReading != null ? formatRainfall(stats.maxReading, settings.rainUnit) : '—'}
              </div>
              <div className="text-[10px] text-[#7A8599] truncate mt-0.5" title={stats.maxStation?.station_name}>
                {stats.maxStation ? `${stats.maxStation.station_name}` : 'No active reading'}
              </div>
            </div>
            <Gauge className="w-6 h-6 text-blue-500 shrink-0" />
          </div>

          {/* Card 3: Active Monitoring Network */}
          <div className="bg-[#F7F3EA] rounded-xl p-3.5 border border-[#E8E2D4] flex items-center justify-between">
            <div>
              <div className="text-[10px] font-medium text-[#7A8599] uppercase tracking-wide">
                Monitored Met Stations
              </div>
              <div className="text-2xl font-bold font-mono text-[#1B2432] mt-0.5">
                {stats.total}
              </div>
              <div className="text-[10px] text-[#7A8599] mt-0.5">
                {stations?.[0] ? `Updated ${formatAgo(stations[0].recorded_at)}` : 'Live telemetries'}
              </div>
            </div>
            <Droplets className="w-6 h-6 text-indigo-500 shrink-0" />
          </div>
        </div>
      )}

      {/* IMD Intensity Distribution Segmented Bar */}
      {stats && (
        <div className="bg-[#F7F3EA] rounded-xl p-3.5 border border-[#E8E2D4]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-[#1B2432]">
              IMD Intensity Classification Across Stations
            </span>
            <span className="text-[10px] text-[#7A8599]">
              {stats.total} stations reporting
            </span>
          </div>

          {/* Segmented bar */}
          <div className="h-3 rounded-full bg-[#E8E2D4] overflow-hidden flex">
            {IMD_CLASSES.map((cls) => {
              const count = stats.distribution[cls.key] || 0;
              const pct = (count / stats.total) * 100;
              if (pct === 0) return null;
              return (
                <div
                  key={cls.key}
                  style={{ width: `${pct}%`, backgroundColor: cls.color }}
                  title={`${cls.label}: ${count} stations (${pct.toFixed(0)}%)`}
                  className="transition-all duration-300"
                />
              );
            })}
          </div>

          {/* Legend pills */}
          <div className="flex flex-wrap items-center gap-3 mt-2.5">
            {IMD_CLASSES.map((cls) => {
              const count = stats.distribution[cls.key] || 0;
              return (
                <div key={cls.key} className="flex items-center gap-1.5 text-[10px]">
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: cls.color }}
                  />
                  <span className="text-[#4A5568]">{cls.label}:</span>
                  <span className="font-mono font-semibold text-[#1B2432]">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Station readings pills */}
      <div className="flex flex-wrap gap-2 pt-1 border-t border-[#E8E2D4]">
        {(stations ?? []).map((st) => {
          const cls = getImdClass(st.rainfall_mm);
          return (
            <div
              key={st.station_code}
              className="bg-[#F7F3EA] border border-[#E8E2D4] rounded-lg px-2.5 py-1 flex items-center gap-2 text-xs"
            >
              <span className="font-medium text-[#1B2432] truncate max-w-[120px]" title={st.station_name}>
                {st.station_name}
              </span>
              <span
                className="font-mono font-bold text-[11px] px-1.5 py-0.5 rounded"
                style={{
                  color: cls?.color ?? '#94A3B8',
                  backgroundColor: `${cls?.color ?? '#94A3B8'}18`,
                }}
              >
                {st.rainfall_mm != null ? formatRainfall(st.rainfall_mm, settings.rainUnit) : '—'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
