'use client';

/**
 * Warnings page.
 *
 * Two kinds of card, never mixed up:
 *
 * 1. **Official warnings** — CAP alerts issued by IMD, CWC and state SDMAs,
 *    collected from NDMA's SACHET feed by the backend poller
 *    (GET /api/alerts/agency). These are real government warnings, shown with
 *    the issuing agency's own words.
 * 2. **INDRA events** — HIGH or CRITICAL events the platform fused from
 *    reports, shown with their true review status. INDRA does not issue
 *    warnings (the alert engine was cancelled), so these are labelled as events
 *    and are never credited to an agency.
 *
 * This page used to append four hardcoded bulletins credited to IMD, the
 * Cyclone Warning Division, GSI and CWC — a fictional "Cyclone Marut", "port
 * signal 8 hoisted", "2,85,000 cusecs" — to every load, and to present any
 * HIGH or CRITICAL event, quarantined ones included, as a "CRITICAL WARNING"
 * from an "NDMA Emergency Operation Centre", with a canned evacuation
 * directive attached.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  ShieldAlert,
  Clock,
  ChevronRight,
  Search,
  Loader2,
  ShieldCheck,
  RefreshCw,
  Radio,
  MapPin,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import EventVerificationModal from '@/components/EventVerificationModal';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import {
  fetchEvents,
  fetchAgencyAlerts,
  formatPlace,
  type ApiEvent,
  type AgencyAlert,
  type EngineAlert,
  fetchEngineAlerts,
  acknowledgeEngineAlert,
  resolveEngineAlert,
  ALERT_ENGINE_WS,
} from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { safeEventState } from '@/lib/eventState';
import { useTranslation } from '@/lib/i18n/useTranslation';

type Level = 'RED' | 'ORANGE' | 'YELLOW';

interface WarningCard {
  key: string;
  kind: 'official' | 'indra';
  level: Level;
  title: string;
  /** Who said it: the CAP sender, or "INDRA" for a fused event. */
  source: string;
  issuedAt: string;
  validUntil: string | null;
  area: string;
  description: string;
  /** Extra facts shown as small chips: CAP urgency/certainty, review status. */
  facts: string[];
  eventId?: string;
  confidenceScore?: number;
}

const REVIEW_LABEL: Record<string, string> = {
  AUTO_PUBLISHED: 'Auto-published',
  HUMAN_APPROVED: 'Approved by an operator',
  PENDING_HUMAN_REVIEW: 'Awaiting operator review',
  QUARANTINED: 'Quarantined — not verified',
};

function levelForSeverity(severity: string | null | undefined): Level {
  const s = (severity || '').toUpperCase();
  if (s === 'CRITICAL') return 'RED';
  if (s === 'HIGH') return 'ORANGE';
  return 'YELLOW';
}

function relativeTime(ts: string | null): string {
  if (!ts) return 'time not given';
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ${mins % 60}m ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function istTime(ts: string | null): string | null {
  if (!ts) return null;
  return (
    new Date(ts).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }) + ' IST'
  );
}

function officialCard(a: AgencyAlert): WarningCard {
  const facts = [
    a.raw_severity ? `CAP severity: ${a.raw_severity}` : 'Severity not rated by the issuer',
    a.urgency ? `Urgency: ${a.urgency}` : null,
    a.certainty ? `Certainty: ${a.certainty}` : null,
  ].filter((f): f is string => Boolean(f));
  return {
    key: `alert-${a.id}`,
    kind: 'official',
    level: levelForSeverity(a.severity),
    title: a.event || 'Warning',
    source: a.sender || 'Issuing agency not named',
    issuedAt: relativeTime(a.sent_at),
    validUntil: istTime(a.expires_at),
    area: a.area_desc || a.location_label || 'Area not given',
    description: a.headline || '',
    facts,
  };
}

function indraCard(ev: ApiEvent): WarningCard {
  // The API's review_status and quadrant, derived only when absent (BUG-070).
  const derivedState = safeEventState(ev.id, ev.severity, ev.confidence_score, ev.review_status, ev.quadrant);
  const status = REVIEW_LABEL[derivedState.reviewStatus] || derivedState.reviewLabel;
  const reports = ev.corroborating_reports_count;
  return {
    key: `event-${ev.id}`,
    kind: 'indra',
    level: levelForSeverity(ev.severity),
    title: `${ev.eventType} — ${ev.severity.toUpperCase()} severity`,
    source: 'INDRA',
    issuedAt: relativeTime(ev.timestamp || ev.verified_at),
    validUntil: null,
    area: formatPlace(ev.city, ev.state, ev.place_precision),
    description:
      reports != null
        ? `Fused from ${reports} report${reports === 1 ? '' : 's'}. ${status}.`
        : `${status}.`,
    facts: [status, ev.event_code],
    eventId: ev.id,
    confidenceScore: ev.confidence_score,
  };
}

const LEVEL_STYLE: Record<Level, { border: string; strip: string; badge: string }> = {
  RED: {
    border: 'border-rose-200 hover:border-rose-300',
    strip: '5px solid #8C2F26',
    badge: 'bg-rose-600 text-white',
  },
  ORANGE: {
    border: 'border-amber-200 hover:border-amber-300',
    strip: '5px solid #B8873A',
    badge: 'bg-amber-500 text-slate-950',
  },
  YELLOW: {
    border: 'border-yellow-200 hover:border-yellow-300',
    strip: '5px solid #CA8A04',
    badge: 'bg-yellow-300 text-slate-950',
  },
};

export default function AlertsPage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [selectedLevel, setSelectedLevel] = useState<'ALL' | Level>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [agencyAlerts, setAgencyAlerts] = useState<AgencyAlert[]>([]);
  const [events, setEvents] = useState<ApiEvent[]>([]);
  const [alertsFailed, setAlertsFailed] = useState(false);
  const [eventsFailed, setEventsFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [verificationEventId, setVerificationEventId] = useState<string | null>(null);
  const { subscribe } = useIndraWebSocket();

  const loadWarnings = useCallback(async () => {
    const [alertsResult, eventsResult] = await Promise.allSettled([
      fetchAgencyAlerts(100),
      fetchEvents({ time_range: '7d' }),
    ]);
    if (alertsResult.status === 'fulfilled') {
      setAgencyAlerts(alertsResult.value);
      setAlertsFailed(false);
    } else {
      setAlertsFailed(true);
    }
    if (eventsResult.status === 'fulfilled') {
      setEvents(eventsResult.value);
      setEventsFailed(false);
    } else {
      setEventsFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadWarnings();
  }, [loadWarnings]);

  useEffect(() => {
    return subscribe('alerts-page', (msg) => {
      if (['VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        loadWarnings();
      }
    });
  }, [subscribe, loadWarnings]);

  const cards = useMemo<WarningCard[]>(() => {
    const official = agencyAlerts.map(officialCard);
    const severe = events
      .filter((ev) => ['CRITICAL', 'HIGH'].includes((ev.severity || '').toUpperCase()))
      .map(indraCard);
    const rank: Record<Level, number> = { RED: 0, ORANGE: 1, YELLOW: 2 };
    return [...official, ...severe].sort((a, b) => rank[a.level] - rank[b.level]);
  }, [agencyAlerts, events]);

  const filtered = cards.filter((c) => {
    if (selectedLevel !== 'ALL' && c.level !== selectedLevel) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return [c.title, c.description, c.area, c.source].some((f) => f.toLowerCase().includes(q));
    }
    return true;
  });

  const count = (level: Level) => cards.filter((c) => c.level === level).length;
  const officialCount = cards.filter((c) => c.kind === 'official').length;
  const indraCount = cards.length - officialCount;

  return (
    <div className="min-h-screen bg-[#F7F3EA] text-[#1B2432]">
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
          <div className="bg-gradient-to-r from-[#8C2F26] via-[#73241C] to-[#1B2432] text-white p-5 rounded-2xl border border-[#B5482E]/30 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                <ShieldAlert className="w-5 h-5 text-rose-300" />
                <h1
                  className="text-xl font-bold tracking-wide"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  {t('nav.official_warnings')}
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-white/10 text-rose-100 border border-white/20">
                  {officialCount} {t('kpis.delta_in_force')}
                </span>
                {indraCount > 0 && (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-white/10 text-amber-100 border border-white/20">
                    {indraCount} {t('chart.events')}
                  </span>
                )}
              </div>
              <p className="text-xs text-rose-100/80 max-w-3xl">
                Official warnings are issued by IMD, CWC and state SDMAs and collected from NDMA&apos;s
                SACHET feed. INDRA events are fused from reports and carry their review status.
                INDRA itself does not issue warnings.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-black/30 border border-white/20 text-xs font-mono text-rose-100">
                <Radio className="w-3.5 h-3.5" />
                {alertsFailed ? 'SACHET feed unavailable' : 'SACHET feed via backend poller'}
              </div>
              <button
                onClick={() => {
                  setLoading(true);
                  loadWarnings();
                }}
                disabled={loading}
                className="p-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {(alertsFailed || eventsFailed) && (
            <div
              role="alert"
              className="p-3 rounded-xl bg-rose-50 border border-rose-100 text-xs font-semibold text-rose-700"
            >
              {alertsFailed && 'Official warnings could not be loaded from the backend. '}
              {eventsFailed && 'INDRA events could not be loaded from the backend.'}
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              {([
                { id: 'ALL', label: `${t('common.view_all')} (${cards.length})` },
                { id: 'RED', label: `${t('severity.CRITICAL')} (${count('RED')})` },
                { id: 'ORANGE', label: `${t('severity.HIGH')} (${count('ORANGE')})` },
                { id: 'YELLOW', label: `${t('severity.MODERATE')} (${count('YELLOW')})` },
              ] as const).map((lvl) => (
                <button
                  key={lvl.id}
                  onClick={() => setSelectedLevel(lvl.id)}
                  className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                    selectedLevel === lvl.id
                      ? 'bg-[#1B2432] text-white shadow-sm'
                      : 'bg-white text-[#4A5568] border border-[#E8E2D4] hover:bg-[#F0EBE0]'
                  }`}
                >
                  {lvl.label}
                </button>
              ))}
            </div>

            <div className="relative w-full sm:w-72">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#A0988A]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('nav.search_placeholder')}
                className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-white border border-[#E8E2D4] text-xs text-[#1B2432] placeholder-[#A0988A] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 transition-all shadow-2xs"
              />
            </div>
          </div>

          {/* Cards */}
          {loading && cards.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 bg-white rounded-2xl border border-[#E8E2D4]">
              <Loader2 className="w-8 h-8 text-[#B5482E] animate-spin mb-3" />
              <p className="text-sm font-medium text-[#7A8599]">{t('common.loading')}...</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center bg-white rounded-2xl border border-[#E8E2D4] text-[#7A8599] text-sm">
              {cards.length === 0
                ? t('chart.no_warnings_force')
                : 'Nothing matches this filter.'}
            </div>
          ) : (
            <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-4">
              {filtered.map((c) => {
                const style = LEVEL_STYLE[c.level];
                return (
                  <motion.div
                    key={c.key}
                    variants={fadeIn}
                    data-kind={c.kind}
                    className={`rounded-2xl border p-5 shadow-xs bg-white transition-all hover:shadow-md ${style.border}`}
                    style={{ borderLeft: style.strip }}
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span className={`text-xs font-black font-mono px-2.5 py-0.5 rounded-md ${style.badge}`}>
                          {t.severity(c.level)}
                        </span>
                        {c.kind === 'official' ? (
                          <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-[#1B2432] text-white">
                            {t('nav.official_warnings')}
                          </span>
                        ) : (
                          <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-[#F7F3EA] text-[#4A5568] border border-[#E8E2D4]">
                            {t('nav.incident_events')}
                          </span>
                        )}
                        <span className="text-xs text-[#4A5568] font-semibold">{c.source}</span>
                      </div>

                      <div className="flex items-center gap-2 text-xs font-mono text-[#7A8599]">
                        <Clock className="w-3.5 h-3.5 text-[#A0988A]" />
                        <span>
                          {c.kind === 'official' ? 'Issued' : 'Updated'} {c.issuedAt}
                        </span>
                        {c.validUntil && <span>• Valid until {c.validUntil}</span>}
                      </div>
                    </div>

                    <h2
                      className="text-base font-bold text-[#1B2432] mb-2 leading-snug"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      {c.title}
                    </h2>

                    {c.description && (
                      <p className="text-xs sm:text-sm text-[#4A5568] mb-3.5 leading-relaxed">{c.description}</p>
                    )}

                    <div className="flex items-start gap-1.5 mb-3 text-xs text-[#4A5568]">
                      <MapPin className="w-3.5 h-3.5 mt-0.5 text-[#A0988A] flex-shrink-0" />
                      <span>{c.area}</span>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {c.facts.map((fact) => (
                        <span
                          key={fact}
                          className="text-[11px] font-mono bg-[#F7F3EA] text-[#4A5568] px-2 py-0.5 rounded-md border border-[#E8E2D4]"
                        >
                          {fact}
                        </span>
                      ))}
                    </div>

                    {c.eventId && (
                      <div className="mt-3 pt-2 border-t border-[#F0EBE0] flex items-center justify-between">
                        <span className="text-[11px] font-mono text-[#7A8599] flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" />
                          {t('receipt.confidence_label')} {Math.round((c.confidenceScore || 0) * 100)}%
                        </span>
                        <button
                          onClick={() => setVerificationEventId(c.eventId!)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#F7F3EA] hover:bg-[#F0EBE0] text-[#1B2432] text-xs font-medium border border-[#E8E2D4] transition-colors"
                        >
                          <ShieldCheck className="w-3.5 h-3.5 text-[#B5482E]" />
                          {t('receipt.title')}
                          <ChevronRight className="w-3.5 h-3.5 text-[#A0988A]" />
                        </button>
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </motion.div>
          )}

          {/* Alert Engine Additive Section */}
          <div className="mt-12 pt-8 border-t border-[#E8E2D4]">
            <AlertEngineSection />
          </div>

        </main>
      </div>

      <EventVerificationModal
        eventId={verificationEventId}
        onClose={() => setVerificationEventId(null)}
        onEventUpdated={() => loadWarnings()}
      />
    </div>
  );
}

function AlertEngineSection() {
  const [engineAlerts, setEngineAlerts] = useState<EngineAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  const loadAlerts = useCallback(async () => {
    try {
      const data = await fetchEngineAlerts();
      setEngineAlerts(data);
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  useEffect(() => {
    if (!ALERT_ENGINE_WS) return;
    const ws = new WebSocket(ALERT_ENGINE_WS);
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (['ENGINE_ALERT_CREATED', 'ENGINE_ALERT_UPDATED', 'ENGINE_ALERT_RESOLVED'].includes(msg.type)) {
          loadAlerts();
        }
      } catch (err) {}
    };
    return () => ws.close();
  }, [loadAlerts]);

  const handleAction = async (alertId: string, action: 'ack' | 'res') => {
    let result;
    if (action === 'ack') result = await acknowledgeEngineAlert(alertId);
    if (action === 'res') result = await resolveEngineAlert(alertId, "Resolved by operator");
    if (result && !result.success) {
      alert(`Action failed: ${result.error}`);
    }
    loadAlerts();
  };

  if (loading) {
    return (
      <div className="p-6 bg-white rounded-2xl border border-[#E8E2D4] text-center">
        <Loader2 className="w-6 h-6 text-[#B5482E] animate-spin mx-auto mb-2" />
        <p className="text-sm text-[#7A8599]">Checking Alert Engine...</p>
      </div>
    );
  }

  if (offline || (!loading && engineAlerts.length === 0 && offline)) {
    return (
      <div className="p-6 bg-rose-50 rounded-2xl border border-rose-100 text-center">
        <AlertTriangle className="w-6 h-6 text-rose-500 mx-auto mb-2" />
        <h3 className="text-sm font-bold text-rose-700">Alert Engine Offline</h3>
        <p className="text-xs text-rose-600/80 mt-1">The independent Alert Engine service is currently unreachable.</p>
      </div>
    );
  }

  if (engineAlerts.length === 0) {
    return (
      <div className="p-6 bg-white rounded-2xl border border-[#E8E2D4] text-center">
        <ShieldCheck className="w-6 h-6 text-emerald-500 mx-auto mb-2" />
        <h3 className="text-sm font-bold text-[#1B2432]">Alert Engine Active</h3>
        <p className="text-xs text-[#7A8599] mt-1">No active alerts generated by the engine at this time.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <Radio className="w-5 h-5 text-indigo-500" />
        <h2 className="text-lg font-bold text-[#1B2432]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
          INDRA Alert Engine
        </h2>
        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-100 text-indigo-700">
          ADDITIVE SERVICE
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {engineAlerts.map(alert => (
          <div key={alert.id} className="bg-white rounded-2xl border border-[#E8E2D4] p-4 shadow-sm relative overflow-hidden">
            <div className={`absolute top-0 left-0 w-1 h-full ${alert.status === 'ACTIVE' ? 'bg-rose-500' : alert.status === 'ESCALATED' ? 'bg-purple-500' : 'bg-emerald-500'}`} />
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-[#F7F3EA] border border-[#E8E2D4]">
                  {alert.rule_name || alert.rule_id}
                </span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${alert.status === 'ACTIVE' ? 'bg-rose-100 text-rose-700' : alert.status === 'ESCALATED' ? 'bg-purple-100 text-purple-700' : 'bg-emerald-100 text-emerald-700'}`}>
                  {alert.status}
                </span>
                {alert.mode === 'DEMO' && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-100 text-amber-700">
                    DEMO ALERT
                  </span>
                )}
                {alert.mode === 'LIVE' && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-100 text-blue-700">
                    LIVE ALERT
                  </span>
                )}
              </div>
              <span className="text-[10px] text-[#7A8599] font-mono">
                {new Date(alert.updated_at).toLocaleTimeString()}
              </span>
            </div>
            
            <h3 className="font-bold text-[#1B2432] text-sm mb-1">{alert.message}</h3>
            {alert.affected_area && (
              <div className="flex items-center gap-1 text-xs text-[#4A5568] mb-3">
                <MapPin className="w-3 h-3 text-[#A0988A]" />
                {alert.affected_area}
              </div>
            )}

            <div className="flex items-center justify-between mt-3 pt-3 border-t border-[#E8E2D4]">
              <div className="text-[10px] text-[#7A8599]">
                {alert.notification_status ? `Notification: ${alert.notification_status}` : 'No notification sent'}
                {alert.acknowledged_by && ` • Ack by ${alert.acknowledged_by}`}
              </div>
              <div className="flex gap-2">
                {!alert.acknowledged_by && ['ACTIVE', 'ESCALATED'].includes(alert.status) && (
                  <button onClick={() => handleAction(alert.id, 'ack')} className="px-3 py-1 rounded-md text-xs font-semibold bg-[#F7F3EA] border border-[#E8E2D4] hover:bg-[#F0EBE0] text-[#1B2432]">
                    Acknowledge
                  </button>
                )}
                {['ACTIVE', 'ESCALATED'].includes(alert.status) && (
                  <button onClick={() => handleAction(alert.id, 'res')} className="px-3 py-1 rounded-md text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100">
                    Resolve
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
