'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bell,
  AlertOctagon,
  AlertTriangle,
  Info,
  ShieldAlert,
  Radio,
  MapPin,
  Clock,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Zap,
  TrendingUp,
  Shield,
  Activity,
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import {
  fetchEngineAlerts,
  fetchAlertEngineStats,
  acknowledgeEngineAlert,
  resolveEngineAlert,
  checkAlertEngineHealth,
  type EngineAlert,
  type AlertEngineStats,
} from '@/lib/api';

// ── Severity / Status Helpers ────────────────────────────────────────────────

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'bg-rose-600 text-white',
  HIGH:     'bg-amber-500 text-white',
  MODERATE: 'bg-yellow-400 text-slate-900',
  ADVISORY: 'bg-sky-500 text-white',
};

const SEVERITY_BORDER: Record<string, string> = {
  CRITICAL: 'border-rose-400/60 hover:border-rose-400',
  HIGH:     'border-amber-400/50 hover:border-amber-400',
  MODERATE: 'border-yellow-400/40 hover:border-yellow-400',
  ADVISORY: 'border-sky-400/40 hover:border-sky-400',
};

const STATUS_COLOR: Record<string, string> = {
  ACTIVE:       'text-emerald-400',
  ESCALATED:    'text-rose-400',
  ACKNOWLEDGED: 'text-amber-400',
  RESOLVED:     'text-slate-500',
  EXPIRED:      'text-slate-600',
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  ACTIVE:       <Activity className="w-3.5 h-3.5" />,
  ESCALATED:    <TrendingUp className="w-3.5 h-3.5" />,
  ACKNOWLEDGED: <CheckCircle2 className="w-3.5 h-3.5" />,
  RESOLVED:     <Shield className="w-3.5 h-3.5" />,
  EXPIRED:      <XCircle className="w-3.5 h-3.5" />,
};

const MODE_BADGE: Record<string, { label: string; cls: string }> = {
  live:      { label: 'LIVE', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
  websocket: { label: 'LIVE', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
  api:       { label: 'DEMO', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
  demo:      { label: 'DEMO', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
};

// ── Alert Card ────────────────────────────────────────────────────────────────

function AlertCard({
  alert,
  onAcknowledge,
  onResolve,
}: {
  alert: EngineAlert;
  onAcknowledge: (id: string) => Promise<void>;
  onResolve: (id: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const modeBadge = MODE_BADGE[alert.mode] ?? MODE_BADGE['demo'];

  const confidencePct = Math.round(alert.confidence * 100);

  const handleAck = async () => {
    setActing(true);
    await onAcknowledge(alert.alert_id);
    setActing(false);
  };
  const handleResolve = async () => {
    setActing(true);
    await onResolve(alert.alert_id);
    setActing(false);
  };

  return (
    <motion.div
      variants={fadeIn}
      layout
      className={`rounded-2xl border bg-slate-900/80 backdrop-blur-sm shadow-md transition-all duration-200 ${
        SEVERITY_BORDER[alert.severity] ?? 'border-slate-700 hover:border-slate-600'
      }`}
    >
      {/* Card Header */}
      <div className="p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
          {/* Left column */}
          <div className="flex items-start gap-3 flex-1 min-w-0">
            {/* Severity badge */}
            <span
              className={`shrink-0 text-[10px] font-black font-mono px-2.5 py-1 rounded-lg tracking-widest ${
                SEVERITY_COLOR[alert.severity] ?? 'bg-slate-600 text-white'
              }`}
            >
              {alert.severity}
            </span>

            <div className="min-w-0">
              <p className="text-sm font-bold text-white leading-tight mb-1 line-clamp-2">
                {alert.title}
              </p>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                <span className="font-mono text-slate-500">{alert.alert_id}</span>
                <span>·</span>
                <span className="font-mono text-slate-500">{alert.event_code}</span>
                {alert.affected_area && (
                  <>
                    <span>·</span>
                    <span className="flex items-center gap-1">
                      <MapPin className="w-3 h-3" />
                      {alert.affected_area}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Right column */}
          <div className="flex items-center gap-2 shrink-0">
            {/* Mode */}
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${modeBadge.cls}`}
            >
              {modeBadge.label}
            </span>
            {/* Status */}
            <span
              className={`flex items-center gap-1 text-[10px] font-bold font-mono ${
                STATUS_COLOR[alert.status] ?? 'text-slate-400'
              }`}
            >
              {STATUS_ICON[alert.status]}
              {alert.status}
            </span>
          </div>
        </div>

        {/* Message */}
        <p className="mt-3 text-xs text-slate-400 leading-relaxed line-clamp-2">
          {alert.message}
        </p>

        {/* Confidence bar */}
        <div className="mt-3 flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-mono w-24 shrink-0">
            Confidence {confidencePct}%
          </span>
          <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                confidencePct >= 90
                  ? 'bg-emerald-500'
                  : confidencePct >= 70
                  ? 'bg-amber-500'
                  : 'bg-rose-500'
              }`}
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-[10px] text-slate-500 shrink-0">
            {alert.source_count} sources
          </span>
        </div>

        {/* Timestamps */}
        <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-500 font-mono">
          {alert.triggered_at && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              Triggered {new Date(alert.triggered_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
            </span>
          )}
          {alert.escalation_level !== 'NONE' && (
            <span className="flex items-center gap-1 text-rose-400">
              <TrendingUp className="w-3 h-3" />
              {alert.escalation_level}
            </span>
          )}
        </div>
      </div>

      {/* Expandable Detail */}
      <div
        className="border-t border-slate-800/60 px-5 py-2.5 flex items-center justify-between cursor-pointer hover:bg-slate-800/30 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="text-[11px] text-slate-500">Evidence & Actions</span>
        {expanded ? (
          <ChevronUp className="w-3.5 h-3.5 text-slate-500" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
        )}
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="p-5 pt-0 space-y-4 border-t border-slate-800/60">
              {/* Evidence factors */}
              {Array.isArray((alert.evidence as any)?.factors) && (
                <div>
                  <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-2">
                    Verification Factors
                  </p>
                  <div className="space-y-1">
                    {((alert.evidence as any).factors as any[]).map(
                      (f: any, i: number) => (
                        <div key={i} className="flex items-center gap-2">
                          <span className="text-[10px] text-slate-400 w-40 truncate">{f.factor}</span>
                          <div className="flex-1 h-1 bg-slate-800 rounded-full">
                            <div
                              className="h-full bg-indigo-500 rounded-full"
                              style={{ width: `${Math.round((f.score ?? 0) * 100)}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-400 font-mono w-8 text-right">
                            {Math.round((f.score ?? 0) * 100)}%
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}

              {/* Location */}
              {alert.lat && alert.lng && (
                <div className="flex items-center gap-2 text-[11px] text-slate-400">
                  <MapPin className="w-3.5 h-3.5 text-slate-500" />
                  <span>
                    {alert.lat.toFixed(4)}°N, {alert.lng.toFixed(4)}°E
                    {alert.impact_radius_km && ` — Radius ${alert.impact_radius_km.toFixed(1)} km`}
                  </span>
                </div>
              )}

              {/* Action buttons */}
              {(alert.status === 'ACTIVE' || alert.status === 'ESCALATED') && (
                <div className="flex items-center gap-2 pt-1">
                  <button
                    disabled={acting}
                    onClick={handleAck}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 transition-colors disabled:opacity-50"
                  >
                    <CheckCircle2 className="inline w-3.5 h-3.5 mr-1 -mt-0.5" />
                    Acknowledge
                  </button>
                  <button
                    disabled={acting}
                    onClick={handleResolve}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                  >
                    <Shield className="inline w-3.5 h-3.5 mr-1 -mt-0.5" />
                    Resolve
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const [alerts, setAlerts] = useState<EngineAlert[]>([]);
  const [stats, setStats] = useState<AlertEngineStats | null>(null);
  const [engineOnline, setEngineOnline] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [selectedSeverity, setSelectedSeverity] = useState('ALL');
  const [selectedStatus, setSelectedStatus] = useState('ALL');
  const wsRef = useRef<WebSocket | null>(null);

  const ALERT_ENGINE_WS =
    process.env.NEXT_PUBLIC_ALERT_ENGINE_WS_URL ?? 'ws://localhost:8001/api/ws/alerts';

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    const [alertData, statsData, health] = await Promise.all([
      fetchEngineAlerts(),
      fetchAlertEngineStats(),
      checkAlertEngineHealth(),
    ]);
    setAlerts(alertData);
    setStats(statsData);
    setEngineOnline(health);
    setLastRefreshed(new Date());
    setLoading(false);
  }, []);

  // Initial load
  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  // Real-time WebSocket subscription
  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      try {
        ws = new WebSocket(ALERT_ENGINE_WS);
        wsRef.current = ws;

        ws.onopen = () => setEngineOnline(true);

        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'INITIAL_ALERTS' && Array.isArray(msg.alerts)) {
              setAlerts(msg.alerts);
            } else if (msg.type === 'ALERT_UPDATE' && msg.alert) {
              setAlerts((prev) => {
                const idx = prev.findIndex((a) => a.alert_id === msg.alert.alert_id);
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = msg.alert;
                  return next;
                }
                return [msg.alert, ...prev];
              });
              setLastRefreshed(new Date());
            }
          } catch {}
        };

        ws.onerror = () => setEngineOnline(false);
        ws.onclose = () => {
          setEngineOnline(false);
          // Reconnect after 10 seconds
          reconnectTimer = setTimeout(connect, 10000);
        };
      } catch {
        reconnectTimer = setTimeout(connect, 10000);
      }
    };

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [ALERT_ENGINE_WS]);

  const handleAcknowledge = async (alertId: string) => {
    await acknowledgeEngineAlert(alertId, 'operator');
    await loadAlerts();
  };

  const handleResolve = async (alertId: string) => {
    await resolveEngineAlert(alertId, 'Manual resolution by operator', 'operator');
    await loadAlerts();
  };

  const filtered = alerts.filter((a) => {
    const sevOk = selectedSeverity === 'ALL' || a.severity === selectedSeverity;
    const stOk = selectedStatus === 'ALL' || a.status === selectedStatus;
    return sevOk && stOk;
  });

  const activeCount = alerts.filter((a) =>
    ['ACTIVE', 'ESCALATED', 'ACKNOWLEDGED'].includes(a.status)
  ).length;

  return (
    <div className="min-h-screen bg-slate-950">
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
          <div className="bg-gradient-to-r from-rose-950 via-slate-900 to-slate-950 text-white p-5 rounded-2xl border border-rose-900/40 shadow-xl">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2.5 mb-1.5">
                  <ShieldAlert className="w-5 h-5 text-rose-400 animate-pulse" />
                  <h1 className="text-xl font-bold font-mono tracking-wide">
                    ALERT ENGINE — LIVE MONITOR
                  </h1>
                  {activeCount > 0 && (
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/30 text-rose-300 border border-rose-500/50 animate-pulse">
                      {activeCount} ACTIVE
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400">
                  Real alerts derived from INDRA verified events. No mock data.
                  {lastRefreshed && (
                    <span className="ml-2 text-slate-500">
                      Last updated: {lastRefreshed.toLocaleTimeString('en-IN')}
                    </span>
                  )}
                </p>
              </div>

              <div className="flex items-center gap-2">
                {/* Engine status */}
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-mono border ${
                    engineOnline === null
                      ? 'bg-slate-800 border-slate-700 text-slate-400'
                      : engineOnline
                      ? 'bg-emerald-900/40 border-emerald-700/50 text-emerald-300'
                      : 'bg-rose-900/40 border-rose-700/50 text-rose-300'
                  }`}
                >
                  {engineOnline ? (
                    <Wifi className="w-3.5 h-3.5" />
                  ) : (
                    <WifiOff className="w-3.5 h-3.5" />
                  )}
                  {engineOnline === null
                    ? 'CHECKING...'
                    : engineOnline
                    ? 'ENGINE ONLINE'
                    : 'ENGINE OFFLINE'}
                </div>

                <button
                  onClick={loadAlerts}
                  disabled={loading}
                  className="p-2 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {/* Stats row */}
            {stats && (
              <div className="mt-4 flex flex-wrap gap-3">
                {[
                  { label: 'Total Generated', value: stats.total, color: 'text-slate-300' },
                  { label: 'Currently Active', value: stats.active, color: 'text-emerald-400' },
                  {
                    label: 'Filtered (View)',
                    value: filtered.length,
                    color: 'text-indigo-400',
                  },
                ].map((s) => (
                  <div
                    key={s.label}
                    className="bg-slate-900/60 border border-slate-700/50 rounded-xl px-3 py-2"
                  >
                    <p className={`text-lg font-black font-mono ${s.color}`}>{s.value}</p>
                    <p className="text-[10px] text-slate-500">{s.label}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Engine offline banner */}
          {engineOnline === false && (
            <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-amber-600/40 bg-amber-900/20 text-amber-300 text-sm">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>
                <strong>Alert Engine is offline.</strong> Start it with{' '}
                <code className="font-mono text-xs bg-slate-800 px-1.5 py-0.5 rounded">
                  python -m alert_engine.main
                </code>{' '}
                from the INDRA root directory. No alerts will be shown until it is running.
              </span>
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5">
              {['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'ADVISORY'].map((s) => (
                <button
                  key={s}
                  onClick={() => setSelectedSeverity(s)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    selectedSeverity === s
                      ? 'bg-slate-700 text-white shadow-sm'
                      : 'bg-slate-900 text-slate-500 border border-slate-800 hover:bg-slate-800 hover:text-slate-300'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>

            <div className="w-px h-5 bg-slate-700" />

            <div className="flex items-center gap-1.5">
              {['ALL', 'ACTIVE', 'ESCALATED', 'ACKNOWLEDGED', 'RESOLVED'].map((s) => (
                <button
                  key={s}
                  onClick={() => setSelectedStatus(s)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    selectedStatus === s
                      ? 'bg-slate-700 text-white shadow-sm'
                      : 'bg-slate-900 text-slate-500 border border-slate-800 hover:bg-slate-800 hover:text-slate-300'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Empty state */}
          {!loading && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center space-y-3">
              {engineOnline ? (
                <>
                  <Bell className="w-10 h-10 text-slate-700" />
                  <p className="text-slate-500 text-sm">No alerts match the current filters.</p>
                  <p className="text-slate-600 text-xs">
                    Events must meet rule thresholds to generate alerts.
                  </p>
                </>
              ) : (
                <>
                  <WifiOff className="w-10 h-10 text-amber-800" />
                  <p className="text-amber-600 text-sm font-semibold">Alert Engine not running.</p>
                  <p className="text-slate-600 text-xs">
                    Start the engine to see real alerts from INDRA events.
                  </p>
                </>
              )}
            </div>
          )}

          {/* Alert Cards */}
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="space-y-4"
          >
            <AnimatePresence mode="popLayout">
              {filtered.map((alert) => (
                <AlertCard
                  key={alert.alert_id}
                  alert={alert}
                  onAcknowledge={handleAcknowledge}
                  onResolve={handleResolve}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        </main>
      </div>
    </div>
  );
}
