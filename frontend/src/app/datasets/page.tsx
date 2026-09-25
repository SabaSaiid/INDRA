'use client';

/**
 * Data sources page: the feeds INDRA actually reads, and the ones it does not.
 *
 * This used to be a hardcoded catalogue of feeds that do not exist here — an
 * IMD Doppler radar mosaic at "184 GB / Day", INSAT-3DR channels at "92 GB /
 * Day", "1,540" CWC river gauges, a "420 GB" BigQuery lakehouse — every one
 * marked STREAMING_HEALTHY under a spinning "SYNC PIPELINE: 100% OPERATIONAL".
 * INDRA stores its data in PostgreSQL and reads the five sources below.
 *
 * Since 24 Sep each card reads GET /api/meta/sources: whether the feed is
 * alive, its newest row, rows in 24 h and in total. Before that the page was a
 * static catalogue and could not tell a stalled poller from a working one.
 * Against an older backend it falls back to the summary and health checks.
 */

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Database, Radio, Users, CloudRain, MapPinned, ShieldCheck, Ban } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import {
  fetchHealth,
  fetchSummaryCounts,
  fetchDataSources,
  type DashboardSummary,
  type HealthReport,
  type DataSourceStatus,
} from '@/lib/api';
import { formatAgo, formatIst } from '@/lib/utils';

interface Source {
  id: string;
  title: string;
  icon: React.ElementType;
  origin: string;
  path: string;
  cadence: string;
  stores: string;
  /** A live figure, or null when the backend could not be asked. */
  live: string | null;
  /** Green or red only when a live check says so; null is neutral. */
  healthy: boolean | null;
  /** The feed's entry in GET /api/meta/sources, when there is one. */
  feed?: string;
}

const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  ok: { label: 'LIVE', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  stale: { label: 'STALE', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  failing: { label: 'FAILING', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
  disabled: { label: 'DISABLED', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
};

function everyLabel(seconds: number | null): string {
  if (!seconds) return 'push';
  return seconds % 60 === 0 ? `every ${seconds / 60} min` : `every ${seconds} s`;
}

function LiveStatus({ status }: { status: DataSourceStatus }) {
  const pill = STATUS_PILL[status.status] ?? STATUS_PILL.stale;
  return (
    <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
      <div className="rounded-lg border border-slate-100 px-2.5 py-1.5">
        <span className="block text-[10px] text-slate-400">Status</span>
        <span className={`inline-block mt-0.5 font-mono font-bold px-1.5 py-0.5 rounded border ${pill.cls}`}>
          {pill.label}
        </span>
      </div>
      <div className="rounded-lg border border-slate-100 px-2.5 py-1.5">
        <span className="block text-[10px] text-slate-400">
          {status.basis === 'push' ? 'Last received' : 'Newest row'}
        </span>
        <span className="font-medium text-slate-800">
          {status.last_success_at ? `${formatIst(status.last_success_at)} IST` : 'never'}
        </span>
        {status.last_success_at && (
          <span className="block text-[10px] text-slate-400">{formatAgo(status.last_success_at)}</span>
        )}
      </div>
      <div className="rounded-lg border border-slate-100 px-2.5 py-1.5">
        <span className="block text-[10px] text-slate-400">Rows, last 24 h</span>
        <span className="font-mono font-semibold text-slate-800">{status.rows_24h.toLocaleString('en-IN')}</span>
      </div>
      <div className="rounded-lg border border-slate-100 px-2.5 py-1.5">
        <span className="block text-[10px] text-slate-400">Rows stored · poll</span>
        <span className="font-mono font-semibold text-slate-800">{status.rows_total.toLocaleString('en-IN')}</span>
        <span className="block text-[10px] text-slate-400">{everyLabel(status.poll_interval_s)}</span>
      </div>
    </div>
  );
}

const NOT_CONNECTED = [
  { name: 'IMD Doppler radar and automatic weather stations', why: 'No feed or API access' },
  { name: 'ISRO INSAT-3D / MOSDAC satellite products', why: 'Not ingested' },
  { name: 'CWC river gauge telemetry', why: 'No public real-time feed used' },
  { name: 'Social media (e.g. X/Twitter)', why: 'No API key; the source type exists, nothing feeds it' },
];

export default function DatasetsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [feeds, setFeeds] = useState<DataSourceStatus[] | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchSummaryCounts()
        .then((s) => { if (!cancelled) setSummary(s); })
        .catch(() => { if (!cancelled) setSummary(null); });
      fetchHealth()
        .then((h) => { if (!cancelled) setHealth(h); })
        .catch(() => { if (!cancelled) setHealth(null); });
      fetchDataSources()
        .then((f) => { if (!cancelled) { setFeeds(f); setCheckedAt(new Date()); } })
        .catch(() => { if (!cancelled) setFeeds(null); });
    };
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const feedStatus = (feed?: string) => (feed && feeds ? feeds.find((f) => f.feed === feed) : undefined);
  const liveCount = feeds ? feeds.filter((f) => f.status === 'ok').length : null;

  const weatherUp = health ? health.checks.weather_api?.status === 'up' : null;
  const dbUp = health ? health.checks.database?.status === 'up' : null;

  const sources: Source[] = [
    {
      id: 'citizen-reports',
      feed: 'citizen',
      title: 'Citizen reports',
      icon: Users,
      origin: 'Anyone, anonymously',
      path: 'POST /api/reports/submit → Redpanda → pipeline',
      cadence: 'As they arrive',
      stores: 'raw_reports (CITIZEN_APP)',
      live: summary ? `${summary.citizen_reports} stored` : null,
      healthy: dbUp,
    },
    {
      id: 'official-dispatch',
      feed: 'official',
      title: 'Official dispatches',
      icon: ShieldCheck,
      origin: 'A Commander or Admin, authenticated, for a trusted field source',
      path: 'POST /api/reports/official',
      cadence: 'As filed',
      stores: 'raw_reports (OFFICIAL_DISPATCH, with who filed it)',
      live: 'Needs a Commander or Admin token',
      healthy: null,
    },
    {
      id: 'open-meteo',
      feed: 'open_meteo',
      title: 'Open-Meteo precipitation',
      icon: CloudRain,
      origin: 'Open-Meteo forecast API (public)',
      path: 'Polled for 6 cities; also read per event, cached 10 min',
      cadence: 'Every 10 minutes',
      stores: 'station_readings (agency OPEN_METEO)',
      live: weatherUp === null ? null : weatherUp ? 'Reachable now' : 'Unreachable now',
      healthy: weatherUp,
    },
    {
      id: 'sachet',
      feed: 'sachet',
      title: 'Official warnings (CAP)',
      icon: Radio,
      origin: 'NDMA SACHET feed: IMD, CWC and state SDMA alerts',
      path: 'RSS index, then each CAP document',
      cadence: 'Every 5 minutes',
      stores: 'agency_alerts',
      live: summary ? `${summary.active_alerts} in force` : null,
      // A count of stored alerts, not a check that the poller is running.
      healthy: null,
    },
    {
      id: 'gazetteer',
      title: 'District gazetteer',
      icon: MapPinned,
      origin: 'Census 2011 district boundaries',
      path: 'data/geo/india_districts.csv, built by scripts/build_gazetteer.py',
      cadence: 'Static, committed',
      stores: '737 districts: names, in-polygon points, bounding boxes',
      live: 'Used to name every report and event',
      healthy: null,
    },
  ];

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
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md">
            <div className="flex items-center gap-2 mb-1">
              <Database className="w-5 h-5 text-indigo-400" />
              <h1 className="text-xl font-bold font-mono">DATA SOURCES</h1>
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                {sources.length} connected
              </span>
              {feeds && (
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  {liveCount} of {feeds.length} feeds live
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              Everything INDRA reads, where it lands in PostgreSQL, and what is not connected.
              {checkedAt && ` Checked ${formatIst(checkedAt)} IST, every minute.`}
            </p>
          </div>

          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            {sources.map((src) => {
              const Icon = src.icon;
              const live = feedStatus(src.feed);
              return (
                <motion.div
                  key={src.id}
                  variants={fadeIn}
                  className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                      <Icon className="w-4 h-4 text-indigo-500" />
                      {src.title}
                    </h2>
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-bold whitespace-nowrap ${
                        src.healthy === null
                          ? 'bg-slate-50 text-slate-500 border-slate-200'
                          : src.healthy
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : 'bg-rose-50 text-rose-700 border-rose-200'
                      }`}
                    >
                      {src.live ?? 'status unknown'}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 bg-slate-50 p-3 rounded-xl">
                    <div>
                      <span className="text-slate-400 block text-[10px]">From</span>
                      <span className="font-medium text-slate-800">{src.origin}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">Cadence</span>
                      <span className="font-medium text-slate-800">{src.cadence}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">Path</span>
                      <span className="font-medium text-slate-800 font-mono text-[11px]">{src.path}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">Stored in</span>
                      <span className="font-medium text-slate-800">{src.stores}</span>
                    </div>
                  </div>
                  {live && <LiveStatus status={live} />}
                </motion.div>
              );
            })}
          </motion.div>

          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
              <Ban className="w-4 h-4 text-slate-400" />
              Not connected
            </h2>
            <ul className="space-y-1.5 text-xs text-slate-600">
              {NOT_CONNECTED.map((row) => (
                <li key={row.name} className="flex items-center justify-between gap-4">
                  <span>{row.name}</span>
                  <span className="text-slate-400 text-right">{row.why}</span>
                </li>
              ))}
            </ul>
          </div>
        </main>
      </div>
    </div>
  );
}
