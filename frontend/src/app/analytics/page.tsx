'use client';

/**
 * Analytics. The two charts always read the backend; the figures above them
 * used to be invented — a "BIGQUERY ML ENGINE" at "28ms" inference latency, a
 * "96.4%" model confidence index, "1.42M" Doppler radar points per second,
 * "37" precipitation anomalies and "4.82 TB" of IMD and ISRO data a day, none
 * of which INDRA has. They are now counts from GET /api/dashboard/summary.
 *
 * Since 24 Sep it also shows the two live feeds that were stored and never
 * drawn: the Open-Meteo rainfall the station poller writes every 10 minutes,
 * and the official warnings in force grouped by who issued them.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { BarChart3, TrendingUp, Activity, Layers, Database, ShieldAlert, CloudRain, Radio } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import ReportsTrendChart from '@/components/ReportsTrendChart';
import EventDistributionChart from '@/components/EventDistributionChart';
import {
  ApiError,
  fetchSummaryCounts,
  fetchStations,
  fetchAgencyAlerts,
  type DashboardSummary,
  type RainfallStation,
  type AgencyAlert,
} from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { formatAgo, formatIst } from '@/lib/utils';
import { useSettings, formatRainfall } from '@/lib/useSettings';

function Figure({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string;
  value: string;
  note: string;
  icon: React.ElementType;
}) {
  return (
    <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
      <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
        <span>{label}</span>
        <Icon className="w-4 h-4 text-slate-400" />
      </div>
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      <div className="text-[11px] text-slate-500 font-medium mt-1">{note}</div>
    </div>
  );
}

/** IMD's rainfall words for a 24 h total, so a number carries its meaning. */
function rainfallClass(mm: number | null): { label: string; color: string } {
  if (mm == null) return { label: 'no reading', color: '#94A3B8' };
  if (mm < 2.5) return { label: 'Very light / dry', color: '#94A3B8' };
  if (mm < 15.6) return { label: 'Light', color: '#60A5FA' };
  if (mm < 64.5) return { label: 'Moderate', color: '#2563EB' };
  if (mm < 115.6) return { label: 'Heavy', color: '#F59E0B' };
  if (mm < 204.5) return { label: 'Very heavy', color: '#EA580C' };
  return { label: 'Extremely heavy', color: '#DC2626' };
}

function RainfallPanel() {
  const [stations, setStations] = useState<RainfallStation[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const { settings } = useSettings();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchStations()
        .then((rows) => { if (!cancelled) { setStations(rows); setError(null); } })
        .catch((err) => { if (!cancelled) setError(err); });
    load();
    const id = setInterval(load, 300_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const max = useMemo(
    () => Math.max(10, ...(stations ?? []).map((s) => s.rainfall_mm ?? 0)),
    [stations]
  );

  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-1">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <CloudRain className="w-4 h-4 text-blue-600" />
          Rainfall, last 24 hours
        </h2>
        <span className="text-[10px] font-mono text-slate-400 text-right">Open-Meteo · every 10 min</span>
      </div>
      <p className="text-[11px] text-slate-500 mb-3">
        Model rainfall at six city points, the figure the weather factor scores. Not IMD gauge readings.
      </p>
      {error && !stations ? (
        <ErrorState
          label="rainfall readings"
          error={
            error instanceof ApiError && error.status === 404
              ? 'This server has not been updated with GET /api/geo/stations yet.'
              : error
          }
          compact
        />
      ) : stations && stations.length === 0 ? (
        <EmptyState title="No readings in the last 48 hours" hint="The station poller may be switched off." compact />
      ) : !stations ? (
        <div className="h-40 animate-pulse bg-slate-50 rounded-xl" />
      ) : (
        <div className="space-y-2">
          {stations.map((st) => {
            const cls = rainfallClass(st.rainfall_mm);
            const pct = Math.max(2, ((st.rainfall_mm ?? 0) / max) * 100);
            return (
              <div key={st.station_code} className="grid grid-cols-[88px_1fr_110px_72px] items-center gap-3">
                <span className="text-xs font-medium text-slate-800 truncate">{st.station_name}</span>
                <div className="h-2.5 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: cls.color }} />
                </div>
                <span className="text-xs tabular-nums text-slate-700">
                  <strong className="font-mono">{st.rainfall_mm == null ? '—' : formatRainfall(st.rainfall_mm, settings.rainUnit)}</strong>
                  <span className="block text-[10px] text-slate-400">{cls.label}</span>
                </span>
                <div className="h-8" title={`48 h trend, newest ${formatIst(st.recorded_at)} IST`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={st.series}>
                      <YAxis hide domain={[0, 'dataMax']} />
                      <Line type="linear" dataKey="rainfall_mm" stroke={cls.color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })}
          <p className="text-[10px] text-slate-400 pt-1">
            Newest observation {formatIst(stations[0]?.recorded_at)} IST ({formatAgo(stations[0]?.recorded_at)}). Sparklines: last 48 h.
          </p>
        </div>
      )}
    </div>
  );
}

import { useTranslation } from '@/lib/i18n/useTranslation';

const WARNING_COLOURS: Array<{ key: string; name: string; color: string }> = [
  { key: 'CRITICAL', name: 'Red', color: '#DC2626' },
  { key: 'HIGH', name: 'Orange', color: '#F97316' },
  { key: 'MODERATE', name: 'Yellow', color: '#EAB308' },
  { key: 'ADVISORY', name: 'Advisory', color: '#10B981' },
];

function WarningsPanel() {
  const { t } = useTranslation();
  const [alerts, setAlerts] = useState<AgencyAlert[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAgencyAlerts(200)
        .then((rows) => { if (!cancelled) { setAlerts(rows); setError(null); } })
        .catch((err) => { if (!cancelled) setError(err); });
    load();
    const id = setInterval(load, 120_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const bySender = useMemo(() => {
    const m = new Map<string, number>();
    (alerts ?? []).forEach((a) => m.set(a.sender || 'Unknown', (m.get(a.sender || 'Unknown') ?? 0) + 1));
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [alerts]);
  const byColour = useMemo(
    () => WARNING_COLOURS.map((c) => ({ ...c, n: (alerts ?? []).filter((a) => a.severity === c.key).length })),
    [alerts]
  );
  const topSender = bySender[0]?.[1] ?? 1;

  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-1">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <Radio className="w-4 h-4 text-orange-600" />
          {t('chart.warnings')}
        </h2>
        <span className="text-[10px] font-mono text-slate-400 text-right">SACHET CAP · every 5 min</span>
      </div>
      <p className="text-[11px] text-slate-500 mb-3">
        Issued by IMD, CWC and state SDMAs; INDRA reads them and issues none of its own.
      </p>
      {error && !alerts ? (
        <ErrorState label="official warnings" error={error} compact />
      ) : alerts && alerts.length === 0 ? (
        <EmptyState title={t('chart.no_warnings_force')} compact />
      ) : !alerts ? (
        <div className="h-40 animate-pulse bg-slate-50 rounded-xl" />
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2 mb-4">
            {byColour.map((c) => (
              <div key={c.key} className="rounded-xl border border-slate-100 p-2 text-center">
                <div className="text-lg font-bold font-mono" style={{ color: c.color }}>{c.n}</div>
                <div className="text-[10px] text-slate-500">{t.severity(c.key)}</div>
              </div>
            ))}
          </div>
          <div className="space-y-1.5">
            {bySender.map(([sender, n]) => (
              <div key={sender} className="grid grid-cols-[130px_1fr_28px] items-center gap-3">
                <span className="text-xs text-slate-700 truncate" title={sender}>{sender}</span>
                <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full rounded-full bg-orange-400" style={{ width: `${(n / topSender) * 100}%` }} />
                </div>
                <span className="text-xs font-mono text-slate-700 text-right">{n}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function AnalyticsPage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const { subscribe } = useIndraWebSocket();
  useEffect(() => {
    let cancelled = false;
    fetchSummaryCounts()
      .then((s) => { if (!cancelled) { setSummary(s); setFailed(false); } })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [refreshTick]);
  // The figures loaded once and never moved.
  useEffect(() => {
    return subscribe('analytics-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) setRefreshTick((t) => t + 1);
    });
  }, [subscribe]);
  useEffect(() => {
    const id = setInterval(() => setRefreshTick((t) => t + 1), 120_000);
    return () => clearInterval(id);
  }, []);

  const show = (n: number | undefined) => (summary && n != null ? n.toLocaleString('en-IN') : '—');

  return (
    <div className="min-h-screen bg-surface">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileMenuOpen}
        onMobileClose={closeMobile}
      />

      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed ? 'md:ml-[68px]' : 'md:ml-[272px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <BarChart3 className="w-5 h-5 text-cyan-400" />
                <h1 className="text-xl font-bold font-mono">{t('nav.analytics')}</h1>
              </div>
              <p className="text-xs text-slate-400">
                Reports, events, official warnings and rainfall, counted from the live database.
              </p>
            </div>
            <div className="flex items-center gap-2 bg-slate-800 px-3 py-1.5 rounded-xl border border-slate-700 text-xs font-mono text-cyan-300">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span>PostgreSQL + PostGIS</span>
            </div>
          </div>

          {failed && (
            <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-100 text-xs font-semibold text-rose-700">
              The summary could not be loaded from the backend.
            </div>
          )}

          {/* Figures from GET /api/dashboard/summary */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Figure
              label={t('kpis.total_reports')}
              value={show(summary?.total_reports)}
              note={summary ? `${summary.total_reports_delta_pct >= 0 ? '+' : ''}${summary.total_reports_delta_pct}% in the last 24 h` : 'all sources'}
              icon={Activity}
            />
            <Figure
              label={t('kpis.verified_events')}
              value={show(summary?.verified_events)}
              note="Auto-published or approved by an operator"
              icon={TrendingUp}
            />
            <Figure
              label={t('kpis.awaiting_review')}
              value={show(summary?.awaiting_review)}
              note="Escalated or quarantined"
              icon={Layers}
            />
            <Figure
              label={t('kpis.active_alerts')}
              value={show(summary?.active_alerts)}
              note="IMD, CWC and SDMA CAP alerts via SACHET"
              icon={ShieldAlert}
            />
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
              <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-blue-600" />
                {t('kpis.reports_24h')}
              </h2>
              <ReportsTrendChart variant="embedded" />
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
              <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-2">
                <Layers className="w-4 h-4 text-indigo-600" />
                {t('dashboard.event_distribution')}
              </h2>
              <EventDistributionChart variant="embedded" />
            </div>
          </div>

          {/* The two live feeds, as stored */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RainfallPanel />
            <WarningsPanel />
          </div>
        </main>
      </div>
    </div>
  );
}
