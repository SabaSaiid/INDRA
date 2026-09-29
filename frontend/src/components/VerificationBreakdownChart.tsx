'use client';

/**
 * VerificationBreakdownChart
 *
 * Stacked bar chart showing how the AI confidence score is distributed
 * across all non-rejected verified events, broken down by whether the
 * event was AUTO_PUBLISHED or HUMAN_APPROVED.
 *
 * Data source: GET /api/dashboard/verification-breakdown (verified_events)
 */

import React, { useEffect, useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { BrainCircuit } from 'lucide-react';
import { fetchVerificationBreakdown, type VerificationBucket, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';

const AUTO_COLOR   = '#6366F1'; // indigo-500
const HUMAN_COLOR  = '#10B981'; // emerald-500

interface TooltipPayload {
  name: string;
  value: number;
  color: string;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0);
  return (
    <div className="bg-slate-900 text-white text-xs rounded-xl px-3 py-2 shadow-xl border border-slate-700 min-w-[160px]">
      <div className="font-bold mb-1.5 text-cyan-300">Score {label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex justify-between gap-4 items-center">
          <span className="flex items-center gap-1.5 text-slate-300">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: p.color }}
            />
            {p.name === 'auto_published' ? 'Auto-published' : 'Human approved'}
          </span>
          <span className="font-mono tabular-nums">{(p.value ?? 0).toLocaleString('en-IN')}</span>
        </div>
      ))}
      <div className="border-t border-slate-700 mt-1.5 pt-1.5 flex justify-between">
        <span className="text-slate-400">Total</span>
        <span className="font-mono tabular-nums">{total.toLocaleString('en-IN')}</span>
      </div>
    </div>
  );
}

export default function VerificationBreakdownChart() {
  const [data, setData] = useState<VerificationBucket[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchVerificationBreakdown()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-indigo-500" />
          AI Confidence Distribution
        </h2>
        <span className="text-[10px] font-mono text-slate-400">verified_events · confidence_score</span>
      </div>
      <p className="text-[11px] text-slate-500 -mt-1">
        How the AI-assigned confidence score is distributed. High-confidence events are auto-published; lower scores go to human review.
      </p>

      {error && !data ? (
        <ErrorState
          label="verification breakdown"
          error={error instanceof ApiError && error.status === 404
            ? 'GET /api/dashboard/verification-breakdown is not deployed yet.'
            : error}
          compact
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          title="No verified events yet"
          hint="Events appear here once the pipeline processes its first report."
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
              <Legend
                formatter={(value) =>
                  value === 'auto_published' ? 'Auto-published' : 'Human approved'
                }
                wrapperStyle={{ fontSize: '10px', paddingTop: '6px' }}
              />
              <Bar
                dataKey="auto_published"
                stackId="a"
                fill={AUTO_COLOR}
                radius={[0, 0, 0, 0]}
                maxBarSize={52}
                name="auto_published"
              />
              <Bar
                dataKey="human_approved"
                stackId="a"
                fill={HUMAN_COLOR}
                radius={[4, 4, 0, 0]}
                maxBarSize={52}
                name="human_approved"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="flex gap-4 text-[10px] text-slate-500 border-t border-slate-100 pt-2 mt-1">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: AUTO_COLOR }} />
            Auto-published (score ≥ threshold, no human needed)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: HUMAN_COLOR }} />
            Human approved (escalated then confirmed)
          </span>
        </div>
      )}
    </div>
  );
}
