'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarClock,
  AlertTriangle,
  MapPin,
  Clock,
  Filter,
  Search,
  ExternalLink,
  ShieldAlert,
  CheckCircle2,
  Radio,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';

const mockEventsList = [
  {
    id: 'EV-2026-0914-01',
    title: 'Severe Urban Flash Flood — Patna Riverfront Corridor',
    type: 'URBAN_FLOOD',
    severity: 'CRITICAL',
    location: 'Patna, Bihar',
    coordinates: '25.61° N, 85.14° E',
    time: '8 mins ago',
    unitsDeployed: 'NDRF 9th Bn (Hawk-Lead)',
    status: 'ACTIVE_RESPONSE',
    reportsCount: 42,
  },
  {
    id: 'EV-2026-0914-02',
    title: 'Deep Depression & High-Velocity Gale Warnings',
    type: 'CYCLONE',
    severity: 'CRITICAL',
    location: 'Puri & Paradip Coast, Odisha',
    coordinates: '19.81° N, 85.83° E',
    time: '24 mins ago',
    unitsDeployed: 'ODRAF Taskforce Delta',
    status: 'EVACUATION_ORDERED',
    reportsCount: 78,
  },
  {
    id: 'EV-2026-0914-03',
    title: 'Debris Flow & Slope Instability Warning',
    type: 'LANDSLIDE',
    severity: 'HIGH',
    location: 'Wayanad Ghat Corridor, Kerala',
    coordinates: '11.68° N, 76.13° E',
    time: '1h 12m ago',
    unitsDeployed: 'SDRF Kerala Unit 4',
    status: 'MONITORING',
    reportsCount: 19,
  },
  {
    id: 'EV-2026-0914-04',
    title: 'River Swell Inundation — Yamuna Lowland Sector',
    type: 'RIVER_FLOOD',
    severity: 'MODERATE',
    location: 'East Delhi, NCR',
    coordinates: '28.61° N, 77.23° E',
    time: '2h 45m ago',
    unitsDeployed: 'Civil Defense Delhi South',
    status: 'BARRICADED',
    reportsCount: 31,
  },
];

export default function EventsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [search, setSearch] = useState('');

  const filtered = mockEventsList.filter((ev) => {
    if (filterSeverity !== 'ALL' && ev.severity !== filterSeverity) return false;
    if (
      search &&
      !ev.title.toLowerCase().includes(search.toLowerCase()) &&
      !ev.location.toLowerCase().includes(search.toLowerCase())
    ) {
      return false;
    }
    return true;
  });

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
          {/* Header Banner */}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <CalendarClock className="w-5 h-5 text-amber-400" />
                <h1 className="text-xl font-bold font-mono">
                  INCIDENT EVENTS &amp; EMERGENCY LOG
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  18 ACTIVE
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Live multi-source meteorological incident tracking and disaster response coordination.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700 text-xs">
                <Radio className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
                <span className="text-slate-300 font-mono">IMD TELEMETRY SYNCED</span>
              </div>
            </div>
          </div>

          {/* Filters & Search */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="relative w-full sm:w-80">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter by city, river, or state..."
                className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 shadow-sm"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto">
              {['ALL', 'CRITICAL', 'HIGH', 'MODERATE'].map((sev) => (
                <button
                  key={sev}
                  onClick={() => setFilterSeverity(sev)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                    filterSeverity === sev
                      ? 'bg-slate-900 text-white shadow-sm'
                      : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>

          {/* Incidents Grid */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            {filtered.map((ev) => (
              <motion.div
                key={ev.id}
                variants={fadeIn}
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-[11px] text-slate-400">
                        {ev.id}
                      </span>
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                          ev.severity === 'CRITICAL'
                            ? 'bg-rose-100 text-rose-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        {ev.severity}
                      </span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-50 text-blue-700">
                        {ev.status}
                      </span>
                    </div>
                    <h3 className="font-semibold text-slate-900 text-base">
                      {ev.title}
                    </h3>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 mb-4 bg-slate-50 p-3 rounded-xl">
                  <div className="flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5 text-slate-400" />
                    <span>{ev.location}</span>
                  </div>
                  <div className="flex items-center gap-1.5 font-mono text-[11px]">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    <span>{ev.time}</span>
                  </div>
                  <div className="flex items-center gap-1.5 col-span-2">
                    <ShieldAlert className="w-3.5 h-3.5 text-blue-600" />
                    <span className="font-medium text-slate-800">
                      {ev.unitsDeployed}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                  <span>{ev.reportsCount} citizen &amp; sensor reports verified</span>
                  <a
                    href="/live-map"
                    className="text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
                  >
                    View on 3D Globe <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </main>
      </div>
    </div>
  );
}
