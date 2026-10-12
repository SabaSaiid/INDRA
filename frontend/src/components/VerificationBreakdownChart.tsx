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
import { useThemeTokens } from '@/lib/useThemeTokens';

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
    <div className="bg-surface-raised text-text text-xs rounded-xl px-3 py-2 shadow-xl border border-border min-w-[160px]">
      <div className="font-bold mb-1.5 text-brand">Score {label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex justify-between gap-4 items-center">
          <span className="flex items-center gap-1.5 text-text-muted">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: p.color }}
            />
            {p.name === 'auto_published' ? 'Auto-published' : 'Human approved'}
          </span>
          <span className="font-mono tabular-nums text-text">{(p.value ?? 0).toLocaleString('en-IN')}</span>
        </div>
      ))}
      <div className="border-t border-border mt-1.5 pt-1.5 flex justify-between">
        <span className="text-text-muted">Total</span>
        <span className="font-mono tabular-nums text-text">{total.toLocaleString('en-IN')}</span>
      </div>
    </div>
  );
}

export default function VerificationBreakdownChart({ refreshTick = 0 }: { refreshTick?: number }) {
  const { t } = useTranslation();
  const tokens = useThemeTokens();
  const [data, setData] = useState<VerificationBucket[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const isDark = tokens.themeId === 'night_watch' || tokens.themeId === 'high_contrast';
  const autoColor = isDark ? '#818CF8' : '#4F46E5';
  const humanColor = tokens.status.verified;

  useEffect(() => {
    let cancelled = false;
    fetchVerificationBreakdown()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  return (
    <div className="bg-surface p-5 rounded-xl border border-border shadow-2xs flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-bold text-text flex items-center gap-2 font-display">
          <BrainCircuit className="w-4 h-4 text-brand" />
          {t('analytics.verification_title')}
        </h2>
        <span className="text-[10px] font-mono text-text-muted">verified_events · confidence_score</span>
      </div>
      <p className="text-[11px] text-text-muted -mt-1">{t('analytics.verification_subtitle')}</p>

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
        <div className="h-52 animate-pulse bg-surface-raised rounded-xl" />
      ) : (
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            {/* margin.left=12 + width=44 prevents 3-digit Y-axis labels from being clipped */}
            <BarChart
              key={`verification-breakdown-${tokens.themeId}`}
              data={data}
              margin={{ top: 8, right: 12, left: 12, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={tokens.border} vertical={false} />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 10, fill: tokens.textMuted, fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: tokens.textMuted, fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
                width={44}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: tokens.surfaceRaised, opacity: 0.5 }} />
              <Legend
                formatter={(value) => (
                  <span style={{ color: tokens.textSecondary, fontSize: '10px' }}>
                    {value === 'auto_published' ? t('analytics.auto_published') : t('analytics.human_approved')}
                  </span>
                )}
                wrapperStyle={{ fontSize: '10px', paddingTop: '6px' }}
              />
              <Bar
                dataKey="auto_published"
                stackId="a"
                fill={autoColor}
                radius={[0, 0, 0, 0]}
                maxBarSize={52}
                name="auto_published"
              />
              <Bar
                dataKey="human_approved"
                stackId="a"
                fill={humanColor}
                radius={[4, 4, 0, 0]}
                maxBarSize={52}
                name="human_approved"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="flex flex-wrap gap-4 text-[10px] text-text-muted border-t border-border pt-2 mt-1">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: autoColor }} />
            {t('analytics.auto_published')} (score ≥ threshold, no human needed)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: humanColor }} />
            {t('analytics.human_approved')} (escalated then confirmed)
          </span>
        </div>
      )}
    </div>
  );
}
