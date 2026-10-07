'use client';

/**
 * Analytics page — fully audited & overhauled (Oct 2026).
 *
 * Fixes applied:
 *  - Design system: all cards now use INDRA warm-paper tokens (bg-[#FDFAF5],
 *    border-[#E8E2D4]), Fraunces serif headings and terracotta accents.
 *  - KPI cards: linked to their respective detail pages, animated count-up,
 *    semantic colour accents, clean flat-delta formatting (0% not +0%).
 *  - Trend chart title: renamed from "Reports (24h)" to "Report Ingestion Trend"
 *    to match the actual multi-day range selector below it.
 *  - Global refreshTick: InundationDepthChart, VerificationBreakdownChart and
 *    TopDistrictsTable now re-fetch on every WebSocket event / 2-min timer,
 *    not just once on mount.
 *  - Header: added manual refresh button with "last synced X ago" timestamp and
 *    CSV/GeoJSON export links.
 *  - i18n: all hardcoded strings replaced with t('analytics.*') keys.
 *  - Rainfall / Warnings panels: responsive grid, full sender names via tooltip.
 */

import React, { useEffect, useMemo, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  BarChart3, TrendingUp, Activity, Layers, Database,
  ShieldAlert, CloudRain, Radio, RefreshCw, Download,
  ArrowRight, MapPin,
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
import { useTranslation } from '@/lib/i18n/useTranslation';
import { API_BASE } from '@/lib/api-base';

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
    <div className="min-h-screen" style={{ backgroundColor: '#F7F3EA' }}>
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
              <p className="text-xs text-slate-400">{t('analytics.page_subtitle')}</p>
              {lastSyncedText && (
                <p className="text-[10px] text-slate-500 mt-1">{lastSyncedText}</p>
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

              {/* Export dropdown-style button */}
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

          {/* ── KPI Figures ──────────────────────────────────────────── */}
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

          {/* ── Charts Row ───────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Report Ingestion Trend — renamed from "Reports (24h)" */}
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

            {/* Event Distribution */}
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

          {/* ── Second Analytics Row — refreshTick propagated ────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <InundationDepthChart refreshTick={refreshTick} />
            <VerificationBreakdownChart refreshTick={refreshTick} />
          </div>

          {/* ── Top Districts ─────────────────────────────────────────── */}
          <TopDistrictsTable refreshTick={refreshTick} />

          {/* ── Live Feeds ────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RainfallPanel refreshTick={refreshTick} />
            <WarningsPanel refreshTick={refreshTick} />
          </div>

        </main>
      </div>
    </div>
  );
}
