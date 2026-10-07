'use client';

/**
 * TopDistrictsTable
 *
 * Ranked table of the 10 districts with the most verified events, with
 * a severity colour-pill breakdown (CRITICAL / HIGH / MODERATE / LOW).
 *
 * Data source: GET /api/dashboard/top-districts (verified_events)
 *
 * Fixes (Oct 2026):
 *  - refreshTick prop: re-fetches on global WebSocket events from analytics page.
 *  - Removed artificial max-w-[110px] cap on district names (was clipping even
 *    on 1600 px screens where plenty of space existed).
 *  - Progress bar moved to span the full district cell rather than the name td.
 *  - Design: aligned to INDRA warm-paper tokens (bg-[#FDFAF5], Fraunces serif).
 *  - i18n: hardcoded English replaced with t('analytics.*') keys.
 *  - Tooltip on severity pills showing counts + percentages.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { MapPin, TrendingUp } from 'lucide-react';
import { fetchTopDistricts, type TopDistrictRow, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

const SEV_PILL: Record<string, { bg: string; text: string; border: string; label: string }> = {
  critical: { bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200',    label: 'Crit' },
  high:     { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200', label: 'High' },
  moderate: { bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  label: 'Mod'  },
  low:      { bg: 'bg-emerald-50',text: 'text-emerald-700',border: 'border-emerald-200',label: 'Low'  },
};

function Pill({ count, total, kind }: { count: number; total: number; kind: keyof typeof SEV_PILL }) {
  if (count === 0) return null;
  const s = SEV_PILL[kind];
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-bold font-mono border ${s.bg} ${s.text} ${s.border}`}
      title={`${s.label}: ${count} (${pct}%)`}
    >
      {s.label} {count}
    </span>
  );
}

export default function TopDistrictsTable({ refreshTick = 0 }: { refreshTick?: number }) {
  const { t } = useTranslation();
  const [data, setData] = useState<TopDistrictRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTopDistricts()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  const maxTotal = useMemo(
    () => data ? Math.max(1, ...data.map((r) => r.total)) : 1,
    [data]
  );

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2
          className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <MapPin className="w-4 h-4 text-indigo-500" />
          {t('analytics.top_districts_title')}
        </h2>
        <span className="text-[10px] font-mono text-[#7A8599]">verified_events · top 10</span>
      </div>
      <p className="text-[11px] text-[#7A8599] -mt-1">{t('analytics.top_districts_subtitle')}</p>

      {error && !data ? (
        <ErrorState
          label="district data"
          error={error instanceof ApiError && error.status === 404
            ? 'GET /api/dashboard/top-districts is not deployed yet.'
            : error}
          compact
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          title={t('analytics.top_districts_no_data')}
          hint={t('analytics.top_districts_no_data_hint')}
          compact
        />
      ) : !data ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse bg-[#F0EBE0] rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-[#7A8599] uppercase tracking-wide border-b border-[#E8E2D4]">
                <th className="text-left pb-2 pr-2 font-semibold w-6">#</th>
                <th className="text-left pb-2 pr-4 font-semibold min-w-[120px]">District</th>
                <th className="text-left pb-2 pr-4 font-semibold hidden sm:table-cell">State</th>
                <th className="text-right pb-2 pr-4 font-semibold w-16">Events</th>
                <th className="text-left pb-2 font-semibold">Severity split</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F0EBE0]">
              {data.map((row, idx) => {
                const pct = Math.max(4, (row.total / maxTotal) * 100);
                return (
                  <tr key={row.district} className="hover:bg-[#F0EBE0] transition-colors">
                    {/* Rank */}
                    <td className="py-2.5 pr-2 text-[#7A8599] font-mono">{idx + 1}</td>

                    {/* District + progress bar */}
                    <td className="py-2.5 pr-4">
                      <div className="font-semibold text-[#1B2432]" title={row.district}>
                        {row.district}
                      </div>
                      <div className="mt-1 h-1 rounded-full bg-[#E8E2D4] overflow-hidden">
                        <div
                          className="h-full rounded-full bg-indigo-400 transition-all duration-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </td>

                    {/* State */}
                    <td
                      className="py-2.5 pr-4 text-[#7A8599] hidden sm:table-cell"
                      title={row.state ?? ''}
                    >
                      {row.state ?? '—'}
                    </td>

                    {/* Total count */}
                    <td className="py-2.5 pr-4 font-bold font-mono text-[#1B2432] tabular-nums text-right">
                      {row.total.toLocaleString('en-IN')}
                    </td>

                    {/* Severity pills */}
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-1">
                        <Pill count={row.critical} total={row.total} kind="critical" />
                        <Pill count={row.high}     total={row.total} kind="high" />
                        <Pill count={row.moderate} total={row.total} kind="moderate" />
                        <Pill count={row.low}      total={row.total} kind="low" />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && data.length > 0 && (
        <p className="text-[10px] text-[#7A8599] flex items-center gap-1 mt-1 border-t border-[#E8E2D4] pt-2">
          <TrendingUp className="w-3 h-3" />
          Only events that are AUTO_PUBLISHED or HUMAN_APPROVED are counted.
        </p>
      )}
    </div>
  );
}
