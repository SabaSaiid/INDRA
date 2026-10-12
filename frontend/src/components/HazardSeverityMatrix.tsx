'use client';

/**
 * HazardSeverityMatrix
 *
 * Tab 5 — Hazard Trends.
 * 2D heatmap table: rows = hazard types, columns = severity levels.
 * Cell background intensity scales with count.
 *
 * Data source: GET /api/events?limit=500 (fetchEvents)
 * Client-side grouping: eventType × severity → count
 */

import React, { useEffect, useState, useMemo } from 'react';
import { Grid3X3 } from 'lucide-react';
import { fetchEvents, type ApiEvent, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

const SEVERITIES = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW'] as const;
type Severity = typeof SEVERITIES[number];

const SEV_COLORS: Record<Severity, { text: string; base: string }> = {
  CRITICAL: { text: '#DC2626', base: '#DC2626' },
  HIGH:     { text: '#F97316', base: '#F97316' },
  MODERATE: { text: '#EAB308', base: '#EAB308' },
  LOW:      { text: '#94A3B8', base: '#94A3B8' },
};

function cellBg(count: number, max: number): string {
  if (count === 0) return 'transparent';
  // Opacity from 0.08 (1 event) to 0.7 (max)
  const opacity = 0.08 + (count / Math.max(1, max)) * 0.62;
  return `rgba(220, 38, 38, ${opacity.toFixed(2)})`;
}
function cellText(count: number, max: number): string {
  const opacity = count / Math.max(1, max);
  return opacity > 0.5 ? '#fff' : '#1B2432';
}

export default function HazardSeverityMatrix({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<ApiEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchEvents({ limit: 500 })
      .then((rows) => { if (!cancelled) { setEvents(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Build matrix: hazardType → severity → count
  const { matrix, hazardTypes, maxCell } = useMemo(() => {
    const m = new Map<string, Map<string, number>>();
    (events ?? []).forEach((ev) => {
      const haz = ev.eventType || 'UNKNOWN';
      const sev = (ev.severity || 'LOW').toUpperCase();
      if (!m.has(haz)) m.set(haz, new Map());
      const inner = m.get(haz)!;
      inner.set(sev, (inner.get(sev) ?? 0) + 1);
    });
    let maxCell = 0;
    m.forEach((inner) => inner.forEach((v) => { if (v > maxCell) maxCell = v; }));
    // Sort hazards by total events desc
    const hazardTypes = Array.from(m.entries())
      .map(([haz, inner]) => ({ haz, total: Array.from(inner.values()).reduce((s, v) => s + v, 0) }))
      .sort((a, b) => b.total - a.total)
      .map(({ haz }) => haz);
    return { matrix: m, hazardTypes, maxCell };
  }, [events]);

  // ── Loading
  if (!events && !error) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <div className="h-64 animate-pulse bg-[#F0EBE0] rounded-xl" />
      </div>
    );
  }

  // ── Error
  if (error && !events) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <ErrorState label="event matrix data" error={error} compact />
      </div>
    );
  }

  // ── Empty
  if (events && events.length === 0) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <EmptyState
          title="No events to compute matrix"
          hint="Events will appear here once the pipeline verifies its first reports."
          compact
        />
      </div>
    );
  }

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-3">
      <div>
        <h3
          className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <Grid3X3 className="w-4 h-4 text-rose-500" />
          {t('analytics.hazard_matrix_title') || 'Hazard × Severity Matrix'}
        </h3>
        <p className="text-[11px] text-[#7A8599] mt-0.5">
          {t('analytics.hazard_matrix_subtitle') || 'Event count per hazard type and severity. Deeper red = more events.'}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs border-separate border-spacing-1">
          <thead>
            <tr>
              <th className="text-left py-1.5 pr-3 text-[#7A8599] font-semibold text-[11px] min-w-[130px]">
                Hazard
              </th>
              {SEVERITIES.map((s) => (
                <th
                  key={s}
                  className="text-center py-1.5 px-2 font-semibold text-[11px] min-w-[64px]"
                  style={{ color: SEV_COLORS[s].text }}
                >
                  {t.severity(s)}
                </th>
              ))}
              <th className="text-right py-1.5 pl-3 text-[#7A8599] font-semibold text-[11px]">Total</th>
            </tr>
          </thead>
          <tbody>
            {hazardTypes.map((haz) => {
              const inner = matrix.get(haz)!;
              const rowTotal = Array.from(inner.values()).reduce((s, v) => s + v, 0);
              return (
                <tr key={haz}>
                  <td className="py-1 pr-3 font-medium text-[#1B2432] truncate max-w-[130px]" title={t.hazard(haz)}>
                    {t.hazard(haz)}
                  </td>
                  {SEVERITIES.map((s) => {
                    const count = inner.get(s) ?? 0;
                    const bg = cellBg(count, maxCell);
                    const fg = cellText(count, maxCell);
                    return (
                      <td
                        key={s}
                        className="text-center py-1 px-2 rounded-lg font-mono font-semibold tabular-nums transition-all"
                        style={{ backgroundColor: bg, color: count > 0 ? fg : '#D1D5DB' }}
                        title={`${t.hazard(haz)}, ${t.severity(s)}: ${count}`}
                      >
                        {count > 0 ? count : '—'}
                      </td>
                    );
                  })}
                  <td className="text-right py-1 pl-3 font-mono font-bold text-[#1B2432] tabular-nums">
                    {rowTotal}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-[10px] text-[#7A8599] border-t border-[#E8E2D4] pt-2">
        <div className="flex items-center gap-1">
          <div className="w-12 h-3 rounded" style={{ background: 'linear-gradient(to right, rgba(220,38,38,0.08), rgba(220,38,38,0.7))' }} />
        </div>
        <span>Low → High event count</span>
        <span className="ml-auto">
          Showing top {events?.length ?? 0} events (limit 500)
        </span>
      </div>
    </div>
  );
}
