'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
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
} from 'lucide-react';
import { fetchAgencyAlerts, type AgencyAlert } from '@/lib/api';
import { useTranslation } from '@/lib/i18n/useTranslation';

type SeverityKey = 'EXTREME' | 'SEVERE' | 'MODERATE' | 'MINOR' | 'ADVISORY' | 'UNKNOWN';

const severityConfig: Record<SeverityKey, { label: string; dotClass: string; pillClass: string }> = {
  EXTREME:  { label: 'Extreme',  dotClass: 'bg-severity-critical', pillClass: 'bg-severity-critical/15 text-severity-critical border-severity-critical/30' },
  SEVERE:   { label: 'Severe',   dotClass: 'bg-severity-high',     pillClass: 'bg-severity-high/15 text-severity-high border-severity-high/35' },
  MODERATE: { label: 'Moderate', dotClass: 'bg-severity-moderate', pillClass: 'bg-severity-moderate/15 text-severity-moderate border-severity-moderate/35' },
  MINOR:    { label: 'Minor',    dotClass: 'bg-severity-low',      pillClass: 'bg-severity-low/15 text-severity-low border-severity-low/25' },
  ADVISORY: { label: 'Advisory', dotClass: 'bg-text-muted',        pillClass: 'bg-text-muted/15 text-text-muted border-text-muted/25' },
  UNKNOWN:  { label: 'Unrated',  dotClass: 'bg-text-muted',        pillClass: 'bg-text-muted/15 text-text-muted border-text-muted/25' },
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
  const containerRef = useRef<HTMLDivElement>(null);

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const data = await fetchAgencyAlerts(8, false);
      setAlerts(data);
    } catch {
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (isOpen) loadAlerts(); }, [isOpen, loadAlerts]);

  // The bell's dot means a warning is in force, so the count is fetched on
  // mount and every two minutes, not only when the popover opens.
  useEffect(() => {
    const refresh = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
      fetchAgencyAlerts(8, false)
        .then((data) => setAlerts(data))
        .catch(() => { /* the dot stays as it was; opening the popover shows the error */ });
    };
    refresh();
    const id = setInterval(refresh, 120_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setIsOpen(false);
    };
    if (isOpen) document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [isOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setIsOpen(false); };
    if (isOpen) document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen]);

  const hasAlerts = alerts.length > 0;
  const hasHigh = alerts.some((a) => { const s = normaliseSeverity(a.severity); return s === 'EXTREME' || s === 'SEVERE'; });

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <button
        onClick={() => setIsOpen((p) => !p)}
        aria-label={isOpen ? 'Close notifications' : 'Open operational bulletins'}
        aria-expanded={isOpen}
        className="relative p-2 rounded-md hover:bg-surface-raised transition-colors focus:outline-none focus:ring-2 focus:ring-brand/30"
        id="notification-bell"
      >
        {hasHigh && isOpen
          ? <BellRing className="w-5 h-5 text-brand" />
          : <Bell className={`w-5 h-5 transition-colors ${isOpen ? 'text-brand' : 'text-text-muted'}`} />
        }
        {hasAlerts && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-severity-critical ring-1 ring-surface animate-pulse" />
        )}
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.97 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="absolute right-0 mt-2 z-50 w-[360px] sm:w-[400px] rounded-xl border border-border overflow-hidden shadow-xl bg-surface"
            role="dialog"
            aria-label="Operational Bulletins and Alerts"
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-raised">
              <div className="flex items-center gap-2">
                <Radio className="w-3.5 h-3.5 text-text-muted" />
                <span className="text-[11px] font-bold tracking-wider uppercase text-text-secondary">{t('nav.notifications')}</span>
                {hasAlerts && (
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/20">
                    {alerts.length} active
                  </span>
                )}
              </div>
              <button onClick={() => setIsOpen(false)} className="p-1 rounded-md hover:bg-surface transition-colors text-text-muted hover:text-text" aria-label="Close">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="max-h-[340px] overflow-y-auto overscroll-contain divide-y divide-border">
              {loading && (
                <div className="p-4 space-y-3">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex gap-3 items-start animate-pulse">
                      <div className="w-2 h-2 rounded-full bg-border mt-1.5 flex-shrink-0" />
                      <div className="flex-1 space-y-1.5">
                        <div className="h-3 bg-border rounded-md w-4/5" />
                        <div className="h-2.5 bg-border rounded-md w-3/5" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!loading && fetchError && (
                <div className="flex flex-col items-center justify-center py-10 px-6 gap-2 text-center">
                  <AlertTriangle className="w-7 h-7 text-brand/60" />
                  <p className="text-sm font-medium text-text-secondary">{t('common.error')}</p>
                  <p className="text-xs text-text-muted">The backend did not answer. Check server status.</p>
                  <button onClick={loadAlerts} className="mt-2 text-xs font-semibold text-brand hover:underline">{t('common.retry')}</button>
                </div>
              )}

              {!loading && !fetchError && alerts.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 px-6 gap-2 text-center">
                  <div className="w-10 h-10 rounded-full bg-status-verified/10 border border-status-verified/20 flex items-center justify-center">
                    <CheckCircle className="w-5 h-5 text-status-verified" />
                  </div>
                  <p className="text-sm font-semibold text-text">No official warning in force</p>
                  <p className="text-xs text-text-muted leading-relaxed max-w-[260px]">INDRA&apos;s SACHET feed holds no active bulletin from IMD, CWC or a state SDMA.</p>
                </div>
              )}

              {!loading && !fetchError && alerts.map((alert) => {
                const sev = normaliseSeverity(alert.severity);
                const cfg = severityConfig[sev];
                const time = relativeTime(alert.sent_at ?? alert.effective_at);
                return (
                  <div key={alert.id} className="flex gap-3 items-start px-4 py-3 hover:bg-surface-raised transition-colors">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-[5px] ${cfg.dotClass}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-text leading-snug line-clamp-2">
                        {alert.headline || (alert.event ? t.hazard(alert.event) : t('nav.official_warnings'))}
                      </p>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border leading-none ${cfg.pillClass}`}>
                          {t.severity(alert.severity)}
                        </span>
                        {alert.sender && <span className="text-[10px] text-text-muted truncate max-w-[140px]">{alert.sender}</span>}
                        {alert.location_label && <span className="text-[10px] text-text-muted truncate max-w-[120px]">· {alert.location_label}</span>}
                        {time && <span className="text-[10px] text-text-muted ml-auto flex-shrink-0">{time}</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="px-4 py-2.5 border-t border-border flex items-center justify-between bg-surface-raised">
              <span className="text-[10px] text-text-muted">
                {hasAlerts ? `${alerts.length} active` : 'SACHET · IMD · CWC · State SDMAs'}
              </span>
              <Link href="/alerts" onClick={() => setIsOpen(false)} className="flex items-center gap-1 text-[11px] font-semibold text-brand hover:text-brand/80 transition-colors group">
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
