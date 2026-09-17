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
import { kpiData, type KpiItem } from '@/lib/mock-data';
import { fetchDashboardSummary } from '@/lib/api';
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
  const [liveKpiData, setLiveKpiData] = useState<KpiItem[]>(kpiData);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(undefined);

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

  // ── Live KPI data ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchDashboardSummary();
        if (!cancelled) setLiveKpiData(data);
      } catch {
        // mock data already set
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
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
                  <div className="lg:col-span-2"><ListCardSkeleton /></div>
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
                  {liveKpiData.map((item, index) => (
                    <KpiCard key={item.id} item={item} index={index} />
                  ))}
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
                      <div className="lg:col-span-2">
                        <RecentEventsList
                          selectedEventId={selectedIncidentId}
                          onSelectEvent={(ev) => setSelectedIncidentId(ev.id)}
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
                        onSelectEvent={(ev) => setSelectedIncidentId(ev.id)}
                      />
                      <LiveFeed />
                    </div>
                  </>
                )}

                {viewMode === 'analytics-focus' && (
                  <div className="grid grid-cols-1 lg:grid-cols-5 gap-2.5">
                    {/* Narrow events list */}
                    <div className="lg:col-span-2">
                      <RecentEventsList
                        selectedEventId={selectedIncidentId}
                        onSelectEvent={(ev) => setSelectedIncidentId(ev.id)}
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
      </div>
    </div>
  );
}
