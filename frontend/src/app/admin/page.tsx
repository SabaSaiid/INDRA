'use client';

/**
 * Admin console.
 *
 * Every number here is read from the backend: dependency health from
 * /healthz, accounts from /api/profile/operators, and the audit trail from the
 * hash-chained ledger (/api/audit/recent).
 *
 * It used to be entirely static: "99.98% Uptime · 4 Nodes Active · Zero
 * Errors", a "BigQuery Data Warehouse 14ms · GCP asia-south1" INDRA does not
 * use, "Zero Breaches · MFA" for a platform with no MFA, "CLEARANCE: LEVEL 5",
 * a badge reading ALL SYSTEMS OPERATIONAL whatever the system's state, and an
 * audit trail of invented entries — among them a CAP broadcast "pushed to Puri
 * district civil authorities" by an alert engine that does not exist.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  Server,
  Lock,
  Users,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Terminal,
  RefreshCw,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import {
  fetchHealth,
  fetchOperators,
  fetchAuditLedger,
  type HealthReport,
  type OperatorAccount,
  type AuditLedger,
} from '@/lib/api';

// What each /healthz check is, in words an operator can act on.
const CHECK_LABEL: Record<string, { name: string; what: string }> = {
  database: { name: 'PostgreSQL + PostGIS', what: 'Reports, events, audit ledger' },
  streaming_bus: { name: 'Redpanda (Kafka)', what: 'Report stream to the pipeline' },
  redis: { name: 'Redis', what: 'Weather cache, broadcast dedup' },
  weather_api: { name: 'Open-Meteo', what: 'Live rainfall for the weather factor' },
};

const STATUS_STYLE: Record<string, { text: string; dot: string; label: string }> = {
  healthy: { text: 'text-emerald-300', dot: 'bg-emerald-400', label: 'ALL CHECKS UP' },
  degraded: { text: 'text-amber-300', dot: 'bg-amber-400', label: 'DEGRADED — a non-critical check is down' },
  unhealthy: { text: 'text-rose-300', dot: 'bg-rose-500', label: 'UNHEALTHY — a critical check is down' },
};

function when(ts: string | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export default function AdminPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [health, setHealth] = useState<HealthReport | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [operators, setOperators] = useState<OperatorAccount[] | null>(null);
  const [ledger, setLedger] = useState<AuditLedger | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [h, o, l] = await Promise.allSettled([fetchHealth(), fetchOperators(), fetchAuditLedger(15)]);
    if (h.status === 'fulfilled') {
      setHealth(h.value);
      setHealthError(null);
    } else {
      setHealth(null);
      setHealthError(h.reason instanceof Error ? h.reason.message : 'Backend unreachable');
    }
    setOperators(o.status === 'fulfilled' ? o.value : null);
    if (l.status === 'fulfilled') {
      setLedger(l.value);
      setLedgerError(null);
    } else {
      setLedger(null);
      setLedgerError(l.reason instanceof Error ? l.reason.message : 'Ledger unavailable');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const overall = health ? STATUS_STYLE[health.status] ?? STATUS_STYLE.unhealthy : null;

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
          sidebarCollapsed ? 'md:ml-[68px]' : 'md:ml-[272px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-slate-900 text-white p-5 rounded-2xl border border-slate-800 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Shield className="w-5 h-5 text-emerald-400" />
                <h1 className="text-xl font-bold font-mono">ADMIN — SYSTEM &amp; GOVERNANCE</h1>
              </div>
              <p className="text-xs text-slate-400">
                Live dependency checks, operator accounts and the hash-chained audit ledger.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div
                data-testid="overall-health"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-mono ${
                  overall ? overall.text : 'text-rose-300'
                }`}
              >
                <span className={`w-2 h-2 rounded-full ${overall ? overall.dot : 'bg-rose-500'}`} />
                {loading && !health ? 'CHECKING…' : overall ? overall.label : 'BACKEND UNREACHABLE'}
              </div>
              <button
                onClick={load}
                disabled={loading}
                className="p-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Re-run checks"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {healthError && (
            <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-100 text-xs font-semibold text-rose-700">
              {healthError}
            </div>
          )}

          {/* Dependency checks, one card per /healthz check */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            {Object.entries(health?.checks ?? {}).map(([key, check]) => {
              const label = CHECK_LABEL[key] ?? { name: key, what: '' };
              const up = check.status === 'up';
              return (
                <motion.div
                  key={key}
                  variants={fadeIn}
                  className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm"
                >
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                    <span>{label.name}</span>
                    {up ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-rose-500" />
                    )}
                  </div>
                  <div className={`text-lg font-bold font-mono ${up ? 'text-slate-900' : 'text-rose-600'}`}>
                    {up ? 'Up' : 'Down'}
                    {check.latency_ms != null && (
                      <span className="text-xs font-medium text-slate-400"> · {check.latency_ms} ms</span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">
                    {label.what}
                    {check.critical ? ' · critical' : ' · non-critical'}
                  </p>
                </motion.div>
              );
            })}
          </motion.div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Accounts */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
              <h2 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
                <Users className="w-4 h-4 text-indigo-500" />
                Operator accounts
              </h2>
              {operators === null ? (
                <p className="text-xs text-slate-500">Accounts could not be loaded.</p>
              ) : operators.length === 0 ? (
                <p className="text-xs text-slate-500">No operator accounts exist.</p>
              ) : (
                <ul className="space-y-2 text-xs">
                  {operators.map((op) => (
                    <li key={op.operator_id} className="flex items-center justify-between">
                      <span className="text-slate-800 font-medium">{op.full_name}</span>
                      <span className="font-mono text-[11px] text-slate-500">
                        {op.role} · {op.duty_status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Access control, stated as it is */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm lg:col-span-2">
              <h2 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
                <Lock className="w-4 h-4 text-amber-500" />
                Access control
              </h2>
              <ul className="space-y-1.5 text-xs text-slate-600 list-disc pl-4">
                <li>Bearer JWT (HS256, 8-hour expiry) from POST /api/auth/token.</li>
                <li>
                  Every write is role-checked: reviewing an event, dispatching a team and filing an
                  official report need a Commander or Admin; editing a profile needs its owner.
                </li>
                <li>Reading provenance and this ledger needs an Analyst, Commander or Admin.</li>
                <li>Dashboard reads are open. There is no MFA.</li>
                <li>
                  Demo accounts only; their passwords are part of the dashboard&apos;s persona
                  switcher, so the gate demonstrates roles and attribution, not secrecy.
                </li>
              </ul>
            </div>
          </div>

          {/* Audit ledger */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
              <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Terminal className="w-4 h-4 text-slate-700" />
                Audit ledger (SHA-256 hash chain)
              </h2>
              {ledger && (
                <span
                  data-testid="chain-status"
                  className={`text-[11px] font-mono px-2 py-0.5 rounded-md border ${
                    ledger.chain.valid
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : 'bg-rose-50 text-rose-700 border-rose-200'
                  }`}
                >
                  {ledger.chain.valid
                    ? `Chain valid · ${ledger.chain.checked} rows verified`
                    : `Chain BROKEN at seq ${ledger.chain.broken_at_seq}`}
                </span>
              )}
            </div>

            {ledgerError ? (
              <p className="text-xs text-slate-500">{ledgerError}</p>
            ) : !ledger ? (
              <p className="text-xs text-slate-400">Loading the ledger…</p>
            ) : ledger.rows.length === 0 ? (
              <p className="text-xs text-slate-500">
                The ledger is empty: no event has changed status and no operator has reviewed one yet.
              </p>
            ) : (
              <div className="space-y-2 font-mono text-xs text-slate-600 bg-slate-50 p-4 rounded-xl border border-slate-200">
                {ledger.rows.map((row) => (
                  <div key={row.seq} className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-400">[{when(row.logged_at)} IST]</span>
                    <span className="text-slate-400">#{row.seq}</span>
                    <span className="text-blue-600 font-semibold">{row.action_taken}</span>
                    <span>{row.operator_id}</span>
                    {row.reason && <span className="text-slate-500">— {row.reason}</span>}
                    <span className="text-slate-300">{row.sha256_hash.slice(0, 12)}…</span>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-3 text-[11px] text-slate-400 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5" />
              Edits and insertions anywhere in the chain are detected. Deleting the newest rows is
              not, without an external anchor for the head hash (BUG-010).
            </p>
          </div>

          <p className="text-[11px] text-slate-400 flex items-center gap-1.5">
            <Server className="w-3.5 h-3.5" />
            One backend process, PostgreSQL, Redis and Redpanda on a single host.
          </p>
        </main>
      </div>
    </div>
  );
}
