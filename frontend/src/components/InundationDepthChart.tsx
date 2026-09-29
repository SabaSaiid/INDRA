'use client';

/**
 * InundationDepthChart
 *
 * Bar chart showing how many field reports fall into each water depth bucket
 * (< 15 cm, 15–30 cm, 30–60 cm, 60–120 cm, > 120 cm).
 *
 * Data source: GET /api/dashboard/inundation-depth (raw_reports.analysis->>'depth_cm')
 */

import React, { useEffect, useState } from 'react';
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

export default function InundationDepthChart() {
  const [data, setData] = useState<InundationDepthBucket[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchInundationDepth()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <Waves className="w-4 h-4 text-blue-500" />
          Water Inundation Depth
        </h2>
        <span className="text-[10px] font-mono text-slate-400">raw_reports · depth_cm</span>
      </div>
      <p className="text-[11px] text-slate-500 -mt-1">
        Distribution of depths extracted from field reports by the NLP pipeline. Each bar is one depth band.
      </p>

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
          title="No depth readings yet"
          hint="Reports need a depth_cm value in their analysis JSON."
          compact
        />
      ) : !data ? (
        <div className="h-52 animate-pulse bg-slate-50 rounded-xl" />
      ) : (
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false} />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 10, fill: '#64748B' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#64748B' }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
                width={30}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: '#F8FAFC' }} />
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
