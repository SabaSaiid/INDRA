'use client';

/**
 * VerificationBreakdownChart
 *
 * Stacked bar chart: AI confidence score distribution across verified events,
 * broken down by AUTO_PUBLISHED vs HUMAN_APPROVED.
 *
 * Data source: GET /api/dashboard/verification-breakdown (verified_events)
 *
 * Fixes (Oct 2026):
 *  - Y-axis clipping: width=44, margin.left=12 prevents 3-digit labels being cut off.
 *  - refreshTick prop: re-fetches on global WebSocket events.
 *  - Design: aligned to INDRA warm-paper tokens (bg-[#FDFAF5], Fraunces serif).
 *  - i18n: hardcoded English replaced with t('analytics.*') keys.
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
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { BrainCircuit } from 'lucide-react';
import { fetchVerificationBreakdown, type VerificationBucket, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';

const AUTO_COLOR  = '#6366F1'; // indigo-500
const HUMAN_COLOR = '#10B981'; // emerald-500

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

export default function VerificationBreakdownChart({ refreshTick = 0 }: { refreshTick?: number }) {
  const { t } = useTranslation();
  const [data, setData] = useState<VerificationBucket[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchVerificationBreakdown()
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
          <BrainCircuit className="w-4 h-4 text-indigo-500" />
          {t('analytics.verification_title')}
        </h2>
        <span className="text-[10px] font-mono text-[#7A8599]">verified_events · confidence_score</span>
      </div>
      <p className="text-[11px] text-[#7A8599] -mt-1">{t('analytics.verification_subtitle')}</p>

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
          title={t('analytics.verification_no_data')}
          hint={t('analytics.verification_no_data_hint')}
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
              <Legend
                formatter={(value) =>
                  value === 'auto_published' ? t('analytics.auto_published') : t('analytics.human_approved')
                }
                wrapperStyle={{ fontSize: '10px', paddingTop: '6px', fontFamily: 'Public Sans, sans-serif' }}
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
        <div className="flex flex-wrap gap-4 text-[10px] text-[#7A8599] border-t border-[#E8E2D4] pt-2 mt-1">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: AUTO_COLOR }} />
            {t('analytics.auto_published')} (score ≥ threshold, no human needed)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: HUMAN_COLOR }} />
            {t('analytics.human_approved')} (escalated then confirmed)
          </span>
        </div>
      )}
    </div>
  );
}
