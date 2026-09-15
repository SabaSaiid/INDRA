'use client';

import React from 'react';
import { motion } from 'framer-motion';
import {
  Database,
  Layers,
  HardDrive,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  Download,
  Search,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';

const mockDatasets = [
  {
    id: 'DS-IMD-DWR-MOSAIC',
    title: 'IMD National Doppler Weather Radar Composite Mosaic',
    format: 'Cloud-Optimized GeoTIFF (COG)',
    updateFrequency: 'Every 10 Minutes',
    size: '184 GB / Day',
    agency: 'India Meteorological Department (IMD)',
    coverage: 'Pan-India 34 Radar Network',
    status: 'STREAMING_HEALTHY',
  },
  {
    id: 'DS-ISRO-INSAT3D-IR',
    title: 'INSAT-3DR Thermal Infrared & Water Vapor Channels',
    format: 'HDF5 / NetCDF-4',
    updateFrequency: 'Every 15 Minutes',
    size: '92 GB / Day',
    agency: 'ISRO / Space Applications Centre',
    coverage: 'Indian Ocean & Subcontinent Basin',
    status: 'STREAMING_HEALTHY',
  },
  {
    id: 'DS-CWC-HYDRO-BASIN',
    title: 'CWC Real-time River Gauge & Discharge Telemetry',
    format: 'GeoJSON / REST Stream',
    updateFrequency: 'Hourly',
    size: '1.2 GB / Day',
    agency: 'Central Water Commission',
    coverage: '1,540 Monitoring Stations',
    status: 'STREAMING_HEALTHY',
  },
  {
    id: 'DS-INDRA-AI-CORRELATIONS',
    title: 'INDRA AI Multi-Source Incident Correlation Lakehouse',
    format: 'BigQuery Partitioned Tables',
    updateFrequency: 'Sub-minute Streaming',
    size: '420 GB Total',
    agency: 'INDRA Big Data Core',
    coverage: 'District-level Geospatial Bounds',
    status: 'ACTIVE_QUERYABLE',
  },
];

export default function DatasetsPage() {
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
                <Database className="w-5 h-5 text-indigo-400" />
                <h1 className="text-xl font-bold font-mono">
                  GEOSPATIAL FEEDS &amp; LAKEHOUSE DATASETS
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  4 LIVE CATALOGS
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Federated Open Data Architecture ingesting satellite, radar, and river basin raster telemetry into BigQuery.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-mono text-indigo-300">
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                <span>SYNC PIPELINE: 100% OPERATIONAL</span>
              </div>
            </div>
          </div>

          {/* Datasets Grid */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            {mockDatasets.map((ds) => (
              <motion.div
                key={ds.id}
                variants={fadeIn}
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div>
                    <span className="font-mono text-xs text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-200 font-semibold">
                      {ds.id}
                    </span>
                    <h2 className="text-base font-bold text-slate-900 mt-2">
                      {ds.title}
                    </h2>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold whitespace-nowrap">
                    ● {ds.status}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 bg-slate-50 p-3 rounded-xl mb-4">
                  <div>
                    <span className="text-slate-400 block text-[10px]">Source Agency</span>
                    <span className="font-medium text-slate-800">{ds.agency}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Data Format</span>
                    <span className="font-medium text-slate-800">{ds.format}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Cadence</span>
                    <span className="font-medium text-slate-800">{ds.updateFrequency}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Data Volume</span>
                    <span className="font-medium text-slate-800">{ds.size}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                  <span className="truncate max-w-[240px]">Coverage: {ds.coverage}</span>
                  <a
                    href="/live-map"
                    className="text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
                  >
                    Inspect Layer <ExternalLink className="w-3 h-3" />
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
