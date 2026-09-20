'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bell,
  AlertOctagon,
  AlertTriangle,
  Info,
  ShieldAlert,
  Radio,
  ExternalLink,
  MapPin,
  Clock,
  ChevronRight,
  Search,
  Loader2,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import EventVerificationModal from '@/components/EventVerificationModal';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchEvents, type ApiEvent } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';

interface UnifiedAlert {
  id: string;
  eventId?: string;
  level: 'RED' | 'ORANGE' | 'YELLOW';
  title: string;
  agency: string;
  issuedAt: string;
  validUntil: string;
  zones: string[];
  description: string;
  actionRequired: string;
  confidenceScore?: number;
  reportCount?: number;
  isLiveEvent?: boolean;
}

const OFFICIAL_BULLETINS: UnifiedAlert[] = [
  {
    id: 'ALT-IMD-2026-901',
    level: 'RED',
    title: 'RED WARNING: Severe Atmospheric Flash Flood & Cloudburst Potential',
    agency: 'IMD Eastern Regional Centre',
    issuedAt: '12 mins ago',
    validUntil: '15 Sep 2026, 06:00 IST',
    zones: ['Patna', 'Vaishali', 'Muzaffarpur', 'Samastipur'],
    description:
      'Continuous hyper-localized precipitation exceeding 120mm/hr detected by Doppler radar. Extreme inundation imminent in low-lying river catchments.',
    actionRequired: 'Immediate evacuation of floodplains and deployment of NDRF quick-response teams.',
  },
  {
    id: 'ALT-IMD-2026-902',
    level: 'RED',
    title: 'CYCLONIC STORM WARNING: Cyclone "Marut" Coastal Landfall Advisory',
    agency: 'Cyclone Warning Division, New Delhi',
    issuedAt: '45 mins ago',
    validUntil: '15 Sep 2026, 18:00 IST',
    zones: ['Puri', 'Jagatsinghpur', 'Kendrapara', 'Bhadrak'],
    description:
      'Very Severe Cyclonic Storm with sustained winds 130-150 km/h gusting to 165 km/h. Tidal surge up to 2.5m anticipated during high tide.',
    actionRequired: 'Port signal 8 hoisted. Fishermen advised total suspension of fishing operations.',
  },
  {
    id: 'ALT-IMD-2026-903',
    level: 'ORANGE',
    title: 'ORANGE ALERT: Landslide & Hill Slope Debris Discharge',
    agency: 'Geological Survey of India & IMD Trivandrum',
    issuedAt: '2h ago',
    validUntil: '15 Sep 2026, 12:00 IST',
    zones: ['Wayanad', 'Idukki', 'Kozhikode Ghats'],
    description:
      'Soil moisture saturation index at 98.4%. High susceptibility to slope slips along NH-766.',
    actionRequired: 'Night travel prohibited on ghat roads. NDRF team pre-positioned at Meppadi.',
  },
  {
    id: 'ALT-IMD-2026-904',
    level: 'ORANGE',
    title: 'ORANGE ALERT: Upper Yamuna River Water Discharge Advisory',
    agency: 'Central Water Commission (CWC)',
    issuedAt: '3h ago',
    validUntil: '16 Sep 2026, 00:00 IST',
    zones: ['Hathnikund to Delhi Lowlands'],
    description:
      'Hathnikund barrage released 2,85,000 cusecs water upstream. Water levels expected to breach danger mark (205.33m) by tomorrow dawn.',
    actionRequired: 'Relocation of cattle and riverside settlements in Shahdara & Mayur Vihar.',
  },
];

function getRelativeTimeString(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ${mins % 60}m ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function getDirectiveForEvent(type: string, severity: string): string {
  const t = (type || '').toLowerCase();
  if (t.includes('flood') || t.includes('waterlog')) {
    return severity.toUpperCase() === 'CRITICAL'
      ? 'Execute Stage-3 flood evacuation protocols. Dispatch SDRF rescue boats and establish relief shelters in elevated zones.'
      : 'Issue high-water advisories; restrict vehicular movement along underpasses and river banks.';
  }
  if (t.includes('cyclone') || t.includes('wind') || t.includes('storm')) {
    return 'Suspend coastal and maritime operations. Issue CAP alert to district sirens; secure critical power installations.';
  }
  if (t.includes('landslide')) {
    return 'Enforce total vehicular stoppage along vulnerable ghat corridors. Pre-position heavy earthmoving machinery.';
  }
  return 'Mobilize local disaster response units. Maintain active Doppler radar feed and cross-verify civilian reports.';
}

export default function AlertsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [selectedLevel, setSelectedLevel] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [events, setEvents] = useState<ApiEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [verificationEventId, setVerificationEventId] = useState<string | null>(null);
  const { subscribe } = useIndraWebSocket();

  const loadAlertsData = useCallback(async () => {
    try {
      const data = await fetchEvents({ time_range: '7d' });
      setEvents(data);
    } catch {
      // fallback
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadAlertsData();
  }, [loadAlertsData]);

  // Real-time WebSocket updates
  useEffect(() => {
    return subscribe('alerts-page', (msg) => {
      if (['VERIFIED_EVENT', 'EVENT_REVIEWED', 'NEW_REPORT'].includes(msg.type)) {
        loadAlertsData();
      }
    });
  }, [subscribe, loadAlertsData]);

  // Synthesize alerts from live backend events + official bulletins
  const allAlerts = useMemo<UnifiedAlert[]>(() => {
    const liveAlerts: UnifiedAlert[] = [];

    // Filter events that qualify for emergency alerts (CRITICAL or HIGH)
    const severeEvents = events.filter((ev) => {
      const s = (ev.severity || '').toUpperCase();
      return s === 'CRITICAL' || s === 'HIGH';
    });

    for (const ev of severeEvents) {
      const isCritical = ev.severity.toUpperCase() === 'CRITICAL';
      liveAlerts.push({
        id: ev.event_code || `EV-${ev.id.slice(0, 8)}`,
        eventId: ev.id,
        level: isCritical ? 'RED' : 'ORANGE',
        title: `${isCritical ? 'CRITICAL WARNING' : 'HIGH ADVISORY'}: ${ev.eventType} in ${ev.city}`,
        agency: `NDMA • ${ev.state} Emergency Operation Centre`,
        issuedAt: getRelativeTimeString(ev.timestamp),
        validUntil: 'Active Incident Response',
        zones: [ev.city, ev.state, `${ev.impact_radius_km} km radius`],
        description: `Verified ${ev.eventType.toLowerCase()} anomaly corroborated by ${
          ev.corroborating_reports_count || 1
        } sensor/citizen reports with ${Math.round(ev.confidence_score * 100)}% algorithmic confidence. Coordinates: ${(ev.lat ?? 0).toFixed(3)}°N, ${(ev.lng ?? 0).toFixed(3)}°E.`,
        actionRequired: getDirectiveForEvent(ev.eventType, ev.severity),
        confidenceScore: ev.confidence_score,
        reportCount: ev.corroborating_reports_count,
        isLiveEvent: true,
      });
    }

    // Merge live alerts first, followed by official meteorological bulletins
    return [...liveAlerts, ...OFFICIAL_BULLETINS];
  }, [events]);

  const filteredAlerts = allAlerts.filter((alt) => {
    if (selectedLevel !== 'ALL' && alt.level !== selectedLevel) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchTitle = alt.title.toLowerCase().includes(q);
      const matchDesc = alt.description.toLowerCase().includes(q);
      const matchZones = alt.zones.some((z) => z.toLowerCase().includes(q));
      if (!matchTitle && !matchDesc && !matchZones) return false;
    }
    return true;
  });

  const redCount = allAlerts.filter((a) => a.level === 'RED').length;
  const orangeCount = allAlerts.filter((a) => a.level === 'ORANGE').length;

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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Executive Header Banner */}
          <div className="bg-gradient-to-r from-[#8C2F26] via-[#73241C] to-[#1B2432] text-white p-5 rounded-2xl border border-[#B5482E]/30 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                <ShieldAlert className="w-5 h-5 text-rose-300 animate-pulse" />
                <h1
                  className="text-xl font-bold tracking-wide"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  Early Warning &amp; Hazard Bulletins
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-200 border border-rose-400/40 animate-pulse">
                  {redCount} CRITICAL WARNINGS
                </span>
                {orangeCount > 0 && (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-200 border border-amber-400/40">
                    {orangeCount} ADVISORIES
                  </span>
                )}
              </div>
              <p className="text-xs text-rose-100/80">
                Official NDMA, IMD, CWC broadcasts synchronized with real-time INDRA 6-factor verified anomaly telemetry.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-black/30 backdrop-blur-md border border-rose-400/30 text-xs font-mono text-rose-200">
                <span className="w-2 h-2 rounded-full bg-rose-400 animate-ping" />
                CAP-INDIA BROADCAST ONLINE
              </div>
              <button
                onClick={() => {
                  setLoading(true);
                  loadAlertsData();
                }}
                disabled={loading}
                className="p-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Refresh alerts"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Controls: Filter Pills & Search */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              {[
                { id: 'ALL', label: `ALL BULLETINS (${allAlerts.length})` },
                { id: 'RED', label: `🔴 RED WARNINGS (${redCount})` },
                { id: 'ORANGE', label: `🟠 ORANGE ALERTS (${orangeCount})` },
              ].map((lvl) => (
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
                placeholder="Filter by city, state, or hazard..."
                className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-white border border-[#E8E2D4] text-xs text-[#1B2432] placeholder-[#A0988A] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 transition-all shadow-2xs"
              />
            </div>
          </div>

          {/* Alerts Cards List */}
          {loading && allAlerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 bg-white rounded-2xl border border-[#E8E2D4]">
              <Loader2 className="w-8 h-8 text-[#B5482E] animate-spin mb-3" />
              <p className="text-sm font-medium text-[#7A8599]">Synchronizing alert telemetry with backend...</p>
            </div>
          ) : filteredAlerts.length === 0 ? (
            <div className="p-8 text-center bg-white rounded-2xl border border-[#E8E2D4] text-[#7A8599] text-sm">
              No hazard bulletins found matching your filter criteria.
            </div>
          ) : (
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="visible"
              className="space-y-4"
            >
              {filteredAlerts.map((alt) => {
                const isRed = alt.level === 'RED';

                return (
                  <motion.div
                    key={alt.id}
                    variants={fadeIn}
                    className={`rounded-2xl border p-5 shadow-xs bg-white transition-all ${
                      isRed
                        ? 'border-rose-200 hover:border-rose-300 hover:shadow-md'
                        : 'border-amber-200 hover:border-amber-300 hover:shadow-md'
                    }`}
                    style={{
                      borderLeft: isRed ? '5px solid #8C2F26' : '5px solid #B8873A',
                    }}
                  >
                    {/* Card Top Strip */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span
                          className={`text-xs font-black font-mono px-2.5 py-0.5 rounded-md ${
                            isRed
                              ? 'bg-rose-600 text-white'
                              : 'bg-amber-500 text-slate-950 font-bold'
                          }`}
                        >
                          {alt.level} ALERT
                        </span>
                        <span className="font-mono text-xs text-[#7A8599] font-medium">
                          {alt.id}
                        </span>
                        <span className="text-xs text-[#7A8599]">
                          • {alt.agency}
                        </span>
                        {alt.isLiveEvent && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            Live Telemetry Event
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2 text-xs font-mono text-[#7A8599]">
                        <Clock className="w-3.5 h-3.5 text-[#A0988A]" />
                        <span>Issued {alt.issuedAt}</span>
                        <span>• Valid: {alt.validUntil}</span>
                      </div>
                    </div>

                    {/* Headline */}
                    <h2
                      className="text-base font-bold text-[#1B2432] mb-2 leading-snug"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      {alt.title}
                    </h2>

                    {/* Description */}
                    <p className="text-xs sm:text-sm text-[#4A5568] mb-3.5 leading-relaxed">
                      {alt.description}
                    </p>

                    {/* Impacted Districts */}
                    <div className="flex flex-wrap items-center gap-1.5 mb-3.5">
                      <span className="text-xs font-semibold text-[#1B2432]">
                        Impacted Districts:
                      </span>
                      {alt.zones.map((zone) => (
                        <span
                          key={zone}
                          className="text-xs font-mono bg-[#F7F3EA] text-[#4A5568] px-2.5 py-0.5 rounded-md border border-[#E8E2D4]"
                        >
                          {zone}
                        </span>
                      ))}
                    </div>

                    {/* Operational Directive Box */}
                    <div
                      className={`rounded-xl p-3 text-xs flex items-start gap-2.5 mb-3 ${
                        isRed
                          ? 'bg-rose-50/70 border border-rose-200 text-rose-950'
                          : 'bg-amber-50/70 border border-amber-200 text-amber-950'
                      }`}
                    >
                      <AlertOctagon
                        className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
                          isRed ? 'text-rose-600' : 'text-amber-600'
                        }`}
                      />
                      <div className="leading-relaxed">
                        <span className="font-bold">Required Operational Directive: </span>
                        {alt.actionRequired}
                      </div>
                    </div>

                    {/* Action Bar */}
                    {alt.eventId && (
                      <div className="pt-2 border-t border-[#F0EBE0] flex items-center justify-between">
                        <span className="text-[11px] font-mono text-[#7A8599]">
                          Corroborated by {alt.reportCount || 1} reports • Confidence {Math.round((alt.confidenceScore || 0) * 100)}%
                        </span>
                        <button
                          onClick={() => setVerificationEventId(alt.eventId!)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#F7F3EA] hover:bg-[#F0EBE0] text-[#1B2432] text-xs font-medium border border-[#E8E2D4] transition-colors"
                        >
                          <ShieldCheck className="w-3.5 h-3.5 text-[#B5482E]" />
                          Inspect Verification Receipt
                          <ChevronRight className="w-3.5 h-3.5 text-[#A0988A]" />
                        </button>
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </main>
      </div>

      {/* Verification Receipt Modal */}
      <EventVerificationModal
        eventId={verificationEventId}
        onClose={() => setVerificationEventId(null)}
        onEventUpdated={() => loadAlertsData()}
      />
    </div>
  );
}
