'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import WelcomeHeader, { type ViewMode } from '@/components/WelcomeHeader';
import KpiCard from '@/components/KpiCard';
import EventMap from '@/components/EventMap';
import RecentEventsList from '@/components/RecentEventsList';
import EventDistributionChart from '@/components/EventDistributionChart';
import ReportsTrendChart from '@/components/ReportsTrendChart';
import LiveFeed from '@/components/LiveFeed';
import { type KpiItem, type RecentEvent } from '@/lib/ui-config';
import { fetchDashboardSummary, fetchEvents, apiEventsToRecentEvents } from '@/lib/api';
import { ErrorState } from '@/components/ui/empty-state';
import EventVerificationModal from '@/components/EventVerificationModal';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { useTranslation } from '@/lib/i18n/useTranslation';
import {
  KpiCardSkeleton,
  MapCardSkeleton,
  ListCardSkeleton,
  ChartCardSkeleton,
} from '@/components/ui/skeleton';
import { useSidebar } from '@/lib/useSidebar';

// The dashboard map's canvas fills what the viewport leaves after the topbar,
// the status strip, the KPI row, the map's own header and the chart row
// (≈490 px together, measured), so the page ends at the bottom of the screen
// instead of leaving a band of empty paper under the charts. Clamped for short
// and very tall screens.
const DASHBOARD_MAP_HEIGHT = 'h-[clamp(340px,calc(100dvh-490px),680px)]';
const MAP_FOCUS_HEIGHT = 'h-[clamp(420px,calc(100dvh-330px),860px)]';

export default function Home() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  // No seeded values: an empty dashboard that fills as reports arrive is the
  // honest state. Seeding with invented KPIs showed confident numbers before a
  // single request had returned.
  const [liveKpiData, setLiveKpiData] = useState<KpiItem[]>([]);
  const [kpiError, setKpiError] = useState<unknown>(null);
  const [eventsError, setEventsError] = useState<unknown>(null);
  const [events, setEvents] = useState<RecentEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(undefined);
  const [verificationEventId, setVerificationEventId] = useState<string | null>(null);
  const { subscribe } = useIndraWebSocket();
  const { t, language } = useTranslation();

  // KPI label map: id → translation key in kpis namespace
  const KPI_LABEL_MAP: Record<string, string> = {
    'total-reports': t('kpis.total_reports'),
    'verified-events': t('kpis.verified_events'),
    'critical-events': t('kpis.critical_events'),
    'citizen-reports': t('kpis.citizen_reports'),
    'awaiting-review': t('kpis.awaiting_review'),
    'active-alerts': t('kpis.active_alerts'),
  };
  const KPI_DELTA_MAP: Record<string, string> = {
    'total-reports': t('kpis.delta_last_24h'),
    'verified-events': t('kpis.delta_last_24h'),
    'critical-events': t('kpis.delta_last_24h'),
    'citizen-reports': t('kpis.delta_last_24h'),
    'awaiting-review': t('kpis.delta_review_queue'),
    'active-alerts': t('kpis.delta_in_force'),
  };

  // ── View Mode (persisted across sessions) ──────────────────────────────────
  const [viewMode, setViewMode] = useState<ViewMode>('mission-control');

  useEffect(() => {
    try {
      const saved = localStorage.getItem('indra_view_mode') as ViewMode | null;
      if (saved && ['mission-control', 'map-focus', 'analytics-focus'].includes(saved)) {
        setViewMode(saved);
      }
    } catch { /* ignore */ }
  }, []);

  const handleViewModeChange = useCallback((mode: ViewMode) => {
    setViewMode(mode);
  }, []);

  // ── Live KPI and Event Data ───────────────────────────────────────────────
  // refreshTick is bumped by the WebSocket below. Without it this page fetched
  // once on mount and never again, so a console labelled "Grid live" sat on a
  // snapshot until someone reloaded it by hand (BUG-036).
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [kpiResult, apiEvents] = await Promise.allSettled([
          fetchDashboardSummary(),
          fetchEvents({ time_range: '7d' }),
        ]);

        if (!cancelled) {
          if (kpiResult.status === 'fulfilled') {
            // Override labels with the current language using the translation map
            const localized = kpiResult.value.map((kpi) => ({
              ...kpi,
              label: KPI_LABEL_MAP[kpi.id] ?? kpi.label,
              deltaLabel: KPI_DELTA_MAP[kpi.id] ?? kpi.deltaLabel,
            }));
            setLiveKpiData(localized);
            setKpiError(null);
          } else {
            setKpiError(kpiResult.reason);
          }
          // An empty list is a result, not a failure: zero verified events means
          // zero verified events.
          if (apiEvents.status === 'fulfilled') {
            setEvents(apiEventsToRecentEvents(apiEvents.value));
            setEventsError(null);
          } else {
            setEventsError(apiEvents.reason);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setKpiError(err);
          setEventsError(err);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          setEventsLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [refreshTick, language]); // re-fetch labels when language changes

  // The backend has broadcast VERIFIED_EVENT since Day 1 and nothing in the
  // frontend ever listened for it. NEW_REPORT moves the report counters, and
  // VERIFIED_EVENT / EVENT_REVIEWED are the moments the KPI strip and the event
  // list are certainly stale, so each triggers one refetch of both. This page
  // also opened a raw socket of its own beside the shared one; it now listens
  // on the shared connection only.
  useEffect(() => {
    return subscribe('dashboard-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        setRefreshTick((t) => t + 1);
      }
    });
  }, [subscribe]);

  const refreshEvents = useCallback(() => setRefreshTick((t) => t + 1), []);

  // Handler to open verification modal from event lists
  const handleEventSelect = useCallback((ev: RecentEvent) => {
    setSelectedIncidentId(ev.id);
    setVerificationEventId(ev.id);
  }, []);

  return (
    <div className="min-h-screen bg-paper">
      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileMenuOpen}
        onMobileClose={closeMobile}
      />

      {/* Main content area */}
      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed
            ? 'md:ml-[68px]'
            : 'md:ml-[272px]'
        }`}
      >
        {/* Topbar — compact 50px */}
        <Topbar onMobileMenuOpen={openMobile} />

        {/* Dashboard content — viewport-fit wrapper */}
        <main className="p-3 lg:p-4 max-w-[1600px] mx-auto">
          <AnimatePresence mode="wait">
            {isLoading ? (
              <motion.div
                key="skeleton"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
              >
                {/* Skeleton header strip */}
                <div className="h-9 mb-2.5" />

                {/* Skeleton KPIs */}
                <KpiCardSkeleton />

                {/* Skeleton map + list */}
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-2.5 mb-2.5">
                  <div className="lg:col-span-3"><MapCardSkeleton /></div>
                  <div className="lg:col-span-2 flex flex-col"><ListCardSkeleton /></div>
                </div>

                {/* Skeleton bottom row */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                  <ChartCardSkeleton />
                  <ChartCardSkeleton />
                  <ChartCardSkeleton />
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="content"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4 }}
              >
                {/* Executive Status Strip — replaces tall WelcomeHeader */}
                <WelcomeHeader
                  viewMode={viewMode}
                  onViewModeChange={handleViewModeChange}
                />

                {/* Instrument Strip — 4-reading compact KPI bar */}
                <div className="instrument-strip">
                  {kpiError ? (
                    <ErrorState
                      label="dashboard totals"
                      error={kpiError}
                      compact
                      className="col-span-full"
                    />
                  ) : (
                    liveKpiData.map((item, index) => (
                      <KpiCard
                        key={item.id}
                        item={{
                          ...item,
                          label: KPI_LABEL_MAP[item.id] ?? item.label,
                          deltaLabel: KPI_DELTA_MAP[item.id] ?? item.deltaLabel,
                        }}
                        index={index}
                      />
                    ))
                  )}
                </div>

                {/*
                 * ── Adaptive Grid Layout by View Mode ─────────────────────
                 * mission-control: map (3/5) + events (2/5) + charts row
                 * map-focus:       map fullwidth, events row, charts row
                 * analytics-focus: thin event list + expanded charts area
                 */}
                {viewMode === 'mission-control' && (
                  <>
                    {/* Map + Recent Events */}
                    <div className="grid grid-cols-1 lg:grid-cols-5 gap-2.5 mb-2.5">
                      <div className="lg:col-span-3">
                        <EventMap
                          selectedEventId={selectedIncidentId}
                          onEventSelect={(ev) => setSelectedIncidentId(ev?.id)}
                          canvasClassName={DASHBOARD_MAP_HEIGHT}
                        />
                      </div>
                      {/* The map sets the row's height and the list scrolls
                          inside it: absolutely filling the column (lg and up)
                          keeps a long list from stretching the map card and
                          leaving empty space under the canvas. */}
                      <div className="lg:col-span-2 flex flex-col lg:relative">
                        <div className="flex flex-col h-full lg:absolute lg:inset-0">
                          <RecentEventsList
                            selectedEventId={selectedIncidentId}
                            onSelectEvent={handleEventSelect}
                            events={events}
                            loading={eventsLoading}
                            error={eventsError}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Bottom Row: Distribution + Trend + Live Feed */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                      <EventDistributionChart />
                      <ReportsTrendChart />
                      <LiveFeed />
                    </div>
                  </>
                )}

                {viewMode === 'map-focus' && (
                  <>
                    {/* Full-width map */}
                    <div className="mb-2.5">
                      <EventMap
                        selectedEventId={selectedIncidentId}
                        onEventSelect={(ev) => setSelectedIncidentId(ev?.id)}
                        canvasClassName={MAP_FOCUS_HEIGHT}
                      />
                    </div>
                    {/* Events + Feed side by side below map */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      <RecentEventsList
                        selectedEventId={selectedIncidentId}
                        onSelectEvent={handleEventSelect}
                        events={events}
                        loading={eventsLoading}
                        error={eventsError}
                      />
                      <LiveFeed />
                    </div>
                  </>
                )}

                {viewMode === 'analytics-focus' && (
                  <div className="grid grid-cols-1 lg:grid-cols-5 gap-2.5">
                    {/* Narrow events list */}
                    <div className="lg:col-span-2 flex flex-col h-full">
                      <RecentEventsList
                        selectedEventId={selectedIncidentId}
                        onSelectEvent={handleEventSelect}
                        events={events}
                        loading={eventsLoading}
                        error={eventsError}
                      />
                    </div>
                    {/* Wide analytics area */}
                    <div className="lg:col-span-3 flex flex-col gap-2.5">
                      <EventDistributionChart />
                      <ReportsTrendChart />
                      <LiveFeed />
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* Verification Receipt Modal */}
        <EventVerificationModal
          eventId={verificationEventId}
          onClose={() => setVerificationEventId(null)}
          onEventUpdated={() => refreshEvents()}
        />
      </div>
    </div>
  );
}
