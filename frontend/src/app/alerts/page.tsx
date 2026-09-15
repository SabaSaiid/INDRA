'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Bell,
  AlertOctagon,
  AlertTriangle,
  Info,
  ShieldAlert,
  Radio,
  ExternalLink,
  MapPin,
  Clock,
  ChevronRight,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';

const mockAlerts = [
  {
    id: 'ALT-IMD-2026-901',
    level: 'RED',
    title: 'RED WARNING: Severe Atmospheric Flash Flood & Cloudburst Potential',
    agency: 'IMD Eastern Regional Centre',
    issuedAt: '12 mins ago',
    validUntil: '15 Sep 2026, 06:00 IST',
    zones: ['Patna', 'Vaishali', 'Muzaffarpur', 'Samastipur'],
    description:
      'Continuous hyper-localized precipitation exceeding 120mm/hr detected by Doppler radar. Extreme inundation imminent in low-lying river catchments.',
    actionRequired: 'Immediate evacuation of floodplains and deployment of NDRF quick-response teams.',
  },
  {
    id: 'ALT-IMD-2026-902',
    level: 'RED',
    title: 'CYCLONIC STORM WARNING: Cyclone "Marut" Coastal Landfall Advisory',
    agency: 'Cyclone Warning Division, New Delhi',
    issuedAt: '45 mins ago',
    validUntil: '15 Sep 2026, 18:00 IST',
    zones: ['Puri', 'Jagatsinghpur', 'Kendrapara', 'Bhadrak'],
    description:
      'Very Severe Cyclonic Storm with sustained winds 130-150 km/h gusting to 165 km/h. Tidal surge up to 2.5m anticipated during high tide.',
    actionRequired: 'Port signal 8 hoisted. Fishermen advised total suspension of fishing operations.',
  },
  {
    id: 'ALT-IMD-2026-903',
    level: 'ORANGE',
    title: 'ORANGE ALERT: Landslide & Hill Slope Debris Discharge',
    agency: 'Geological Survey of India & IMD Trivandrum',
    issuedAt: '2h ago',
    validUntil: '15 Sep 2026, 12:00 IST',
    zones: ['Wayanad', 'Idukki', 'Kozhikode Ghats'],
    description:
      'Soil moisture saturation index at 98.4%. High susceptibility to slope slips along NH-766.',
    actionRequired: 'Night travel prohibited on ghat roads. NDRF team pre-positioned at Meppadi.',
  },
  {
    id: 'ALT-IMD-2026-904',
    level: 'ORANGE',
    title: 'ORANGE ALERT: Upper Yamuna River Water Discharge Advisory',
    agency: 'Central Water Commission (CWC)',
    issuedAt: '3h ago',
    validUntil: '16 Sep 2026, 00:00 IST',
    zones: ['Hathnikund to Delhi Lowlands'],
    description:
      'Hathnikund barrage released 2,85,000 cusecs water upstream. Water levels expected to breach danger mark (205.33m) by tomorrow dawn.',
    actionRequired: 'Relocation of cattle and riverside settlements in Shahdara & Mayur Vihar.',
  },
];

export default function AlertsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [selectedLevel, setSelectedLevel] = useState<string>('ALL');

  const filtered = mockAlerts.filter(
    (alt) => selectedLevel === 'ALL' || alt.level === selectedLevel
  );

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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[260px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-gradient-to-r from-rose-950 via-slate-900 to-slate-950 text-white p-5 rounded-2xl border border-rose-900/60 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <ShieldAlert className="w-5 h-5 text-rose-400 animate-pulse" />
                <h1 className="text-xl font-bold font-mono tracking-wide">
                  EARLY WARNING &amp; HAZARD BULLETINS
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-500/30 text-rose-300 border border-rose-500/50 animate-pulse">
                  4 CRITICAL ACTIVE
                </span>
              </div>
              <p className="text-xs text-slate-300">
                Official NDMA, IMD, and CWC real-time emergency hazard warnings and broadcast alerts.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-rose-800/40 text-xs font-mono text-rose-300">
                <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
                CAP-INDIA BROADCAST ONLINE
              </div>
            </div>
          </div>

          {/* Level Filter */}
          <div className="flex items-center gap-2">
            {['ALL', 'RED', 'ORANGE'].map((lvl) => (
              <button
                key={lvl}
                onClick={() => setSelectedLevel(lvl)}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                  selectedLevel === lvl
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
                }`}
              >
                {lvl === 'RED' ? '🔴 RED WARNINGS' : lvl === 'ORANGE' ? '🟠 ORANGE ALERTS' : 'ALL BULLETINS'}
              </button>
            ))}
          </div>

          {/* Alerts List */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="space-y-4"
          >
            {filtered.map((alt) => (
              <motion.div
                key={alt.id}
                variants={fadeIn}
                className={`rounded-2xl border p-5 shadow-sm bg-white ${
                  alt.level === 'RED'
                    ? 'border-rose-200 hover:border-rose-300'
                    : 'border-amber-200 hover:border-amber-300'
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`text-xs font-black font-mono px-2.5 py-1 rounded-lg ${
                        alt.level === 'RED'
                          ? 'bg-rose-600 text-white'
                          : 'bg-amber-500 text-slate-950 font-bold'
                      }`}
                    >
                      {alt.level} ALERT
                    </span>
                    <span className="font-mono text-xs text-slate-400">
                      {alt.id}
                    </span>
                    <span className="text-xs text-slate-500 font-medium">
                      • {alt.agency}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
                    <Clock className="w-3.5 h-3.5" />
                    <span>Issued {alt.issuedAt}</span>
                    <span>(Valid until: {alt.validUntil})</span>
                  </div>
                </div>

                <h2 className="text-base font-bold text-slate-900 mb-2">
                  {alt.title}
                </h2>

                <p className="text-sm text-slate-600 mb-3 leading-relaxed">
                  {alt.description}
                </p>

                {/* Zones Affected */}
                <div className="flex flex-wrap items-center gap-1.5 mb-3">
                  <span className="text-xs font-semibold text-slate-700">
                    Impacted Districts:
                  </span>
                  {alt.zones.map((zone) => (
                    <span
                      key={zone}
                      className="text-xs font-mono bg-slate-100 text-slate-700 px-2 py-0.5 rounded-md border border-slate-200"
                    >
                      {zone}
                    </span>
                  ))}
                </div>

                {/* Mandatory Actions */}
                <div className="bg-rose-50/70 border border-rose-100 rounded-xl p-3 text-xs text-rose-900 flex items-start gap-2">
                  <AlertOctagon className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
                  <div>
                    <span className="font-bold">Required Operational Directive: </span>
                    {alt.actionRequired}
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </main>
      </div>
    </div>
  );
}
