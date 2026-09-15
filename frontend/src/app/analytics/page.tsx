'use client';

import React from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3,
  TrendingUp,
  Cpu,
  Activity,
  Zap,
  Layers,
  Database,
  Calendar,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import ReportsTrendChart from '@/components/ReportsTrendChart';
import EventDistributionChart from '@/components/EventDistributionChart';
import { fadeIn } from '@/lib/motion';

export default function AnalyticsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

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
                <h1 className="text-xl font-bold font-mono">
                  TELEMETRY ANALYTICS &amp; PREDICTIVE MODELS
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  BIGQUERY ML ENGINE
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Continuous spatio-temporal time-series forecasting, Doppler radar correlation, and deep anomaly detection.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 bg-slate-800 px-3 py-1.5 rounded-xl border border-slate-700 text-xs font-mono text-cyan-300">
                <Cpu className="w-3.5 h-3.5 text-cyan-400" />
                <span>INFERENCE LATENCY: 28ms</span>
              </div>
            </div>
          </div>

          {/* Metric KPI cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Model Confidence Index</span>
                <TrendingUp className="w-4 h-4 text-emerald-500" />
              </div>
              <div className="text-2xl font-bold text-slate-900">96.4%</div>
              <div className="text-[11px] text-emerald-600 font-medium mt-1">
                +1.8% vs last cyclone cycle
              </div>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Radar Doppler Points / Sec</span>
                <Activity className="w-4 h-4 text-blue-500" />
              </div>
              <div className="text-2xl font-bold text-slate-900">1.42M</div>
              <div className="text-[11px] text-blue-600 font-medium mt-1">
                Real-time sweep ingestion
              </div>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Precipitation Anomalies</span>
                <Zap className="w-4 h-4 text-amber-500" />
              </div>
              <div className="text-2xl font-bold text-slate-900">37 Detected</div>
              <div className="text-[11px] text-amber-600 font-medium mt-1">
                Hyper-local storm cells
              </div>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Data Processed (24h)</span>
                <Database className="w-4 h-4 text-indigo-500" />
              </div>
              <div className="text-2xl font-bold text-slate-900">4.82 TB</div>
              <div className="text-[11px] text-indigo-600 font-medium mt-1">
                IMD + ISRO INSAT-3D Feeds
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
              <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-blue-600" />
                Hourly Incident &amp; Telemetry Volume
              </h2>
              <ReportsTrendChart variant="embedded" />
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col">
              <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-2">
                <Layers className="w-4 h-4 text-indigo-600" />
                Meteorological Hazard &amp; Severity Distribution
              </h2>
              <EventDistributionChart variant="embedded" />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
