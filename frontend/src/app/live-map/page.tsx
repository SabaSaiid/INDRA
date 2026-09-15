'use client';

import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';
import {
  Map,
  Compass,
  Radio,
  Satellite,
  Shield,
  AlertTriangle,
  Waves,
  Wind,
  Layers,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { fadeIn } from '@/lib/motion';
import { useSidebar } from '@/lib/useSidebar';

const GlobeEventMap = dynamic(() => import('@/components/GlobeEventMap'), {
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[260px]'
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
                <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-400 animate-ping" />
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-blue-300">
                  Planetary Observation Console
                </span>
                <span className="text-slate-600">•</span>
                <span className="text-xs text-slate-400 font-mono">INSAT-3DR / MOSDAC / IMD Telemetry</span>
              </div>
              <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                <Compass className="w-6 h-6 text-blue-400" />
                3D Geospatial Intelligence & Severe Event Radar
              </h1>
              <p className="text-xs lg:text-sm text-slate-300 mt-0.5">
                Seamless 3D spherical Earth globe with adaptive subcontinental zoom, real-time alert markers, and cyclone tracks.
              </p>
            </div>

            {/* Quick Stats Badges */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <Radio className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-slate-300">Tracking:</span>
                <span className="font-semibold text-white">Cyclone DANA</span>
              </div>
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <Satellite className="w-3.5 h-3.5 text-cyan-400" />
                <span className="text-slate-300">Sensors:</span>
                <span className="font-semibold text-white">4 Active Feeds</span>
              </div>
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 border border-white/10 text-xs">
                <Shield className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-slate-300">NDRF Units:</span>
                <span className="font-semibold text-white">8 Deployed</span>
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
