'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarClock,
  MapPin,
  Clock,
  Search,
  ExternalLink,
  ShieldAlert,
  Radio,
  Shield,
  Loader2,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import EventVerificationModal from '@/components/EventVerificationModal';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import Link from 'next/link';
import { fetchEvents, fetchSummaryCounts, formatPlace, type ApiEvent } from '@/lib/api';
import { ErrorState } from '@/components/ui/empty-state';
import { safeEventState } from '@/lib/eventState';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { useTranslation } from '@/lib/i18n/useTranslation';

// Issue 3 fix: per-hazard plausible maximum impact radius (km).
// If the raw value exceeds the ceiling, the display layer hides it rather than
// guessing at a corrected value. The root cause is almost certainly a units
// bug upstream (degrees/meters shown as km, or a squared value).
// NOTE TO BACKEND TEAM: please verify the units of impact_radius_km in the
// event-generation and fusion code. This clamp is a display-only safeguard.
const IMPACT_RADIUS_MAX_KM: Record<string, number> = {
  'Severe Rainfall':  100,
  'Heavy Rainfall':   100,
  'Thunderstorm':     100,
  'Fog':              100,
  'Strong Winds':     150,
  'Dust Storm':       100,
  'Flood':            300,
  'Urban Flooding':   100,
};
const IMPACT_RADIUS_DEFAULT_MAX = 150; // km — fallback for unknown hazard types

function clampImpactRadius(eventId: string, eventType: string, rawKm: number | null | undefined): string {
  if (rawKm == null || rawKm <= 0) return '—';
  const ceiling = IMPACT_RADIUS_MAX_KM[eventType] ?? IMPACT_RADIUS_DEFAULT_MAX;
  if (rawKm > ceiling) {
    console.warn(
      `[INDRA] Event ${eventId}: impact_radius_km=${rawKm.toFixed(1)} exceeds ` +
      `the ${ceiling} km ceiling for "${eventType}". Showing "unavailable". ` +
      `Likely a units bug upstream — check event-generation code.`
    );
    return 'unavailable';
  }
  return `${rawKm.toFixed(1)} km radius`;
}

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: 'bg-rose-100 text-rose-700',
  HIGH: 'bg-amber-100 text-amber-700',
  MODERATE: 'bg-blue-100 text-blue-700',
  ADVISORY: 'bg-emerald-100 text-emerald-700',
  critical: 'bg-rose-100 text-rose-700',
  high: 'bg-amber-100 text-amber-700',
  moderate: 'bg-blue-100 text-blue-700',
  low: 'bg-emerald-100 text-emerald-700',
};

const REVIEW_BADGE: Record<string, { label: string; cls: string }> = {
  AUTO_PUBLISHED: { label: 'Auto-Published', cls: 'bg-emerald-50 text-emerald-700' },
  PENDING_HUMAN_REVIEW: { label: 'Pending Review', cls: 'bg-amber-50 text-amber-700' },
  QUARANTINED: { label: 'Quarantined', cls: 'bg-red-50 text-red-700' },
  HUMAN_APPROVED: { label: 'Approved', cls: 'bg-emerald-50 text-emerald-700' },
  REJECTED: { label: 'Rejected', cls: 'bg-slate-100 text-slate-500' },
};

// The API names ADVISORY "low" in the list (SEVERITY_LABELS in events.py), so
// comparing the button's name to the field upper-cased meant ADVISORY could
// never match a single event.
const SEVERITY_KEY: Record<string, string> = {
  critical: 'CRITICAL',
  high: 'HIGH',
  moderate: 'MODERATE',
  low: 'ADVISORY',
  advisory: 'ADVISORY',
};
const severityKey = (sev: string) => SEVERITY_KEY[sev.toLowerCase()] ?? sev.toUpperCase();

type RangeKey = '24h' | '7d' | '30d' | 'all';
const RANGES: Array<{ key: RangeKey; label: string; long: string }> = [
  { key: '24h', label: '24H', long: 'the last 24 hours' },
  { key: '7d', label: '7D', long: 'the last 7 days' },
  { key: '30d', label: '30D', long: 'the last 30 days' },
  { key: 'all', label: 'ALL', long: 'the record' },
];

/** The IST calendar date N days ago, as the API's from= expects. */
function istDateDaysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86_400_000);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(d);
}

function rangeParams(range: RangeKey) {
  if (range === '24h' || range === '7d') return { time_range: range, limit: 200 };
  if (range === '30d') return { from: istDateDaysAgo(30), limit: 200 };
  return { limit: 200 };
}

function getRelativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ${mins % 60}m ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function EventsPage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [search, setSearch] = useState('');
  const [range, setRange] = useState<RangeKey>('7d');
  const [events, setEvents] = useState<ApiEvent[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed request used to be swallowed ("fallback already handled"), and
  // the page then said "No events match the current filters" about a backend
  // it could not reach.
  const [loadError, setLoadError] = useState<unknown>(null);
  const [warningsInForce, setWarningsInForce] = useState<number | null>(null);
  const [verificationEventId, setVerificationEventId] = useState<string | null>(null);
  const { subscribe } = useIndraWebSocket();

  const loadEvents = useCallback(async () => {
    try {
      const data = await fetchEvents(rangeParams(range));
      setEvents(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err);
    }
    setLoading(false);
  }, [range]);

  useEffect(() => {
    setLoading(true);
    loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    fetchSummaryCounts()
      .then((s) => setWarningsInForce(s.active_alerts))
      .catch(() => setWarningsInForce(null));
  }, []);

  // Refresh on WebSocket events
  useEffect(() => {
    return subscribe('events-page', (msg) => {
      if (['VERIFIED_EVENT', 'EVENT_REVIEWED', 'NEW_REPORT'].includes(msg.type)) {
        loadEvents();
      }
    });
  }, [subscribe, loadEvents]);

  const filtered = events.filter((ev) => {
    if (filterSeverity !== 'ALL' && severityKey(ev.severity) !== filterSeverity) return false;
    if (search) {
      const q = search.toLowerCase();
      // city and state are null when the backend could not place the point
      // (BUG-033 made that honest); such an event can still match on its
      // type or code.
      if (
        !(ev.city ?? '').toLowerCase().includes(q) &&
        !(ev.state ?? '').toLowerCase().includes(q) &&
        !ev.eventType.toLowerCase().includes(q) &&
        !ev.event_code.toLowerCase().includes(q)
      ) return false;
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
          sidebarCollapsed ? 'md:ml-[68px]' : 'md:ml-[272px]'
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
                  {t('nav.incident_events').toUpperCase()}
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {events.length} {t('chart.events').toUpperCase()} · {RANGES.find((r) => r.key === range)?.label}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                {t('dashboard.welcome_subtitle')}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700 text-xs">
                <Radio className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
                <span className="text-slate-300 font-mono">{t('nav.telemetry_live').toUpperCase()}</span>
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
                placeholder={t('nav.search_placeholder')}
                className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 shadow-sm"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto">
              <div className="flex items-center gap-0.5 p-0.5 mr-1 rounded-xl bg-slate-100 border border-slate-200" role="group" aria-label="Time range">
                {RANGES.map((r) => (
                  <button
                    key={r.key}
                    onClick={() => setRange(r.key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold transition-all ${
                      range === r.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              {['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'ADVISORY'].map((sev) => (
                <button
                  key={sev}
                  onClick={() => setFilterSeverity(sev)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                    filterSeverity === sev
                      ? 'bg-slate-900 text-white shadow-sm'
                      : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  {sev === 'ALL' ? t('common.view_all') : t.severity(sev)}
                </button>
              ))}
            </div>
          </div>

          {/* Loading / Empty */}
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
              <span className="ml-2 text-sm text-slate-500">{t('common.loading')}</span>
            </div>
          ) : loadError ? (
            <div className="bg-white rounded-2xl border border-slate-200">
              <ErrorState label="events" error={loadError} onRetry={() => { setLoading(true); loadEvents(); }} />
            </div>
          ) : events.length === 0 ? (
            <div className="text-center py-16 px-4 bg-white rounded-2xl border border-slate-200">
              <p className="text-sm font-medium text-slate-700">
                No INDRA events in {RANGES.find((r) => r.key === range)?.long}
              </p>
              <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
                An event forms when at least two reports close together in place and time corroborate
                each other. A single report waits on Field Reports until a second one arrives.
              </p>
              <div className="flex items-center justify-center gap-2 mt-4 flex-wrap">
                <Link href="/alerts" className="px-3 py-1.5 rounded-xl text-xs font-medium bg-slate-900 text-white hover:bg-slate-800">
                  Early Warnings{warningsInForce != null ? ` · ${warningsInForce} in force` : ''}
                </Link>
                <Link href="/reports" className="px-3 py-1.5 rounded-xl text-xs font-medium bg-white text-slate-700 border border-slate-200 hover:bg-slate-50">
                  Field Reports
                </Link>
                {range !== 'all' && (
                  <button onClick={() => setRange('all')} className="px-3 py-1.5 rounded-xl text-xs font-medium bg-white text-slate-700 border border-slate-200 hover:bg-slate-50">
                    Show the whole record
                  </button>
                )}
              </div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-24 text-slate-400 text-sm">
              No events match the current filters.
            </div>
          ) : (
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="visible"
              className="grid grid-cols-1 md:grid-cols-2 gap-4"
            >
              {filtered.map((ev) => {
                const sevBadge = SEVERITY_BADGE[ev.severity] || SEVERITY_BADGE.moderate;
                // The API's review_status and quadrant, derived only when absent (BUG-070).
                const eventState = safeEventState(ev.id, ev.severity, ev.confidence_score, ev.review_status, ev.quadrant);
                const reviewBadge = REVIEW_BADGE[eventState.reviewStatus] || REVIEW_BADGE.PENDING_HUMAN_REVIEW;
                return (
                  <motion.div
                    key={ev.id}
                    variants={fadeIn}
                    className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                    onClick={() => setVerificationEventId(ev.id)}
                  >
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono text-[11px] text-slate-400">
                            {ev.event_code}
                          </span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${sevBadge}`}>
                            {t.severity(ev.severity)}
                          </span>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${reviewBadge.cls}`}>
                            {t.status(eventState.reviewStatus)}
                          </span>
                        </div>
                        <h3 className="font-semibold text-slate-900 text-base">
                          {t.hazard(ev.eventType)} — {formatPlace(ev.city, ev.state, ev.place_precision)}
                        </h3>
                        {eventState.quadrant && (
                          <p className="text-[11px] text-slate-500 mt-0.5">{eventState.quadrant}</p>
                        )}
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="text-lg font-bold font-mono text-[#B5482E]">{Math.round(ev.confidence_score * 100)}%</div>
                        <div className="text-[10px] text-slate-400">{t('receipt.confidence_label')}</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 mb-4 bg-slate-50 p-3 rounded-xl">
                      <div className="flex items-center gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-slate-400" />
                        <span>{formatPlace(ev.city, ev.state, ev.place_precision)}</span>
                      </div>
                      <div className="flex items-center gap-1.5 font-mono text-[11px]">
                        <Clock className="w-3.5 h-3.5 text-slate-400" />
                        <span>{getRelativeTime(ev.timestamp || ev.verified_at)}</span>
                      </div>
                      <div className="flex items-center gap-1.5 col-span-2">
                        <Shield className="w-3.5 h-3.5 text-blue-600" />
                        <span className="font-medium text-slate-800">
                          {/* Issue 3 fix: clamp impact_radius_km to per-hazard ceiling; show "unavailable" if it exceeds it */}
                          Impact: {clampImpactRadius(ev.id, ev.eventType, ev.impact_radius_km)}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <Shield className="w-3 h-3" /> Click for full verification receipt
                      </span>
                      <Link
                        href="/live-map"
                        onClick={(e) => e.stopPropagation()}
                        className="text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
                      >
                        View on 3D Globe <ExternalLink className="w-3 h-3" />
                      </Link>
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </main>

        {/* Verification Modal */}
        <EventVerificationModal
          eventId={verificationEventId}
          onClose={() => setVerificationEventId(null)}
          onEventUpdated={() => loadEvents()}
        />
      </div>
    </div>
  );
}
