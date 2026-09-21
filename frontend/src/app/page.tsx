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
import {
  KpiCardSkeleton,
  MapCardSkeleton,
  ListCardSkeleton,
  ChartCardSkeleton,
} from '@/components/ui/skeleton';
import { useSidebar } from '@/lib/useSidebar';

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
            setLiveKpiData(kpiResult.value);
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
  }, []);

  // ── WebSocket: auto-refresh events on real-time broadcasts ────────────────
  const refreshEvents = useCallback(async () => {
    try {
      const apiEvents = await fetchEvents({ time_range: '7d' });
      if (apiEvents.length > 0) {
        setEvents(apiEventsToRecentEvents(apiEvents));
      }
    } catch { /* no-op */ }
  }, []);

  useEffect(() => {
    return subscribe('dashboard-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        refreshEvents();
        // Also refresh KPIs on verified/reviewed events
        if (msg.type !== 'NEW_REPORT') {
          fetchDashboardSummary().then(setLiveKpiData);
        }
      }
    });
  }, [subscribe, refreshEvents]);

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
            ? 'md:ml-[72px]'
            : 'md:ml-[280px]'
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
                      <KpiCard key={item.id} item={item} index={index} />
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
                        />
                      </div>
                      <div className="lg:col-span-2 flex flex-col">
                        <RecentEventsList
                          selectedEventId={selectedIncidentId}
                          onSelectEvent={handleEventSelect}
                          events={events}
                          loading={eventsLoading}
                          error={eventsError}
                        />
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
