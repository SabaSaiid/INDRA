'use client';

import React from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  Server,
  Lock,
  Users,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Radio,
  Sliders,
  Terminal,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';

export default function AdminPage() {
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[260px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Shield className="w-5 h-5 text-emerald-400" />
                <h1 className="text-xl font-bold font-mono">
                  ADMIN COMMAND &amp; GOVERNANCE CONSOLE
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  CLEARANCE: LEVEL 5 (COMMANDER)
                </span>
              </div>
              <p className="text-xs text-slate-400">
                System telemetry node health, RBAC security roles, audit trail logs, and high-availability failover.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-mono text-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                ALL SYSTEMS OPERATIONAL
              </div>
            </div>
          </div>

          {/* Node Health Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>FastAPI Microservice Cluster</span>
                <Server className="w-4 h-4 text-emerald-500" />
              </div>
              <div className="text-lg font-bold text-slate-900 font-mono">99.98% Uptime</div>
              <p className="text-[11px] text-emerald-600 font-medium mt-1">4 Nodes Active • Zero Errors</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>BigQuery Data Warehouse</span>
                <Activity className="w-4 h-4 text-blue-500" />
              </div>
              <div className="text-lg font-bold text-slate-900 font-mono">14ms Latency</div>
              <p className="text-[11px] text-blue-600 font-medium mt-1">GCP asia-south1 (Mumbai)</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Active Operator Sessions</span>
                <Users className="w-4 h-4 text-indigo-500" />
              </div>
              <div className="text-lg font-bold text-slate-900 font-mono">12 Commanders</div>
              <p className="text-[11px] text-indigo-600 font-medium mt-1">NDRF, SDRF &amp; IMD Leads</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                <span>Security Clearance Audit</span>
                <Lock className="w-4 h-4 text-amber-500" />
              </div>
              <div className="text-lg font-bold text-slate-900 font-mono">Zero Breaches</div>
              <p className="text-[11px] text-amber-600 font-medium mt-1">MFA &amp; Signed WebTokens</p>
            </div>
          </div>

          {/* Audit Trail Preview */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
              <Terminal className="w-4 h-4 text-slate-700" />
              Recent Security Audit &amp; Event Dispatch Trail
            </h2>
            <div className="space-y-2 font-mono text-xs text-slate-600 bg-slate-50 p-4 rounded-xl border border-slate-200">
              <div className="flex items-center gap-2">
                <span className="text-slate-400">[2026-09-14 20:45:12 UTC]</span>
                <span className="text-blue-600 font-semibold">AUTH_SUCCESS</span>
                <span>Commander R.K. Verma authenticated via PKI smartcard</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-400">[2026-09-14 21:02:44 UTC]</span>
                <span className="text-emerald-600 font-semibold">DISPATCH_ORDER</span>
                <span>Assigned NDRF 9th Bn to Patna Riverfront Flash Flood</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-400">[2026-09-14 22:15:00 UTC]</span>
                <span className="text-purple-600 font-semibold">RADAR_SWEEP</span>
                <span>Ingested 34 Doppler GeoTIFF layers into BigQuery GIS partition</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-400">[2026-09-14 22:38:19 UTC]</span>
                <span className="text-amber-600 font-semibold">BROADCAST_SENT</span>
                <span>Common Alerting Protocol (CAP) pushed to Puri district civil authorities</span>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
