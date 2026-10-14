'use client';

/**
 * Analytics page — Tab-based overhaul (Oct 2026).
 *
 * 5 tabs:
 *  1. Overview         — existing charts (trend, distribution, inundation, verification, districts, rainfall, warnings)
 *  2. Source Intelligence — data feed health, ingestion contribution, kind breakdown
 *  3. Geo Risk         — state leaderboard, H3 heatmap summary, district stacked bar
 *  4. AI Pipeline      — ML Observatory (auth-gated), throughput metrics, verification weights
 *  5. Hazard Trends    — hazard grouped bars (24h/7d/30d), severity matrix, warnings-events alignment
 *
 * Architecture:
 *  - KPI cards + header stay above the tab bar (always visible)
 *  - Only the active tab is mounted; inactive tabs are unmounted (no parallel fetches)
 *  - refreshTick is propagated to every active tab panel
 *  - WebSocket events bump refreshTick → all charts re-fetch
 *  - Periodic heartbeat every 2 min
 */

import React, { useEffect, useMemo, useState, useCallback } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart3, TrendingUp, Activity, Layers, Database,
  ShieldAlert, CloudRain, Radio, RefreshCw, Download,
  ArrowRight, MapPin, LayoutDashboard, Brain, Zap, Lock,
} from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import ReportsTrendChart from '@/components/ReportsTrendChart';
import EventDistributionChart from '@/components/EventDistributionChart';
import InundationDepthChart from '@/components/InundationDepthChart';
import TopDistrictsTable from '@/components/TopDistrictsTable';
import VerificationBreakdownChart from '@/components/VerificationBreakdownChart';
import AiModelObservatory from '@/components/AiModelObservatory';
import DataSourceHealthGrid from '@/components/DataSourceHealthGrid';
import StateRiskLeaderboard from '@/components/StateRiskLeaderboard';
import GeoHeatmapSummaryCard from '@/components/GeoHeatmapSummaryCard';
import PipelineThroughputPanel from '@/components/PipelineThroughputPanel';
import HazardTrendChart from '@/components/HazardTrendChart';
import HazardSeverityMatrix from '@/components/HazardSeverityMatrix';
import WarningsEventsAlignment from '@/components/WarningsEventsAlignment';
import RainfallContextMiniPanel from '@/components/RainfallContextMiniPanel';
import {
  ApiError,
  fetchSummaryCounts,
  fetchStations,
  fetchAgencyAlerts,
  fetchMlObservatory,
  type DashboardSummary,
  type RainfallStation,
  type AgencyAlert,
  type MlObservatoryData,
} from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { formatAgo, formatIst } from '@/lib/utils';
import { useSettings, formatRainfall } from '@/lib/useSettings';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { getSession } from '@/lib/auth';
import { API_BASE } from '@/lib/api-base';

// ─── Tab definition ───────────────────────────────────────────────────────────

type TabId = 'overview' | 'sources' | 'geo' | 'ai-pipeline' | 'hazard-trends';

const TABS: Array<{ id: TabId; labelKey: string; icon: React.ElementType }> = [
  { id: 'overview',       labelKey: 'analytics.tab_overview',      icon: LayoutDashboard },
  { id: 'sources',        labelKey: 'analytics.tab_sources',       icon: Radio },
  { id: 'geo',            labelKey: 'analytics.tab_geo',           icon: MapPin },
  { id: 'ai-pipeline',   labelKey: 'analytics.tab_ai_pipeline',   icon: Brain },
  { id: 'hazard-trends', labelKey: 'analytics.tab_hazard_trends', icon: TrendingUp },
];

// ─── KPI Figure card ──────────────────────────────────────────────────────────

interface FigureProps {
  label: string;
  value: string;
  note: string;
  icon: React.ElementType;
  href?: string;
  accentColor?: string;
}

function Figure({ label, value, note, icon: Icon, href, accentColor = '#2563EB' }: FigureProps) {
  const inner = (
    <div
      className="bg-[#FDFAF5] p-4 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-1 group relative overflow-hidden transition-all duration-200 hover:shadow-md hover:-translate-y-0.5"
      style={{ cursor: href ? 'pointer' : 'default' }}
    >
      {/* Semantic accent bar */}
      <div
        className="absolute top-0 left-0 right-0 h-0.5 rounded-t-xl opacity-80"
        style={{ background: accentColor }}
      />
      <div className="flex items-center justify-between text-[11px] text-[#7A8599] mt-1">
        <span className="font-medium">{label}</span>
        <Icon className="w-4 h-4" style={{ color: accentColor }} />
      </div>
      <div
        className="text-2xl font-bold tabular-nums"
        style={{ fontFamily: 'JetBrains Mono, monospace', color: '#1B2432' }}
      >
        {value}
      </div>
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-[#7A8599] font-medium">{note}</div>
        {href && (
          <span className="text-[10px] text-[#2563EB] font-semibold flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            View <ArrowRight className="w-2.5 h-2.5" />
          </span>
        )}
      </div>
    </div>
  );
  if (href) return <Link href={href}>{inner}</Link>;
  return inner;
}

// ─── IMD rainfall intensity classification ────────────────────────────────────

function rainfallClass(mm: number | null): { label: string; color: string } {
  if (mm == null) return { label: 'no reading', color: '#94A3B8' };
  if (mm < 2.5)   return { label: 'Very light / dry', color: '#94A3B8' };
  if (mm < 15.6)  return { label: 'Light',            color: '#60A5FA' };
  if (mm < 64.5)  return { label: 'Moderate',         color: '#2563EB' };
  if (mm < 115.6) return { label: 'Heavy',            color: '#F59E0B' };
  if (mm < 204.5) return { label: 'Very heavy',       color: '#EA580C' };
  return                  { label: 'Extremely heavy', color: '#DC2626' };
}

// ─── Rainfall panel ───────────────────────────────────────────────────────────

function RainfallPanel({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [stations, setStations] = useState<RainfallStation[] | null>(null);
  const [error, setError]       = useState<unknown>(null);
  const { settings }            = useSettings();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchStations()
        .then((rows) => { if (!cancelled) { setStations(rows); setError(null); } })
        .catch((err) => { if (!cancelled) setError(err); });
    load();
    const id = setInterval(load, 300_000);
    return () => { cancelled = true; clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  const max = useMemo(
    () => Math.max(10, ...(stations ?? []).map((s) => s.rainfall_mm ?? 0)),
    [stations]
  );

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-1">
        <h2
          className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <CloudRain className="w-4 h-4 text-blue-500" />
          {t('analytics.rainfall_title')}
        </h2>
        <span className="text-[10px] font-mono text-[#7A8599] text-right">Open-Meteo · every 10 min</span>
      </div>
      <p className="text-[11px] text-[#7A8599] mb-3">{t('analytics.rainfall_subtitle')}</p>

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
        <EmptyState title={t('analytics.rainfall_no_data')} hint="The station poller may be switched off." compact />
      ) : !stations ? (
        <div className="h-40 animate-pulse bg-[#F0EBE0] rounded-xl" />
      ) : (
        <div className="space-y-2.5">
          {stations.map((st) => {
            const cls = rainfallClass(st.rainfall_mm);
            const pct = Math.max(2, ((st.rainfall_mm ?? 0) / max) * 100);
            return (
              <div key={st.station_code} className="grid grid-cols-[96px_1fr_100px_64px] items-center gap-3">
                <span className="text-xs font-medium text-[#1B2432] truncate" title={st.station_name}>
                  {st.station_name}
                </span>
                <div className="h-2 rounded-full bg-[#E8E2D4] overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: cls.color }} />
                </div>
                <span className="text-xs tabular-nums text-[#4A5568]">
                  <strong className="font-mono">{st.rainfall_mm == null ? '—' : formatRainfall(st.rainfall_mm, settings.rainUnit)}</strong>
                  <span className="block text-[10px] text-[#7A8599]">{cls.label}</span>
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
          <p className="text-[10px] text-[#7A8599] pt-1">
            Newest observation {formatIst(stations[0]?.recorded_at)} IST ({formatAgo(stations[0]?.recorded_at)}). Sparklines: last 48 h.
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Warnings panel ───────────────────────────────────────────────────────────

const WARNING_COLOURS: Array<{ key: string; name: string; color: string; bg: string }> = [
  { key: 'CRITICAL', name: 'Red',      color: '#DC2626', bg: '#FEF2F2' },
  { key: 'HIGH',     name: 'Orange',   color: '#F97316', bg: '#FFF7ED' },
  { key: 'MODERATE', name: 'Yellow',   color: '#EAB308', bg: '#FEFCE8' },
  { key: 'ADVISORY', name: 'Advisory', color: '#10B981', bg: '#ECFDF5' },
];

function WarningsPanel({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [alerts, setAlerts] = useState<AgencyAlert[] | null>(null);
  const [error, setError]   = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAgencyAlerts(200)
        .then((rows) => { if (!cancelled) { setAlerts(rows); setError(null); } })
        .catch((err) => { if (!cancelled) setError(err); });
    load();
    const id = setInterval(load, 120_000);
    return () => { cancelled = true; clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

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
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-1">
        <h2
          className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <Radio className="w-4 h-4 text-orange-500" />
          {t('chart.warnings')}
        </h2>
        <span className="text-[10px] font-mono text-[#7A8599] text-right">{t('analytics.warnings_note')}</span>
      </div>
      <p className="text-[11px] text-[#7A8599] mb-3">{t('analytics.warnings_subtitle')}</p>

      {error && !alerts ? (
        <ErrorState label="official warnings" error={error} compact />
      ) : alerts && alerts.length === 0 ? (
        <EmptyState title={t('chart.no_warnings_force')} compact />
      ) : !alerts ? (
        <div className="h-40 animate-pulse bg-[#F0EBE0] rounded-xl" />
      ) : (
        <>
          {/* Severity badge row */}
          <div className="grid grid-cols-4 gap-2 mb-4">
            {byColour.map((c) => (
              <Link
                key={c.key}
                href={`/early-warnings?severity=${c.key.toLowerCase()}`}
                className="rounded-xl border p-2 text-center transition-all hover:shadow-sm hover:-translate-y-0.5"
                style={{ borderColor: `${c.color}33`, backgroundColor: c.bg }}
                title={`View ${c.name} warnings`}
              >
                <div className="text-lg font-bold font-mono" style={{ color: c.color }}>{c.n}</div>
                <div className="text-[10px] text-[#7A8599]">{t.severity(c.key)}</div>
              </Link>
            ))}
          </div>

          {/* Agency sender bars */}
          <div className="space-y-1.5">
            {bySender.map(([sender, n]) => (
              <div key={sender} className="grid grid-cols-[1fr_auto] items-center gap-3">
                <div className="min-w-0">
                  <span
                    className="text-xs text-[#1B2432] truncate block"
                    title={sender}
                  >
                    {sender}
                  </span>
                  <div className="h-1.5 rounded-full bg-[#E8E2D4] overflow-hidden mt-1">
                    <div
                      className="h-full rounded-full bg-orange-400 transition-all duration-500"
                      style={{ width: `${(n / topSender) * 100}%` }}
                    />
                  </div>
                </div>
                <span className="text-xs font-mono text-[#4A5568] font-semibold tabular-nums">{n}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── AI Pipeline Tab — auth-gated container ───────────────────────────────────

function AiPipelineTab({ refreshTick }: { refreshTick: number }) {
  const [observatory, setObservatory] = useState<MlObservatoryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const session = getSession();

  useEffect(() => {
    if (!session) { setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    fetchMlObservatory()
      .then((d) => { if (!cancelled) { setObservatory(d); setError(null); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err?.message ?? 'Failed to load'); setLoading(false); } });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick, session?.accessToken]);

  // Not signed in
  if (!session) {
    return (
      <div className="bg-[#FDFAF5] border border-[#E8E2D4] rounded-2xl p-8 sm:p-12 shadow-xs text-center max-w-xl mx-auto flex flex-col items-center gap-4 my-6">
        <div className="w-14 h-14 rounded-2xl bg-[#F0EBE0] border border-[#E8E2D4] flex items-center justify-center text-[#B5482E] shadow-2xs">
          <Lock className="w-7 h-7 text-[#B5482E]" />
        </div>
        <div className="space-y-1.5">
          <h3 className="font-bold text-[#1B2432] text-base" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
            Tactical AI Pipeline Security Gate
          </h3>
          <p className="text-xs text-[#7A8599] max-w-md leading-relaxed">
            IndicBERT NLP classifications, SAM-2 spatial confidence, and DBSCAN consensus weights require Analyst or Commander clearance to inspect.
          </p>
        </div>
        <div className="pt-2 flex items-center gap-3">
          <Link
            href="/operator-profile"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#B5482E] hover:bg-[#9E3E26] text-white text-xs font-semibold shadow-xs transition-all hover:-translate-y-0.5"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Sign in as Analyst</span>
          </Link>
        </div>
      </div>
    );
  }

  // Loading
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-12 animate-pulse bg-[#F0EBE0] rounded-xl" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-28 animate-pulse bg-[#F0EBE0] rounded-xl" />
          ))}
        </div>
        <div className="h-64 animate-pulse bg-[#F0EBE0] rounded-xl" />
      </div>
    );
  }

  // Error
  if (error && !observatory) {
    return <ErrorState label="AI observatory" error={error} />;
  }

  return (
    <div className="space-y-6">
      {/* ML Observatory (the existing component) */}
      <AiModelObservatory />

      {/* Throughput metrics + weights (only when data loaded) */}
      {observatory && (
        <PipelineThroughputPanel
          telemetry={observatory.live_telemetry}
          weights={observatory.consensus_weights}
        />
      )}

      {/* Verification confidence chart */}
      <VerificationBreakdownChart refreshTick={refreshTick} />
    </div>
  );
}

// ─── Analytics page ───────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [activeTab, setActiveTab]       = useState<TabId>('overview');
  const [summary, setSummary]           = useState<DashboardSummary | null>(null);
  const [failed, setFailed]             = useState(false);
  const [refreshTick, setRefreshTick]   = useState(0);
  const [lastSynced, setLastSynced]     = useState<Date | null>(null);
  const [refreshing, setRefreshing]     = useState(false);
  const { subscribe }                   = useIndraWebSocket();

  const doRefresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  const handleManualRefresh = useCallback(async () => {
    setRefreshing(true);
    doRefresh();
    await new Promise((r) => setTimeout(r, 700));
    setRefreshing(false);
  }, [doRefresh]);

  // Fetch summary on mount and on every refreshTick
  useEffect(() => {
    let cancelled = false;
    fetchSummaryCounts()
      .then((s) => {
        if (!cancelled) {
          setSummary(s);
          setFailed(false);
          setLastSynced(new Date());
        }
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [refreshTick]);

  // WebSocket events bump the refreshTick → all charts re-fetch together
  useEffect(() => {
    return subscribe('analytics-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        doRefresh();
      }
    });
  }, [subscribe, doRefresh]);

  // Periodic heartbeat every 2 min
  useEffect(() => {
    const id = setInterval(doRefresh, 120_000);
    return () => clearInterval(id);
  }, [doRefresh]);

  const show = (n: number | undefined) =>
    summary && n != null ? n.toLocaleString('en-IN') : '—';

  // Flat delta formatting: 0 → "0%", not "+0%"
  const deltaPct = summary?.total_reports_delta_pct ?? 0;
  const deltaText = deltaPct === 0
    ? `0% in the last 24 h`
    : `${deltaPct > 0 ? '+' : ''}${deltaPct}% in the last 24 h`;

  const lastSyncedText = lastSynced
    ? `${t('analytics.last_synced')} ${formatAgo(lastSynced.toISOString())}`
    : '';

  return (
    <div className="min-h-screen bg-surface-bg text-text">
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

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-5">

          {/* ── Header ───────────────────────────────────────────────── */}
          <div
            className="text-white p-5 rounded-xl border shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4"
            style={{ background: 'linear-gradient(135deg, #1B2432 0%, #26314A 100%)', borderColor: '#2E3D56' }}
          >
            <div>
              <div className="flex items-center gap-2 mb-1">
                <BarChart3 className="w-5 h-5 text-cyan-400" />
                <h1
                  className="text-xl font-bold"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  {t('analytics.page_title')}
                </h1>
              </div>
              <p className="text-xs text-slate-300">{t('analytics.page_subtitle')}</p>
              {lastSyncedText && (
                <p className="text-[10px] text-slate-300 mt-1">{lastSyncedText}</p>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {/* Database badge */}
              <div className="flex items-center gap-2 bg-slate-800/70 px-3 py-1.5 rounded-lg border border-slate-700 text-xs font-mono text-cyan-300">
                <Database className="w-3.5 h-3.5 text-cyan-400" />
                <span>PostgreSQL + PostGIS</span>
              </div>

              {/* Manual refresh */}
              <button
                type="button"
                onClick={handleManualRefresh}
                disabled={refreshing}
                className="flex items-center gap-1.5 bg-slate-800/70 hover:bg-slate-700/70 px-3 py-1.5 rounded-lg border border-slate-700 text-xs font-medium text-slate-300 hover:text-white transition-all disabled:opacity-60"
                title={t('analytics.refresh')}
              >
                <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
                <span>{t('analytics.refresh')}</span>
              </button>

              {/* Export */}
              <a
                href={`${API_BASE}/api/events/export?format=csv`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 bg-[#B5482E]/80 hover:bg-[#B5482E] px-3 py-1.5 rounded-lg border border-[#A03D25] text-xs font-medium text-white transition-all"
                title={t('analytics.export_data')}
              >
                <Download className="w-3.5 h-3.5" />
                <span>{t('analytics.export_data')}</span>
              </a>
            </div>
          </div>

          {/* Error banner */}
          {failed && (
            <div role="alert" className="p-3 rounded-xl bg-red-50 border border-red-100 text-xs font-semibold text-red-700">
              The summary could not be loaded from the backend.
            </div>
          )}

          {/* ── KPI Figures (always visible) ──────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Figure
              label={t('kpis.total_reports')}
              value={show(summary?.total_reports)}
              note={summary ? deltaText : 'all sources'}
              icon={Activity}
              href="/reports"
              accentColor="#2563EB"
            />
            <Figure
              label={t('kpis.verified_events')}
              value={show(summary?.verified_events)}
              note="Auto-published or approved by an operator"
              icon={TrendingUp}
              href="/events"
              accentColor="#10B981"
            />
            <Figure
              label={t('kpis.awaiting_review')}
              value={show(summary?.awaiting_review)}
              note="Escalated or quarantined"
              icon={Layers}
              href="/events?status=review"
              accentColor="#F59E0B"
            />
            <Figure
              label={t('kpis.active_alerts')}
              value={show(summary?.active_alerts)}
              note="IMD, CWC and SDMA CAP alerts via SACHET"
              icon={ShieldAlert}
              href="/early-warnings"
              accentColor="#EF4444"
            />
          </div>

          {/* ── Segmented Floating Tab Controller ────────────────────────── */}
          <div className="space-y-6">
            <div className="bg-[#F0EBE0]/80 border border-[#E8E2D4] p-1.5 rounded-2xl shadow-xs backdrop-blur-md flex items-center gap-1 overflow-x-auto scrollbar-none">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    id={`analytics-tab-${tab.id}`}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`relative flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs sm:text-[13px] font-semibold whitespace-nowrap transition-all shrink-0 cursor-pointer select-none ${
                      isActive
                        ? 'text-[#1B2432]'
                        : 'text-[#69768A] hover:text-[#1B2432] hover:bg-black/[0.03]'
                    }`}
                    aria-selected={isActive}
                    role="tab"
                  >
                    {isActive && (
                      <motion.div
                        layoutId="activeAnalyticsTabIndicator"
                        className="absolute inset-0 bg-[#FDFAF5] rounded-xl shadow-xs border border-[#E8E2D4]"
                        transition={{ type: 'spring', stiffness: 420, damping: 32 }}
                      />
                    )}
                    <span className="relative z-10 flex items-center gap-2">
                      <Icon className={`w-4 h-4 shrink-0 transition-colors ${isActive ? 'text-[#B5482E]' : 'text-[#7A8599]'}`} />
                      <span>{t(tab.labelKey)}</span>
                      {(() => {
                        if (tab.id === 'overview') {
                          const count = summary?.total_reports;
                          if (!count) return null;
                          const formatted = count >= 1000 ? `${(count / 1000).toFixed(1)}k` : `${count}`;
                          return (
                            <span
                              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-md transition-colors ${
                                isActive
                                  ? 'bg-[#B5482E]/10 text-[#B5482E]'
                                  : 'bg-[#E8E2D4]/70 text-[#7A8599]'
                              }`}
                            >
                              {formatted}
                            </span>
                          );
                        }
                        if (tab.id === 'sources') {
                          return (
                            <span className="flex items-center gap-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 font-semibold">
                              <span className="relative flex h-1.5 w-1.5">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                              </span>
                              Live
                            </span>
                          );
                        }
                        if (tab.id === 'geo') {
                          return (
                            <span
                              className={`text-[10px] font-mono font-medium px-1.5 py-0.5 rounded-md transition-colors ${
                                isActive ? 'bg-blue-500/10 text-blue-700 font-semibold' : 'bg-[#E8E2D4]/70 text-[#7A8599]'
                              }`}
                            >
                              Pan-India
                            </span>
                          );
                        }
                        if (tab.id === 'ai-pipeline') {
                          const session = getSession();
                          if (!session) {
                            return (
                              <span className="flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-amber-500/15 text-amber-800 font-bold">
                                <Lock className="w-2.5 h-2.5" />
                                Auth
                              </span>
                            );
                          }
                          return (
                            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-purple-500/15 text-purple-700 font-bold">
                              v1.0
                            </span>
                          );
                        }
                        if (tab.id === 'hazard-trends') {
                          const alerts = summary?.active_alerts ?? 0;
                          return (
                            <span
                              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-md transition-colors ${
                                alerts > 0
                                  ? 'bg-rose-500/15 text-rose-700'
                                  : 'bg-[#E8E2D4]/70 text-[#7A8599]'
                              }`}
                            >
                              {alerts > 0 ? `${alerts} alert${alerts > 1 ? 's' : ''}` : 'Active'}
                            </span>
                          );
                        }
                        return null;
                      })()}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Tab content area with AnimatePresence */}
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                className="space-y-6"
              >
                {/* ── Tab 1: Overview ─────────────────────────────────── */}
                {activeTab === 'overview' && (
                  <>
                    {/* Charts Row */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col">
                        <h2
                          className="text-sm font-bold text-[#1B2432] mb-0.5 flex items-center gap-2"
                          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                        >
                          <TrendingUp className="w-4 h-4 text-blue-500" />
                          {t('analytics.ingestion_trend_title')}
                        </h2>
                        <p className="text-[11px] text-[#7A8599] mb-2">{t('analytics.ingestion_trend_subtitle')}</p>
                        <ReportsTrendChart variant="embedded" />
                      </div>

                      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col">
                        <h2
                          className="text-sm font-bold text-[#1B2432] mb-0.5 flex items-center gap-2"
                          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                        >
                          <Layers className="w-4 h-4 text-indigo-500" />
                          {t('dashboard.event_distribution')}
                        </h2>
                        <p className="text-[11px] text-[#7A8599] mb-2">
                          {summary && `${summary.verified_events.toLocaleString('en-IN')} events total`}
                        </p>
                        <EventDistributionChart variant="embedded" />
                      </div>
                    </div>

                    {/* Second row */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <InundationDepthChart refreshTick={refreshTick} />
                      <VerificationBreakdownChart refreshTick={refreshTick} />
                    </div>

                    {/* Top Districts */}
                    <TopDistrictsTable refreshTick={refreshTick} />

                    {/* Live Feeds */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <RainfallPanel refreshTick={refreshTick} />
                      <WarningsPanel refreshTick={refreshTick} />
                    </div>
                  </>
                )}

                {/* ── Tab 2: Source Intelligence ───────────────────────── */}
                {activeTab === 'sources' && (
                  <DataSourceHealthGrid refreshTick={refreshTick} />
                )}

                {/* ── Tab 3: Geo Risk ──────────────────────────────────── */}
                {activeTab === 'geo' && (
                  <div className="space-y-6">
                    <StateRiskLeaderboard refreshTick={refreshTick} />
                    <GeoHeatmapSummaryCard refreshTick={refreshTick} />
                  </div>
                )}

                {/* ── Tab 4: AI Pipeline ──────────────────────────────── */}
                {activeTab === 'ai-pipeline' && (
                  <AiPipelineTab refreshTick={refreshTick} />
                )}

                {/* ── Tab 5: Hazard Trends ─────────────────────────────── */}
                {activeTab === 'hazard-trends' && (
                  <div className="space-y-6">
                    <HazardTrendChart refreshTick={refreshTick} />
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <HazardSeverityMatrix refreshTick={refreshTick} />
                      <WarningsEventsAlignment refreshTick={refreshTick} />
                    </div>
                    <RainfallContextMiniPanel refreshTick={refreshTick} />
                  </div>
                )}

              </motion.div>
            </AnimatePresence>
          </div>

        </main>
      </div>
    </div>
  );
}
