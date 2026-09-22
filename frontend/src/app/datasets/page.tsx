'use client';

/**
 * Data sources page: the feeds INDRA actually reads, and the ones it does not.
 *
 * This used to be a hardcoded catalogue of feeds that do not exist here — an
 * IMD Doppler radar mosaic at "184 GB / Day", INSAT-3DR channels at "92 GB /
 * Day", "1,540" CWC river gauges, a "420 GB" BigQuery lakehouse — every one
 * marked STREAMING_HEALTHY under a spinning "SYNC PIPELINE: 100% OPERATIONAL".
 * INDRA stores its data in PostgreSQL and reads the five sources below.
 */

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Database, Radio, Users, CloudRain, MapPinned, ShieldCheck, Ban } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchHealth, fetchSummaryCounts, type DashboardSummary, type HealthReport } from '@/lib/api';

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

  useEffect(() => {
    let cancelled = false;
    fetchSummaryCounts()
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { if (!cancelled) setSummary(null); });
    fetchHealth()
      .then((h) => { if (!cancelled) setHealth(h); })
      .catch(() => { if (!cancelled) setHealth(null); });
    return () => { cancelled = true; };
  }, []);

  const weatherUp = health ? health.checks.weather_api?.status === 'up' : null;
  const dbUp = health ? health.checks.database?.status === 'up' : null;

  const sources: Source[] = [
    {
      id: 'citizen-reports',
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
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
            </div>
            <p className="text-xs text-slate-400">
              Everything INDRA reads, where it lands in PostgreSQL, and what is not connected.
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
