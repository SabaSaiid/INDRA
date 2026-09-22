'use client';

import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';
import { Compass, Radio, Shield, MapPin } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { fadeIn } from '@/lib/motion';
import { useSidebar } from '@/lib/useSidebar';
import { fetchEvents, fetchSummaryCounts, fetchTeams } from '@/lib/api';

const GlobeEventMap = dynamic(() => import('@/components/client-only/GlobeEventMap'), {
  ssr: false,
  loading: () => <MapCardSkeleton />,
});

export default function LiveMapPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  // The header counts what the map below actually draws. It used to read
  // "Tracking: Cyclone DANA", "Sensors: 4 Active Feeds" and "NDRF Units:
  // 8 Deployed" whatever the data, under an "INSAT-3DR / MOSDAC / IMD
  // Telemetry" tagline for feeds INDRA does not read.
  const [eventCount, setEventCount] = useState<number | null>(null);
  const [warningCount, setWarningCount] = useState<number | null>(null);
  const [deployedCount, setDeployedCount] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchEvents({ time_range: '7d' })
      .then((rows) => { if (!cancelled) setEventCount(rows.length); })
      .catch(() => { if (!cancelled) setEventCount(null); });
    fetchSummaryCounts()
      .then((s) => { if (!cancelled) setWarningCount(s.active_alerts); })
      .catch(() => { if (!cancelled) setWarningCount(null); });
    fetchTeams()
      .then((rows) => {
        if (!cancelled) setDeployedCount(rows.filter((t) => t.status === 'DEPLOYED').length);
      })
      .catch(() => { if (!cancelled) setDeployedCount(null); });
    return () => { cancelled = true; };
  }, []);

  const show = (n: number | null) => (n === null ? '—' : String(n));

  return (
    <div className="min-h-screen bg-surface">
      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileMenuOpen}
        onMobileClose={closeMobile}
      />

      {/* Main Content Area */}
      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1700px] mx-auto space-y-4">
          {/* Header Banner */}
          <motion.div
            variants={fadeIn}
            initial="hidden"
            animate="visible"
            className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-gradient-to-r from-slate-900 via-slate-850 to-blue-950 text-white p-4 lg:p-5 rounded-2xl shadow-md border border-slate-800"
          >
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-blue-300">
                  Live map
                </span>
                <span className="text-slate-600">•</span>
                <span className="text-xs text-slate-400 font-mono">
                  INDRA events · SACHET warnings · citizen reports
                </span>
              </div>
              <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                <Compass className="w-6 h-6 text-blue-400" />
                Events, warnings and reports on one map
              </h1>
              <p className="text-xs lg:text-sm text-slate-300 mt-0.5">
                Fused events, official warnings that resolve to a district, and citizen reports not
                yet part of an event, each drawn as its own layer.
              </p>
            </div>

            {/* Counts of what the map draws */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <MapPin className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-slate-300">Events (7 days):</span>
                <span className="font-semibold text-white">{show(eventCount)}</span>
              </div>
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <Radio className="w-3.5 h-3.5 text-cyan-400" />
                <span className="text-slate-300">Official warnings:</span>
                <span className="font-semibold text-white">{show(warningCount)}</span>
              </div>
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <Shield className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-slate-300">Teams deployed:</span>
                <span className="font-semibold text-white">{show(deployedCount)}</span>
              </div>
            </div>
          </motion.div>

          {/* 3D Globe Event Map */}
          <div className="w-full">
            <GlobeEventMap />
          </div>
        </main>
      </div>
    </div>
  );
}
