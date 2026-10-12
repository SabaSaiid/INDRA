'use client';

/**
 * HazardTrendChart
 *
 * Tab 5 — Hazard Trends.
 * Grouped bar chart showing event counts per hazard type across three
 * time windows: 24h, 7d, 30d.
 *
 * Uses three parallel fetchEventDistribution() calls (existing API).
 * This is an honest 3-point snapshot — no time-series interpolation.
 *
 * Data source: GET /api/events/distribution?by=hazard&time_range=<window>
 */

import React, { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import { fetchEventDistribution, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

const BAR_24H  = '#2563EB';
const BAR_7D   = '#8B5CF6';
const BAR_30D  = '#F59E0B';

function HazardTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 text-white text-xs rounded-xl px-3 py-2 shadow-xl border border-slate-700 min-w-[170px]">
      <div className="font-bold mb-1.5 text-cyan-300">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} className="flex justify-between gap-4 items-center">
          <span className="flex items-center gap-1.5 text-slate-300">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-mono tabular-nums">{p.value ?? 0}</span>
        </div>
      ))}
    </div>
  );
}

export default function HazardTrendChart({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [data24, setData24] = useState<any[] | null>(null);
  const [data7,  setData7]  = useState<any[] | null>(null);
  const [data30, setData30] = useState<any[] | null>(null);
  const [error,  setError]  = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchEventDistribution('hazard', '24h'),
      fetchEventDistribution('hazard', '7d'),
      fetchEventDistribution('hazard', '30d'),
    ])
      .then(([d24, d7, d30]) => {
        if (!cancelled) {
          setData24(d24);
          setData7(d7);
          setData30(d30);
          setError(null);
        }
      })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Merge all three windows into a single data array keyed by hazard name
  const chartData = useMemo(() => {
    if (!data24 || !data7 || !data30) return null;
    // Collect all unique hazard names across all windows
    const names = new Set<string>([
      ...data24.map((d) => d.name),
      ...data7.map((d) => d.name),
      ...data30.map((d) => d.name),
    ]);
    const lookup = (arr: any[], name: string) =>
      arr.find((d) => d.name === name)?.value ?? 0;

    return Array.from(names)
      .map((name) => ({
        name: t.hazard(name),          // localized label
        rawName: name,
        'Last 24 h': lookup(data24, name),
        'Last 7 days': lookup(data7, name),
        'Last 30 days': lookup(data30, name),
      }))
      .filter((d) => d['Last 30 days'] > 0 || d['Last 7 days'] > 0 || d['Last 24 h'] > 0)
      .sort((a, b) => b['Last 30 days'] - a['Last 30 days']);
  }, [data24, data7, data30, t]);

  // ── Loading
  if (!chartData && !error) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <div className="h-64 animate-pulse bg-[#F0EBE0] rounded-xl" />
      </div>
    );
  }

  // ── Error
  if (error && !chartData) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <ErrorState label="hazard trend data" error={error} compact />
      </div>
    );
  }

  // ── Empty
  if (chartData && chartData.length === 0) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <EmptyState
          title="No event distribution data yet"
          hint="Events will appear here once the pipeline processes its first reports."
          compact
        />
      </div>
    );
  }

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3
            className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            <TrendingUp className="w-4 h-4 text-blue-500" />
            {t('analytics.hazard_trend_title') || 'Hazard Type Trends'}
          </h3>
          <p className="text-[11px] text-[#7A8599] mt-0.5">
            {t('analytics.hazard_trend_subtitle') || 'Event counts per hazard across 3 time windows — each bar is a real snapshot, not interpolated'}
          </p>
        </div>
        <span className="text-[10px] font-mono text-[#7A8599] shrink-0">
          3 × GET /api/events/distribution
        </span>
      </div>

      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData ?? []}
            margin={{ top: 8, right: 12, left: 0, bottom: 60 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#E8E2D4" vertical={false} />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 9, fill: '#7A8599', fontFamily: 'Public Sans, sans-serif' }}
              axisLine={false}
              tickLine={false}
              angle={-35}
              textAnchor="end"
              interval={0}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#7A8599', fontFamily: 'JetBrains Mono, monospace' }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
              width={36}
            />
            <Tooltip content={<HazardTooltip />} cursor={{ fill: '#F0EBE0' }} />
            <Legend
              formatter={(value) => (
                <span style={{ fontSize: 10, color: '#4A5568', fontFamily: 'Public Sans, sans-serif' }}>
                  {value}
                </span>
              )}
              wrapperStyle={{ paddingTop: '4px' }}
            />
            <Bar dataKey="Last 24 h"   fill={BAR_24H} maxBarSize={18} radius={[2, 2, 0, 0]} name="Last 24 h" />
            <Bar dataKey="Last 7 days" fill={BAR_7D}  maxBarSize={18} radius={[2, 2, 0, 0]} name="Last 7 days" />
            <Bar dataKey="Last 30 days" fill={BAR_30D} maxBarSize={18} radius={[2, 2, 0, 0]} name="Last 30 days" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
