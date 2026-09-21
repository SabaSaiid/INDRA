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
import { fetchEvents, type ApiEvent } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';

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
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [search, setSearch] = useState('');
  const [events, setEvents] = useState<ApiEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [verificationEventId, setVerificationEventId] = useState<string | null>(null);
  const { subscribe } = useIndraWebSocket();

  const loadEvents = useCallback(async () => {
    try {
      const data = await fetchEvents({ time_range: '7d' });
      setEvents(data);
    } catch { /* fallback already handled in fetchEvents */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadEvents(); }, [loadEvents]);

  // Refresh on WebSocket events
  useEffect(() => {
    return subscribe('events-page', (msg) => {
      if (['VERIFIED_EVENT', 'EVENT_REVIEWED', 'NEW_REPORT'].includes(msg.type)) {
        loadEvents();
      }
    });
  }, [subscribe, loadEvents]);

  const filtered = events.filter((ev) => {
    if (filterSeverity !== 'ALL' && ev.severity.toUpperCase() !== filterSeverity) return false;
    if (search) {
      const q = search.toLowerCase();
      if (
        !ev.city.toLowerCase().includes(q) &&
        !ev.state.toLowerCase().includes(q) &&
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
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
                  {events.length} ACTIVE
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Live multi-source meteorological incident tracking and disaster response coordination.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700 text-xs">
                <Radio className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
                <span className="text-slate-300 font-mono">LIVE API SYNCED</span>
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
                placeholder="Filter by city, event type, or event code..."
                className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 shadow-sm"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto">
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
                  {sev}
                </button>
              ))}
            </div>
          </div>

          {/* Loading / Empty */}
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
              <span className="ml-2 text-sm text-slate-500">Loading events from backend…</span>
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
                const reviewBadge = REVIEW_BADGE[ev.review_status] || REVIEW_BADGE.QUARANTINED;
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
                            {ev.severity.toUpperCase()}
                          </span>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${reviewBadge.cls}`}>
                            {reviewBadge.label}
                          </span>
                        </div>
                        <h3 className="font-semibold text-slate-900 text-base">
                          {ev.eventType} — {ev.quadrant || `${ev.city} Sector`}
                        </h3>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="text-lg font-bold font-mono text-[#B5482E]">{Math.round(ev.confidence_score * 100)}%</div>
                        <div className="text-[10px] text-slate-400">confidence</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 mb-4 bg-slate-50 p-3 rounded-xl">
                      <div className="flex items-center gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-slate-400" />
                        <span>{ev.city}, {ev.state}</span>
                      </div>
                      <div className="flex items-center gap-1.5 font-mono text-[11px]">
                        <Clock className="w-3.5 h-3.5 text-slate-400" />
                        <span>{getRelativeTime(ev.timestamp || ev.verified_at)}</span>
                      </div>
                      <div className="flex items-center gap-1.5 col-span-2">
                        <Shield className="w-3.5 h-3.5 text-blue-600" />
                        <span className="font-medium text-slate-800">
                          Impact: {ev.impact_radius_km?.toFixed(1) || '—'} km radius
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <Shield className="w-3 h-3" /> Click for full verification receipt
                      </span>
                      <a
                        href="/live-map"
                        onClick={(e) => e.stopPropagation()}
                        className="text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
                      >
                        View on 3D Globe <ExternalLink className="w-3 h-3" />
                      </a>
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
