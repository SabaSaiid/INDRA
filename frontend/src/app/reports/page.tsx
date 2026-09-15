'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  FileText,
  CheckCircle2,
  Clock,
  MapPin,
  Camera,
  ShieldCheck,
  Search,
  Filter,
  Eye,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';

const mockReports = [
  {
    id: 'REP-9921',
    category: 'WATERLOGGING',
    location: 'Gandhi Maidan Sector 4, Patna',
    submitter: 'Citizen Mobile App (Verified Aadhaar)',
    depth: '0.85 meters',
    confidence: 94.2,
    timestamp: '14 mins ago',
    status: 'VERIFIED_BY_RADAR',
    description: 'Road fully submerged, 2 public buses stranded near collectorate gate. Water rapidly rising.',
  },
  {
    id: 'REP-9920',
    category: 'CYCLONE_DAMAGE',
    location: 'Marine Drive Road, Puri',
    submitter: 'NDRF Scout Unit 2',
    depth: 'N/A (Wind: 110 km/h)',
    confidence: 99.1,
    timestamp: '32 mins ago',
    status: 'VERIFIED_GROUND_OBS',
    description: 'Uprooted banyan trees blocking national highway 316. Power transmission lines severed.',
  },
  {
    id: 'REP-9919',
    category: 'FLASH_FLOOD',
    location: 'Meppadi Village, Wayanad',
    submitter: 'Automated Hydro-Sensor #412',
    depth: '1.40 meters',
    confidence: 98.7,
    timestamp: '50 mins ago',
    status: 'TELEMETRY_CONFIRMED',
    description: 'Stream discharge crossed 95th percentile baseline. Sediment turbidity high.',
  },
  {
    id: 'REP-9918',
    category: 'INUNDATION',
    location: 'Yamuna Bazar, East Delhi',
    submitter: 'Civil Defense Volunteer Patrol',
    depth: '0.45 meters',
    confidence: 91.5,
    timestamp: '1h 15m ago',
    status: 'VERIFIED_BY_RADAR',
    description: 'River water entered low-lying ghat steps. Ghat shops evacuated by district police.',
  },
];

export default function ReportsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [search, setSearch] = useState('');

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
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <FileText className="w-5 h-5 text-blue-400" />
                <h1 className="text-xl font-bold font-mono">
                  FIELD REPORTS &amp; GROUND TRUTH REPOSITORY
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  1,248 TOTAL REPORTS
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Multi-channel verification pipeline combining citizen crowdsourced observations, IoT hydro-sensors, and satellite telemetry.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-emerald-950/60 border border-emerald-500/30 px-3 py-1.5 rounded-xl text-xs font-mono text-emerald-400">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span>94.8% AI CROSS-VERIFICATION ACCURACY</span>
              </div>
            </div>
          </div>

          {/* Search bar */}
          <div className="relative max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search reports by location, submitter, or ID..."
              className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 shadow-sm"
            />
          </div>

          {/* Reports Table/Cards */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            {mockReports.map((rep) => (
              <motion.div
                key={rep.id}
                variants={fadeIn}
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-200">
                      {rep.id}
                    </span>
                    <span className="text-xs font-mono text-slate-400">
                      {rep.category}
                    </span>
                  </div>
                  <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200 font-semibold">
                    <ShieldCheck className="w-3.5 h-3.5" />
                    {rep.confidence}% Confident
                  </span>
                </div>

                <div className="space-y-2 mb-4">
                  <div className="flex items-center gap-1.5 text-xs text-slate-700 font-medium">
                    <MapPin className="w-4 h-4 text-slate-400 flex-shrink-0" />
                    <span>{rep.location}</span>
                  </div>
                  <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded-xl border border-slate-100 leading-relaxed">
                    &ldquo;{rep.description}&rdquo;
                  </p>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                  <span className="text-[11px]">By: {rep.submitter}</span>
                  <div className="flex items-center gap-1 font-mono text-[11px]">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    <span>{rep.timestamp}</span>
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
