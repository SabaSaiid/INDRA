'use client';

/**
 * InundationDepthChart
 *
 * Bar chart showing how many field reports fall into each water depth bucket
 * (< 15 cm, 15–30 cm, 30–60 cm, 60–120 cm, > 120 cm).
 *
 * Data source: GET /api/dashboard/inundation-depth (raw_reports.analysis->>'depth_cm')
 *
 * Fixes (Oct 2026):
 *  - Y-axis clipping: width=44, margin.left=12 prevents 3-digit labels being cut off.
 *  - refreshTick prop: re-fetches whenever the parent page bumps the global tick.
 *  - i18n: all hardcoded English titles replaced with t('analytics.*') keys.
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from '@/lib/i18n/useTranslation';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { Waves } from 'lucide-react';
import { fetchInundationDepth, type InundationDepthBucket, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';

/** Colour per severity bucket — deepest water = most dangerous. */
const BUCKET_COLOURS: Record<string, string> = {
  '< 15 cm':    '#60A5FA',  // blue-400  – ankle-deep, low risk
  '15 – 30 cm': '#3B82F6',  // blue-500
  '30 – 60 cm': '#F59E0B',  // amber-500 – knee-deep, moderate
  '60 – 120 cm':'#EA580C',  // orange-600 – waist-deep, high risk
  '> 120 cm':   '#DC2626',  // red-600   – chest-deep, critical
};

function bucketColor(bucket: string): string {
  return BUCKET_COLOURS[bucket] ?? '#94A3B8';
}

interface TooltipPayload {
  payload?: InundationDepthBucket;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayload[] }) {
  if (!active || !payload?.length || !payload[0].payload) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-900 text-white text-xs rounded-xl px-3 py-2 shadow-xl border border-slate-700">
      <div className="font-bold mb-0.5">{d.bucket}</div>
      <div className="text-slate-300">{d.count.toLocaleString('en-IN')} report{d.count !== 1 ? 's' : ''}</div>
    </div>
  );
}

export default function InundationDepthChart({ refreshTick = 0 }: { refreshTick?: number }) {
  const { t } = useTranslation();
  const [data, setData] = useState<InundationDepthBucket[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchInundationDepth()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2
          className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <Waves className="w-4 h-4 text-blue-500" />
          {t('analytics.inundation_title')}
        </h2>
        <span className="text-[10px] font-mono text-[#7A8599]">raw_reports · depth_cm</span>
      </div>
      <p className="text-[11px] text-[#7A8599] -mt-1">{t('analytics.inundation_subtitle')}</p>

      {error && !data ? (
        <ErrorState
          label="inundation depth data"
          error={error instanceof ApiError && error.status === 404
            ? 'GET /api/dashboard/inundation-depth is not deployed yet.'
            : error}
          compact
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          title={t('analytics.inundation_no_data')}
          hint={t('analytics.inundation_no_data_hint')}
          compact
        />
      ) : !data ? (
        <div className="h-52 animate-pulse bg-[#F0EBE0] rounded-xl" />
      ) : (
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            {/* margin.left=12 + width=44 prevents 3-digit Y-axis labels from being clipped */}
            <BarChart data={data} margin={{ top: 8, right: 12, left: 12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8E2D4" vertical={false} />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 10, fill: '#7A8599', fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#7A8599', fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
                width={44}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: '#F0EBE0' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={52}>
                {data.map((entry) => (
                  <Cell key={entry.bucket} fill={bucketColor(entry.bucket)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
