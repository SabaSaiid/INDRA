'use client';

/**
 * StateRiskLeaderboard
 *
 * Tab 3 — Geo Risk.
 * Groups top districts by state, computes a risk score, and renders
 * a state-level risk ranking table + stacked district bar chart.
 *
 * Data source: GET /api/dashboard/top-districts (fetchTopDistricts)
 */

import React, { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts';
import { MapPin } from 'lucide-react';
import { fetchTopDistricts, type TopDistrictRow, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { useThemeTokens } from '@/lib/useThemeTokens';

// ─── Risk score ───────────────────────────────────────────────────────────────

/** Weighted score: critical × 3, high × 2, moderate × 1 */
function riskScore(row: TopDistrictRow): number {
  if (row.total === 0) return 0;
  return Math.round(((row.critical * 3 + row.high * 2 + row.moderate) / (row.total * 3)) * 100);
}

// ─── Tooltip ─────────────────────────────────────────────────────────────────

function DistrictTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s: number, p: any) => s + (p.value ?? 0), 0);
  return (
    <div className="bg-surface-raised text-text text-xs rounded-xl px-3 py-2 shadow-xl border border-border min-w-[160px]">
      <div className="font-bold mb-1.5 text-brand truncate">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} className="flex justify-between gap-4 items-center">
          <span className="flex items-center gap-1.5 text-text-muted capitalize">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-mono tabular-nums text-text">{p.value ?? 0}</span>
        </div>
      ))}
      <div className="border-t border-border mt-1.5 pt-1.5 flex justify-between">
        <span className="text-text-muted">Total</span>
        <span className="font-mono tabular-nums text-text">{total}</span>
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function StateRiskLeaderboard({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const tokens = useThemeTokens();
  const [districts, setDistricts] = useState<TopDistrictRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const getRiskColor = (score: number): string => {
    if (score >= 70) return tokens.severity.critical;
    if (score >= 40) return tokens.severity.high;
    if (score >= 15) return tokens.severity.moderate;
    return tokens.severity.low;
  };

  useEffect(() => {
    let cancelled = false;
    fetchTopDistricts()
      .then((rows) => { if (!cancelled) { setDistricts(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Group districts → states
  const stateRows = useMemo(() => {
    const m = new Map<string, { total: number; critical: number; high: number; moderate: number; low: number }>();
    (districts ?? []).forEach((d) => {
      const key = d.state || 'Unknown State';
      const prev = m.get(key) ?? { total: 0, critical: 0, high: 0, moderate: 0, low: 0 };
      m.set(key, {
        total:    prev.total    + d.total,
        critical: prev.critical + d.critical,
        high:     prev.high     + d.high,
        moderate: prev.moderate + d.moderate,
        low:      prev.low      + d.low,
      });
    });
    return Array.from(m.entries())
      .map(([state, v]) => ({ state, ...v, score: riskScore(v as TopDistrictRow) }))
      .sort((a, b) => b.score - a.score || b.total - a.total);
  }, [districts]);

  // District bar chart data (top 10)
  const districtBarData = useMemo(
    () =>
      (districts ?? []).slice(0, 10).map((d) => ({
        name: d.district,
        critical: d.critical,
        high: d.high,
        moderate: d.moderate,
        low: d.low,
      })),
    [districts]
  );

  // ── Loading
  if (!districts && !error) {
    return (
      <div className="space-y-6">
        <div className="h-48 animate-pulse bg-surface-raised rounded-xl" />
        <div className="h-64 animate-pulse bg-surface-raised rounded-xl" />
      </div>
    );
  }

  // ── Error
  if (error && !districts) {
    return (
      <ErrorState
        label="district risk data"
        error={
          error instanceof ApiError && error.status === 404
            ? 'GET /api/dashboard/top-districts is not available on this backend version.'
            : error
        }
      />
    );
  }

  // ── Empty
  if (districts && districts.length === 0) {
    return (
      <EmptyState
        title="No verified events with a known location yet"
        hint="Events gain a district after geocoding completes."
      />
    );
  }

  const maxTotal = Math.max(1, ...stateRows.map((r) => r.total));

  return (
    <div className="space-y-6">

      {/* ── State Leaderboard Table ──────────────────────────────────────── */}
      <div className="bg-surface rounded-xl border border-border shadow-2xs overflow-hidden">
        <div className="p-5 border-b border-border">
          <h3 className="text-sm font-bold text-text flex items-center gap-2 font-display">
            <MapPin className="w-4 h-4 text-brand" />
            {t('analytics.geo_state_leaderboard_title')}
          </h3>
          <p className="text-[11px] text-text-muted mt-0.5">
            {t('analytics.geo_state_leaderboard_subtitle')}
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-surface-raised text-text-muted">
                <th className="text-left px-4 py-2.5 font-semibold">State</th>
                <th className="text-right px-3 py-2.5 font-semibold text-severity-critical">Critical</th>
                <th className="text-right px-3 py-2.5 font-semibold text-severity-high">High</th>
                <th className="text-right px-3 py-2.5 font-semibold text-severity-moderate">Moderate</th>
                <th className="text-right px-3 py-2.5 font-semibold">Total</th>
                <th className="px-4 py-2.5 font-semibold w-36">{t('analytics.geo_risk_score') || 'Risk Score'}</th>
              </tr>
            </thead>
            <tbody>
              {stateRows.map((row, i) => {
                const score = row.score;
                const color = getRiskColor(score);
                const pct = Math.max(4, (row.total / maxTotal) * 100);
                return (
                  <tr
                    key={row.state}
                    className="border-t border-border hover:bg-surface-raised/50 transition-colors"
                  >
                    <td className="px-4 py-2.5">
                      <span className="font-medium text-text">{row.state}</span>
                      {i === 0 && (
                        <span className="ml-2 text-[9px] font-bold bg-severity-critical/15 text-severity-critical px-1.5 py-0.5 rounded-full">
                          HIGHEST
                        </span>
                      )}
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono font-semibold text-severity-critical">
                      {row.critical || '—'}
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono text-severity-high">
                      {row.high || '—'}
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono text-severity-moderate">
                      {row.moderate || '—'}
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono font-bold text-text">
                      {row.total}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 rounded-full bg-surface-raised overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${pct}%`, backgroundColor: color }}
                          />
                        </div>
                        <span
                          className="text-[10px] font-bold font-mono w-8 text-right"
                          style={{ color }}
                        >
                          {score}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── District Stacked Bar Chart ───────────────────────────────────── */}
      <div className="bg-surface p-5 rounded-xl border border-border shadow-2xs">
        <h3 className="text-sm font-bold text-text mb-0.5 font-display">
          {t('analytics.geo_district_chart_title')}
        </h3>
        <p className="text-[11px] text-text-muted mb-3">
          {t('analytics.geo_district_chart_subtitle')}
        </p>
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              key={`state-risk-${tokens.themeId}`}
              data={districtBarData}
              layout="vertical"
              margin={{ top: 0, right: 12, left: 4, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={tokens.border} horizontal={false} />
              <XAxis
                type="number"
                tick={{ fontSize: 10, fill: tokens.textMuted, fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={100}
                tick={{ fontSize: 10, fill: tokens.textSecondary, fontFamily: 'JetBrains Mono, monospace' }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip content={<DistrictTooltip />} cursor={{ fill: tokens.surfaceRaised, opacity: 0.5 }} />
              <Legend
                formatter={(value) => (
                  <span style={{ fontSize: 10, color: tokens.textSecondary, textTransform: 'capitalize' }}>
                    {value}
                  </span>
                )}
                wrapperStyle={{ paddingTop: '6px' }}
              />
              <Bar dataKey="critical" stackId="a" fill={tokens.severity.critical} maxBarSize={16} name="critical" />
              <Bar dataKey="high"     stackId="a" fill={tokens.severity.high}     maxBarSize={16} name="high" />
              <Bar dataKey="moderate" stackId="a" fill={tokens.severity.moderate} maxBarSize={16} name="moderate" />
              <Bar dataKey="low"      stackId="a" fill={tokens.severity.low}      maxBarSize={16} radius={[0, 4, 4, 0]} name="low" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
