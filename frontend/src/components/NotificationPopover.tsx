'use client';

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import {
  Bell,
  BellRing,
  X,
  AlertTriangle,
  CheckCircle,
  ExternalLink,
  Radio,
  RefreshCw,
  ChevronRight,
  Flame,
  Info,
} from 'lucide-react';
import { fetchAgencyAlerts, type AgencyAlert } from '@/lib/api';
import { useTranslation } from '@/lib/i18n/useTranslation';

type SeverityKey = 'EXTREME' | 'SEVERE' | 'MODERATE' | 'MINOR' | 'ADVISORY' | 'UNKNOWN';
type FilterTab = 'all' | 'critical' | 'advisory';

const severityConfig: Record<SeverityKey, { label: string; dotClass: string; pillClass: string }> = {
  EXTREME:  { label: 'Extreme',  dotClass: 'bg-red-600',     pillClass: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30' },
  SEVERE:   { label: 'Severe',   dotClass: 'bg-amber-600',   pillClass: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/35' },
  MODERATE: { label: 'Moderate', dotClass: 'bg-yellow-600',  pillClass: 'bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border-yellow-500/35' },
  MINOR:    { label: 'Minor',    dotClass: 'bg-emerald-600', pillClass: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/25' },
  ADVISORY: { label: 'Advisory', dotClass: 'bg-slate-500',   pillClass: 'bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/25' },
  UNKNOWN:  { label: 'Unrated',  dotClass: 'bg-slate-400',   pillClass: 'bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/25' },
};

function normaliseSeverity(raw: string | null): SeverityKey {
  const upper = (raw ?? '').toUpperCase();
  if (upper === 'CRITICAL') return 'EXTREME';
  if (upper === 'HIGH') return 'SEVERE';
  if (upper === 'LOW') return 'MINOR';
  if (upper === 'INFO') return 'ADVISORY';
  if (upper in severityConfig) return upper as SeverityKey;
  return 'UNKNOWN';
}

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function NotificationPopover({ className = '' }: { className?: string }) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [alerts, setAlerts] = useState<AgencyAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState(false);
  const [activeTab, setActiveTab] = useState<FilterTab>('all');
  const containerRef = useRef<HTMLDivElement>(null);

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const data = await fetchAgencyAlerts(12, false);
      setAlerts(data);
    } catch {
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadAlerts();
    }
  }, [isOpen, loadAlerts]);

  // Periodic background refresh for notification badge
  useEffect(() => {
    const refresh = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
      fetchAgencyAlerts(12, false)
        .then((data) => setAlerts(data))
        .catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, 120_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [isOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    if (isOpen) document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen]);

  const hasAlerts = alerts.length > 0;
  const criticalCount = useMemo(() => {
    return alerts.filter((a) => {
      const s = normaliseSeverity(a.severity);
      return s === 'EXTREME' || s === 'SEVERE';
    }).length;
  }, [alerts]);

  const advisoryCount = useMemo(() => {
    return alerts.filter((a) => {
      const s = normaliseSeverity(a.severity);
      return s === 'MODERATE' || s === 'MINOR' || s === 'ADVISORY' || s === 'UNKNOWN';
    }).length;
  }, [alerts]);

  const filteredAlerts = useMemo(() => {
    if (activeTab === 'critical') {
      return alerts.filter((a) => {
        const s = normaliseSeverity(a.severity);
        return s === 'EXTREME' || s === 'SEVERE';
      });
    }
    if (activeTab === 'advisory') {
      return alerts.filter((a) => {
        const s = normaliseSeverity(a.severity);
        return s === 'MODERATE' || s === 'MINOR' || s === 'ADVISORY' || s === 'UNKNOWN';
      });
    }
    return alerts;
  }, [alerts, activeTab]);

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <button
        onClick={() => setIsOpen((p) => !p)}
        aria-label={isOpen ? 'Close notifications' : 'Open operational bulletins'}
        aria-expanded={isOpen}
        className="relative p-2 rounded-md hover:bg-black/[0.04] dark:hover:bg-white/[0.08] transition-colors focus:outline-none focus:ring-2 focus:ring-brand/30"
        id="notification-bell"
      >
        {criticalCount > 0 && isOpen ? (
          <BellRing className="w-5 h-5 text-brand" />
        ) : (
          <Bell className={`w-5 h-5 transition-colors ${isOpen ? 'text-brand' : 'text-text-muted'}`} />
        )}
        {hasAlerts && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-600 text-white text-[9px] font-bold flex items-center justify-center ring-2 ring-white dark:ring-slate-900 shadow-sm animate-pulse">
            {alerts.length > 9 ? '9+' : alerts.length}
          </span>
        )}
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.97 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="absolute right-0 mt-2 z-50 w-[360px] sm:w-[420px] rounded-xl border border-border shadow-[0_16px_40px_rgba(0,0,0,0.22)] overflow-hidden bg-surface"
            style={{
              backgroundColor: 'var(--card, #FDFAF5)',
              borderColor: 'var(--paper-3, #E8E2D4)',
            }}
            role="dialog"
            aria-label="Operational Bulletins and Alerts"
          >
            {/* Header */}
            <div
              className="flex items-center justify-between px-4 py-3 border-b"
              style={{
                backgroundColor: 'var(--paper-2, #FFFFFF)',
                borderColor: 'var(--paper-3, #E8E2D4)',
              }}
            >
              <div className="flex items-center gap-2">
                <Radio className="w-3.5 h-3.5 text-brand animate-pulse" />
                <span className="text-xs font-bold tracking-wider uppercase text-text">
                  {t('nav.notifications')}
                </span>
                {hasAlerts && (
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/20">
                    {alerts.length} active
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={loadAlerts}
                  disabled={loading}
                  className="p-1 rounded-md hover:bg-black/[0.04] dark:hover:bg-white/[0.08] transition-colors text-text-muted hover:text-text"
                  aria-label="Refresh alerts"
                  title="Refresh bulletin feed"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-brand' : ''}`} />
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1 rounded-md hover:bg-black/[0.04] dark:hover:bg-white/[0.08] transition-colors text-text-muted hover:text-text"
                  aria-label="Close"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Filter Tabs */}
            <div
              className="flex items-center gap-1 px-3 py-1.5 border-b text-[11px] font-medium"
              style={{
                backgroundColor: 'var(--paper-2, #FFFFFF)',
                borderColor: 'var(--paper-3, #E8E2D4)',
              }}
            >
              <button
                onClick={() => setActiveTab('all')}
                className={`px-2.5 py-1 rounded-lg transition-all ${
                  activeTab === 'all'
                    ? 'bg-brand/15 text-brand font-semibold shadow-2xs'
                    : 'text-text-muted hover:text-text hover:bg-black/[0.03] dark:hover:bg-white/[0.05]'
                }`}
              >
                All ({alerts.length})
              </button>
              <button
                onClick={() => setActiveTab('critical')}
                className={`px-2.5 py-1 rounded-lg flex items-center gap-1 transition-all ${
                  activeTab === 'critical'
                    ? 'bg-red-500/15 text-red-600 dark:text-red-400 font-semibold shadow-2xs'
                    : 'text-text-muted hover:text-text hover:bg-black/[0.03] dark:hover:bg-white/[0.05]'
                }`}
              >
                <Flame className="w-3 h-3 text-red-500" />
                Critical ({criticalCount})
              </button>
              <button
                onClick={() => setActiveTab('advisory')}
                className={`px-2.5 py-1 rounded-lg flex items-center gap-1 transition-all ${
                  activeTab === 'advisory'
                    ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold shadow-2xs'
                    : 'text-text-muted hover:text-text hover:bg-black/[0.03] dark:hover:bg-white/[0.05]'
                }`}
              >
                <Info className="w-3 h-3 text-amber-500" />
                Advisories ({advisoryCount})
              </button>
            </div>

            {/* Notifications Body List */}
            <div
              className="max-h-[360px] overflow-y-auto overscroll-contain divide-y"
              style={{
                backgroundColor: 'var(--card, #FDFAF5)',
                borderColor: 'var(--paper-3, #E8E2D4)',
              }}
            >
              {loading && alerts.length === 0 && (
                <div className="p-4 space-y-3">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex gap-3 items-start animate-pulse">
                      <div className="w-2.5 h-2.5 rounded-full bg-border mt-1.5 flex-shrink-0" />
                      <div className="flex-1 space-y-1.5">
                        <div className="h-3 bg-border rounded-md w-4/5" />
                        <div className="h-2.5 bg-border rounded-md w-3/5" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!loading && fetchError && alerts.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 px-6 gap-2 text-center">
                  <AlertTriangle className="w-7 h-7 text-brand/60" />
                  <p className="text-sm font-medium text-text-secondary">{t('common.error')}</p>
                  <p className="text-xs text-text-muted">The backend did not answer. Check server status.</p>
                  <button
                    onClick={loadAlerts}
                    className="mt-2 text-xs font-semibold text-brand hover:underline"
                  >
                    {t('common.retry')}
                  </button>
                </div>
              )}

              {!loading && !fetchError && filteredAlerts.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 px-6 gap-2 text-center">
                  <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                    <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                  </div>
                  <p className="text-sm font-semibold text-text">
                    {activeTab === 'all'
                      ? 'No official warning in force'
                      : activeTab === 'critical'
                      ? 'No critical warnings in force'
                      : 'No advisory bulletins in force'}
                  </p>
                  <p className="text-xs text-text-muted leading-relaxed max-w-[260px]">
                    INDRA&apos;s SACHET feed holds no active bulletin from IMD, CWC or a state SDMA for this filter.
                  </p>
                </div>
              )}

              {filteredAlerts.map((alert) => {
                const sev = normaliseSeverity(alert.severity);
                const cfg = severityConfig[sev];
                const time = relativeTime(alert.sent_at ?? alert.effective_at);
                return (
                  <Link
                    key={alert.id}
                    href="/alerts"
                    onClick={() => setIsOpen(false)}
                    className="flex gap-3 items-start px-4 py-3 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors group cursor-pointer block"
                    style={{
                      backgroundColor: 'var(--card, #FDFAF5)',
                    }}
                  >
                    <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 mt-1 shadow-2xs ${cfg.dotClass}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-1.5">
                        <p className="text-xs font-semibold text-text leading-snug line-clamp-2 group-hover:text-brand transition-colors">
                          {alert.headline || (alert.event ? t.hazard(alert.event) : t('nav.official_warnings'))}
                        </p>
                        <ChevronRight className="w-3.5 h-3.5 text-text-muted group-hover:text-brand group-hover:translate-x-0.5 transition-all flex-shrink-0 mt-0.5" />
                      </div>
                      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border leading-none ${cfg.pillClass}`}>
                          {t.severity(alert.severity)}
                        </span>
                        {alert.sender && (
                          <span className="text-[10px] font-medium text-text-secondary truncate max-w-[140px] px-1.5 py-0.5 rounded bg-black/[0.03] dark:bg-white/[0.05]">
                            {alert.sender}
                          </span>
                        )}
                        {alert.location_label && (
                          <span className="text-[10px] text-text-muted truncate max-w-[120px]">
                            · {alert.location_label}
                          </span>
                        )}
                        {time && (
                          <span className="text-[10px] text-text-muted ml-auto flex-shrink-0 font-mono">
                            {time}
                          </span>
                        )}
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>

            {/* Footer */}
            <div
              className="px-4 py-2.5 border-t flex items-center justify-between"
              style={{
                backgroundColor: 'var(--paper-2, #FFFFFF)',
                borderColor: 'var(--paper-3, #E8E2D4)',
              }}
            >
              <span className="text-[10px] text-text-muted font-medium">
                {filteredAlerts.length} shown · SACHET / IMD Feed
              </span>
              <Link
                href="/alerts"
                onClick={() => setIsOpen(false)}
                className="flex items-center gap-1 text-[11px] font-semibold text-brand hover:text-brand/80 transition-colors group"
              >
                {t('nav.official_warnings')}
                <ExternalLink className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

