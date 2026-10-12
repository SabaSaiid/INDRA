'use client';

/**
 * DataSourceHealthGrid
 *
 * Tab 2 — Source Intelligence.
 * Shows data source health, ingestion contributions, and kind breakdown.
 *
 * Data source: GET /api/meta/sources
 */

import React, { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { Radio, CheckCircle, AlertTriangle, XCircle, MinusCircle } from 'lucide-react';
import { fetchDataSources, type DataSourceStatus, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { formatAgo } from '@/lib/utils';
import { useTranslation } from '@/lib/i18n/useTranslation';

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, {
  label: string; color: string; bg: string; Icon: React.ElementType;
}> = {
  ok:       { label: 'OK',       color: '#10B981', bg: '#ECFDF5', Icon: CheckCircle  },
  stale:    { label: 'Stale',    color: '#F59E0B', bg: '#FFFBEB', Icon: AlertTriangle },
  failing:  { label: 'Failing',  color: '#EF4444', bg: '#FEF2F2', Icon: XCircle       },
  disabled: { label: 'Disabled', color: '#94A3B8', bg: '#F8FAFC', Icon: MinusCircle   },
};

const KIND_COLORS: Record<string, string> = {
  sensor:   '#2563EB',
  cap_feed: '#F97316',
  push:     '#8B5CF6',
  citizen:  '#10B981',
};
const KIND_LABELS: Record<string, string> = {
  sensor:   'Sensor',
  cap_feed: 'CAP Feed',
  push:     'Push / Webhook',
  citizen:  'Citizen',
};

// ─── Custom Tooltip ───────────────────────────────────────────────────────────

function BarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d: DataSourceStatus = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-slate-900 text-white text-xs rounded-xl px-3 py-2 shadow-xl border border-slate-700 min-w-[180px]">
      <div className="font-bold mb-1 text-cyan-300 truncate">{d.title || d.feed}</div>
      <div className="flex justify-between gap-4">
        <span className="text-slate-300">Last 24 h</span>
        <span className="font-mono tabular-nums">{d.rows_24h.toLocaleString('en-IN')}</span>
      </div>
      {d.last_success_at && (
        <div className="flex justify-between gap-4 mt-0.5">
          <span className="text-slate-400">Last success</span>
          <span className="font-mono">{formatAgo(d.last_success_at)}</span>
        </div>
      )}
    </div>
  );
}

// ─── Source status card ───────────────────────────────────────────────────────

function SourceCard({ s }: { s: DataSourceStatus }) {
  const cfg = STATUS_CONFIG[s.status] ?? STATUS_CONFIG.disabled;
  const { Icon } = cfg;
  return (
    <div
      className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-3.5 flex flex-col gap-2 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div
            className="text-xs font-bold text-[#1B2432] truncate"
            style={{ fontFamily: 'JetBrains Mono, monospace' }}
            title={s.feed}
          >
            {s.feed}
          </div>
          {s.title && (
            <div className="text-[10px] text-[#7A8599] truncate mt-0.5">{s.title}</div>
          )}
        </div>
        {/* Status badge */}
        <span
          className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0"
          style={{ color: cfg.color, backgroundColor: cfg.bg }}
        >
          <Icon className="w-3 h-3" />
          {cfg.label}
        </span>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div
            className="text-base font-bold tabular-nums"
            style={{ fontFamily: 'JetBrains Mono, monospace', color: '#1B2432' }}
          >
            {s.rows_24h.toLocaleString('en-IN')}
          </div>
          <div className="text-[9px] text-[#7A8599]">last 24 h</div>
        </div>
        <div>
          <div
            className="text-base font-bold tabular-nums"
            style={{ fontFamily: 'JetBrains Mono, monospace', color: '#1B2432' }}
          >
            {s.rows_total.toLocaleString('en-IN')}
          </div>
          <div className="text-[9px] text-[#7A8599]">total rows</div>
        </div>
        <div>
          <div
            className="text-base font-bold tabular-nums"
            style={{ fontFamily: 'JetBrains Mono, monospace', color: '#1B2432' }}
          >
            {s.poll_interval_s ? `${Math.round(s.poll_interval_s / 60)}m` : '—'}
          </div>
          <div className="text-[9px] text-[#7A8599]">poll interval</div>
        </div>
      </div>

      {/* Last success / error */}
      <div className="text-[10px] text-[#7A8599] border-t border-[#E8E2D4] pt-1.5">
        {s.status === 'failing' && s.last_error ? (
          <span className="text-red-500 truncate block" title={s.last_error}>
            ⚠ {s.last_error}
          </span>
        ) : s.last_success_at ? (
          `Last ok: ${formatAgo(s.last_success_at)}`
        ) : (
          'No successful poll recorded'
        )}
      </div>

      {/* Kind badge */}
      <div className="flex items-center gap-1.5">
        <span
          className="text-[9px] font-semibold px-1.5 py-0.5 rounded"
          style={{
            color: KIND_COLORS[s.kind] ?? '#94A3B8',
            backgroundColor: `${KIND_COLORS[s.kind] ?? '#94A3B8'}18`,
          }}
        >
          {KIND_LABELS[s.kind] ?? s.kind}
        </span>
        {!s.enabled && (
          <span className="text-[9px] text-[#94A3B8] font-medium">disabled</span>
        )}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DataSourceHealthGrid({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<DataSourceStatus[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    fetchDataSources()
      .then((rows) => { if (!cancelled) { setSources(rows); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Bar chart data: rows_24h per source, sorted desc
  const barData = useMemo(
    () =>
      (sources ?? [])
        .filter((s) => s.rows_24h > 0)
        .sort((a, b) => b.rows_24h - a.rows_24h)
        .map((s) => ({ ...s, name: s.title || s.feed })),
    [sources]
  );

  // Donut data: count by kind
  const donutData = useMemo(() => {
    const m = new Map<string, number>();
    (sources ?? []).forEach((s) => m.set(s.kind, (m.get(s.kind) ?? 0) + 1));
    return Array.from(m.entries()).map(([kind, count]) => ({
      name: KIND_LABELS[kind] ?? kind,
      value: count,
      color: KIND_COLORS[kind] ?? '#94A3B8',
    }));
  }, [sources]);

  // ── Loading ──
  if (!sources && !error) {
    return (
      <div className="space-y-6">
        <div className="h-52 animate-pulse bg-[#F0EBE0] rounded-xl" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-36 animate-pulse bg-[#F0EBE0] rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error ──
  if (error && !sources) {
    return (
      <ErrorState
        label="data sources"
        error={
          error instanceof ApiError && error.status === 404
            ? 'GET /api/meta/sources is not available on this backend version.'
            : error
        }
      />
    );
  }

  // ── Empty ──
  if (sources && sources.length === 0) {
    return (
      <EmptyState
        title="No data sources registered"
        hint="Check the backend configuration or the /api/meta/sources endpoint."
      />
    );
  }

  return (
    <div className="space-y-6">

      {/* ── Summary row ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {(['ok', 'stale', 'failing', 'disabled'] as const).map((status) => {
          const cfg = STATUS_CONFIG[status];
          const { Icon } = cfg;
          const n = (sources ?? []).filter((s) => s.status === status).length;
          return (
            <div
              key={status}
              className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-4 flex flex-col gap-1 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-[#7A8599]">{cfg.label}</span>
                <Icon className="w-4 h-4" style={{ color: cfg.color }} />
              </div>
              <div
                className="text-2xl font-bold tabular-nums"
                style={{ fontFamily: 'JetBrains Mono, monospace', color: cfg.color }}
              >
                {n}
              </div>
              <div className="text-[10px] text-[#7A8599]">sources</div>
            </div>
          );
        })}
      </div>

      {/* ── Contribution chart + Kind donut ───────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Contribution bar chart */}
        <div className="lg:col-span-2 bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
          <h3
            className="text-sm font-bold text-[#1B2432] mb-0.5"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            {t('analytics.sources_chart_title')}
          </h3>
          <p className="text-[11px] text-[#7A8599] mb-3">{t('analytics.sources_chart_subtitle')}</p>
          {barData.length === 0 ? (
            <EmptyState
              title="No rows ingested in the last 24 h"
              hint="Feeds may be idle or just started."
              compact
            />
          ) : (
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={barData}
                  layout="vertical"
                  margin={{ top: 0, right: 12, left: 0, bottom: 0 }}
                >
                  <XAxis
                    type="number"
                    tick={{ fontSize: 10, fill: '#7A8599', fontFamily: 'JetBrains Mono, monospace' }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={110}
                    tick={{ fontSize: 10, fill: '#4A5568', fontFamily: 'JetBrains Mono, monospace' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<BarTooltip />} cursor={{ fill: '#F0EBE0' }} />
                  <Bar
                    dataKey="rows_24h"
                    radius={[0, 4, 4, 0]}
                    maxBarSize={20}
                  >
                    {barData.map((entry, i) => (
                      <Cell
                        key={`cell-${i}`}
                        fill={STATUS_CONFIG[entry.status]?.color ?? '#94A3B8'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Kind donut */}
        <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col">
          <h3
            className="text-sm font-bold text-[#1B2432] mb-0.5"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            {t('analytics.sources_types_title')}
          </h3>
          <p className="text-[11px] text-[#7A8599] mb-3">{t('analytics.sources_types_subtitle')}</p>
          {donutData.length === 0 ? (
            <EmptyState title="No kind data" compact />
          ) : (
            <div className="flex-1 h-44">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={donutData}
                    cx="50%"
                    cy="45%"
                    innerRadius="45%"
                    outerRadius="70%"
                    dataKey="value"
                    strokeWidth={2}
                    stroke="#FDFAF5"
                  >
                    {donutData.map((entry, i) => (
                      <Cell key={`cell-${i}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Legend
                    formatter={(value) => (
                      <span style={{ fontSize: 10, color: '#4A5568', fontFamily: 'Public Sans, sans-serif' }}>
                        {value}
                      </span>
                    )}
                    wrapperStyle={{ paddingTop: '4px' }}
                  />
                  <Tooltip
                    formatter={(value: number) => [`${value} sources`, '']}
                    contentStyle={{
                      background: '#1E293B',
                      border: 'none',
                      borderRadius: 10,
                      color: '#fff',
                      fontSize: 11,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* ── Source cards grid ──────────────────────────────────────────────── */}
      <div>
        <h3
          className="text-sm font-bold text-[#1B2432] mb-3"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          All Sources ({sources?.length})
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {(sources ?? []).map((s) => (
            <SourceCard key={s.feed} s={s} />
          ))}
        </div>
      </div>
    </div>
  );
}
