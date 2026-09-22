'use client';

/**
 * Analytics. The two charts always read the backend; the figures above them
 * used to be invented — a "BIGQUERY ML ENGINE" at "28ms" inference latency, a
 * "96.4%" model confidence index, "1.42M" Doppler radar points per second,
 * "37" precipitation anomalies and "4.82 TB" of IMD and ISRO data a day, none
 * of which INDRA has. They are now counts from GET /api/dashboard/summary.
 */

import React, { useEffect, useState } from 'react';
import { BarChart3, TrendingUp, Activity, Layers, Database, ShieldAlert } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import ReportsTrendChart from '@/components/ReportsTrendChart';
import EventDistributionChart from '@/components/EventDistributionChart';
import { fetchSummaryCounts, type DashboardSummary } from '@/lib/api';

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

export default function AnalyticsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchSummaryCounts()
      .then((s) => { if (!cancelled) { setSummary(s); setFailed(false); } })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <BarChart3 className="w-5 h-5 text-cyan-400" />
                <h1 className="text-xl font-bold font-mono">ANALYTICS</h1>
              </div>
              <p className="text-xs text-slate-400">
                Report volume and event distribution, counted from the live database.
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
              label="Reports stored"
              value={show(summary?.total_reports)}
              note={summary ? `${summary.total_reports_delta_pct >= 0 ? '+' : ''}${summary.total_reports_delta_pct}% in the last 24 h` : 'all sources'}
              icon={Activity}
            />
            <Figure
              label="Verified events"
              value={show(summary?.verified_events)}
              note="Auto-published or approved by an operator"
              icon={TrendingUp}
            />
            <Figure
              label="Awaiting review"
              value={show(summary?.awaiting_review)}
              note="Escalated or quarantined"
              icon={Layers}
            />
            <Figure
              label="Official warnings in force"
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
                Reports per day
              </h2>
              <ReportsTrendChart variant="embedded" />
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
              <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-2">
                <Layers className="w-4 h-4 text-indigo-600" />
                Events by hazard and severity
              </h2>
              <EventDistributionChart variant="embedded" />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
