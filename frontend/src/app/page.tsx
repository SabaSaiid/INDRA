'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import WelcomeHeader from '@/components/WelcomeHeader';
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
import { staggerContainer } from '@/lib/motion';

export default function DashboardPage() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [liveKpiData, setLiveKpiData] = useState<KpiItem[]>(kpiData);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(undefined);

  // Fetch live KPI data from API, fall back to mock
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchDashboardSummary();
        if (!cancelled) setLiveKpiData(data);
      } catch {
        // mock data is already set as default
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Auto-collapse sidebar on medium screens
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024 && window.innerWidth >= 768) {
        setSidebarCollapsed(true);
      } else if (window.innerWidth >= 1280) {
        setSidebarCollapsed(false);
      }

      // Close mobile menu on resize up
      if (window.innerWidth >= 768) {
        setMobileMenuOpen(false);
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div className="min-h-screen bg-surface">
      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />

      {/* Main content area */}
      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed
            ? 'md:ml-[72px]'
            : 'md:ml-[256px]'
        }`}
      >
        {/* Topbar */}
        <Topbar onMobileMenuOpen={() => setMobileMenuOpen(true)} />

        {/* Dashboard content */}
        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto">
          <AnimatePresence mode="wait">
            {isLoading ? (
              <motion.div
                key="skeleton"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
              >
                {/* Skeleton header */}
                <div className="h-16 mb-6" />

                {/* Skeleton KPIs */}
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
                  {[...Array(4)].map((_, i) => (
                    <KpiCardSkeleton key={i} />
                  ))}
                </div>

                {/* Skeleton map + list */}
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
                  <div className="lg:col-span-3">
                    <MapCardSkeleton />
                  </div>
                  <div className="lg:col-span-2">
                    <ListCardSkeleton />
                  </div>
                </div>

                {/* Skeleton bottom row */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
                {/* Welcome Header */}
                <WelcomeHeader />

                {/* KPI Row */}
                <motion.div
                  variants={staggerContainer}
                  initial="hidden"
                  animate="visible"
                  className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6"
                >
                  {liveKpiData.map((item, index) => (
                    <KpiCard key={item.id} item={item} index={index} />
                  ))}
                </motion.div>

                {/* Map + Recent Events */}
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
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
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <EventDistributionChart />
                  <ReportsTrendChart />
                  <LiveFeed />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
