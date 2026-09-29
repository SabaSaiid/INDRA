'use client';

/**
 * TopDistrictsTable
 *
 * Ranked table of the 10 districts with the most verified events, showing a
 * severity colour-pill breakdown (CRITICAL / HIGH / MODERATE / LOW) per row.
 *
 * Data source: GET /api/dashboard/top-districts (verified_events)
 */

import React, { useEffect, useState } from 'react';
import { MapPin, TrendingUp } from 'lucide-react';
import { fetchTopDistricts, type TopDistrictRow, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';

const SEV_PILL: Record<string, { bg: string; text: string; label: string }> = {
  critical: { bg: 'bg-red-100',    text: 'text-red-700',    label: 'Crit' },
  high:     { bg: 'bg-orange-100', text: 'text-orange-700', label: 'High' },
  moderate: { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Mod' },
  low:      { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Low' },
};

function Pill({ count, kind }: { count: number; kind: keyof typeof SEV_PILL }) {
  if (count === 0) return null;
  const s = SEV_PILL[kind];
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-bold font-mono ${s.bg} ${s.text}`}>
      {s.label} {count}
    </span>
  );
}

export default function TopDistrictsTable() {
  const [data, setData] = useState<TopDistrictRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTopDistricts()
      .then((rows) => { if (!cancelled) { setData(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  }, []);

  const maxTotal = data ? Math.max(1, ...data.map((r) => r.total)) : 1;

  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <MapPin className="w-4 h-4 text-indigo-500" />
          Top Impacted Districts
        </h2>
        <span className="text-[10px] font-mono text-slate-400">verified_events · top 10</span>
      </div>
      <p className="text-[11px] text-slate-500 -mt-1">
        Districts ranked by number of AUTO_PUBLISHED or HUMAN_APPROVED events. Bar width is proportional to rank.
      </p>

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
          title="No verified events with a district name yet"
          hint="Events gain a district after geocoding completes."
          compact
        />
      ) : !data ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse bg-slate-50 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-slate-400 uppercase tracking-wide">
                <th className="text-left pb-2 pr-2 font-semibold w-6">#</th>
                <th className="text-left pb-2 pr-2 font-semibold">District</th>
                <th className="text-left pb-2 pr-2 font-semibold hidden sm:table-cell">State</th>
                <th className="text-left pb-2 pr-6 font-semibold">Events</th>
                <th className="text-left pb-2 font-semibold">Severity split</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {data.map((row, idx) => {
                const pct = Math.max(4, (row.total / maxTotal) * 100);
                return (
                  <tr key={row.district} className="hover:bg-slate-50 transition-colors">
                    <td className="py-2 pr-2 text-slate-400 font-mono">{idx + 1}</td>
                    <td className="py-2 pr-2">
                      <div className="font-semibold text-slate-800 truncate max-w-[110px]" title={row.district}>
                        {row.district}
                      </div>
                      {/* Progress bar under the name */}
                      <div className="mt-1 h-1 rounded-full bg-slate-100 overflow-hidden w-full">
                        <div
                          className="h-full rounded-full bg-indigo-400"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </td>
                    <td className="py-2 pr-2 text-slate-500 hidden sm:table-cell truncate max-w-[80px]" title={row.state ?? ''}>
                      {row.state ?? '—'}
                    </td>
                    <td className="py-2 pr-6 font-bold font-mono text-slate-900 tabular-nums">
                      {row.total.toLocaleString('en-IN')}
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        <Pill count={row.critical} kind="critical" />
                        <Pill count={row.high}     kind="high" />
                        <Pill count={row.moderate} kind="moderate" />
                        <Pill count={row.low}      kind="low" />
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
        <p className="text-[10px] text-slate-400 flex items-center gap-1 mt-1">
          <TrendingUp className="w-3 h-3" />
          Only events that are AUTO_PUBLISHED or HUMAN_APPROVED are counted.
        </p>
      )}
    </div>
  );
}
