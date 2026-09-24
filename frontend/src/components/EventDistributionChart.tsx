'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { type DistributionItem } from '@/lib/ui-config';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { fetchEventDistribution, fetchAgencyAlerts, agencyAlertsToDistribution, type AgencyAlert } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';
import { Layers, ShieldAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export type DistributionTab = 'hazard' | 'severity';
export type TimeRangeFilter = '24h' | '7d' | 'all';
/** What is being grouped: INDRA's own events, or official warnings in force. */
export type DistributionSource = 'events' | 'warnings';

interface EventDistributionChartProps {
  variant?: 'card' | 'embedded';
  title?: string;
  initialTab?: DistributionTab;
  className?: string;
}

export default function EventDistributionChart({
  variant = 'card',
  title = 'Event Distribution',
  initialTab = 'hazard',
  className,
}: EventDistributionChartProps) {
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<DistributionTab>(initialTab);
  const [timeRange, setTimeRange] = useState<TimeRangeFilter>('7d');
  const [distribution, setDistribution] = useState<DistributionItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { subscribe } = useIndraWebSocket();
  // The panel grouped INDRA events only, so on a day without citizen reports
  // it was an empty ring beside a map full of official warnings. It can now
  // group either, and says which it is showing. With no events it opens on the
  // warnings, once; after that the operator's choice stands.
  const [source, setSource] = useState<DistributionSource>('events');
  const [sourceChosen, setSourceChosen] = useState(false);
  const [alerts, setAlerts] = useState<AgencyAlert[] | null>(null);
  const [alertsError, setAlertsError] = useState<unknown>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch live distribution data based on activeTab and timeRange
  const loadDistribution = useCallback(async (tab: DistributionTab, range: TimeRangeFilter) => {
    try {
      const data = await fetchEventDistribution(tab, range);
      setDistribution(data || []);
      setError(null);
    } catch (err) {
      setDistribution([]);
      setError(err);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    loadDistribution(activeTab, timeRange);
  }, [activeTab, timeRange, loadDistribution]);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAgencyAlerts(200)
        .then((rows) => { if (!cancelled) { setAlerts(rows); setAlertsError(null); } })
        .catch((err) => { if (!cancelled) setAlertsError(err); });
    load();
    const id = setInterval(load, 120_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const eventsTotal = useMemo(
    () => distribution.reduce((sum, item) => sum + (Number(item.value) || 0), 0),
    [distribution]
  );

  const autoDecided = React.useRef(false);
  useEffect(() => {
    if (autoDecided.current || sourceChosen || !loaded || alerts === null) return;
    autoDecided.current = true;
    if (eventsTotal === 0 && alerts.length > 0) setSource('warnings');
  }, [sourceChosen, loaded, alerts, eventsTotal]);

  const chooseSource = (next: DistributionSource) => {
    setSourceChosen(true);
    setHoveredIndex(null);
    setSource(next);
  };

  const warningsDistribution = useMemo(
    () => (alerts ? agencyAlertsToDistribution(alerts, activeTab) : []),
    [alerts, activeTab]
  );
  const shown = source === 'events' ? distribution : warningsDistribution;
  const shownError = source === 'events' ? error : alertsError;
  const shownLoaded = source === 'events' ? loaded : alerts !== null || alertsError !== null;

  // Real-time synchronization on WebSocket events
  useEffect(() => {
    return subscribe('event-distribution-chart', (msg) => {
      if (['VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        loadDistribution(activeTab, timeRange);
      }
    });
  }, [subscribe, activeTab, timeRange, loadDistribution]);

  // Handle Tab Switch and clear hover
  const handleTabChange = (newTab: DistributionTab) => {
    if (newTab === activeTab) return;
    setHoveredIndex(null);
    setActiveTab(newTab);
  };

  const total = useMemo(() => {
    return shown.reduce((sum, item) => sum + (Number(item.value) || 0), 0);
  }, [shown]);

  // Bounds-safe active item
  const activeItem = useMemo(() => {
    if (hoveredIndex === null) return null;
    return shown[hoveredIndex] || null;
  }, [hoveredIndex, shown]);

  const sourceToggle = (
    <div className="inline-flex items-center rounded-md border border-[#E0D7C6] bg-[#EFE9DC] p-0.5 text-[9px] font-mono">
      {(['events', 'warnings'] as const).map((src) => {
        const n = src === 'events' ? eventsTotal : alerts?.length ?? 0;
        return (
          <button
            key={src}
            type="button"
            onClick={() => chooseSource(src)}
            title={src === 'events' ? 'Events INDRA formed from reports' : 'Official warnings in force (IMD, CWC, SDMA via SACHET)'}
            className={cn(
              'px-1.5 py-0.5 rounded transition-colors cursor-pointer',
              source === src ? 'bg-white text-[#1B2432] font-bold shadow-2xs' : 'text-[#7A8599] hover:text-[#1B2432]'
            )}
          >
            {src === 'events' ? 'Events' : 'Warnings'} {n}
          </button>
        );
      })}
    </div>
  );

  const content = (
    <div className={cn('flex flex-col h-full min-h-0', className)}>
      {/* Subheader: Segmented Tab Switcher + Time Range Pills */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-1 border-b border-[#F0EBE0]">
        {/* Dimension Tabs (Hazard vs Severity) */}
        <div className="inline-flex p-0.5 rounded-lg bg-[#EFE9DC] border border-[#E0D7C6]">
          <button
            type="button"
            onClick={() => handleTabChange('hazard')}
            className={cn(
              'relative flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer',
              activeTab === 'hazard'
                ? 'text-[#1B2432] font-semibold'
                : 'text-[#7A8599] hover:text-[#1B2432]'
            )}
          >
            {activeTab === 'hazard' && (
              <motion.div
                layoutId="activeDistTabIndicator"
                className="absolute inset-0 bg-white rounded-md shadow-2xs"
                transition={{ type: 'spring', bounce: 0.15, duration: 0.35 }}
              />
            )}
            <span className="relative z-10 flex items-center gap-1">
              <Layers className="w-3 h-3 text-[#4A6670]" />
              <span>By Hazard</span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => handleTabChange('severity')}
            className={cn(
              'relative flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer',
              activeTab === 'severity'
                ? 'text-[#1B2432] font-semibold'
                : 'text-[#7A8599] hover:text-[#1B2432]'
            )}
          >
            {activeTab === 'severity' && (
              <motion.div
                layoutId="activeDistTabIndicator"
                className="absolute inset-0 bg-white rounded-md shadow-2xs"
                transition={{ type: 'spring', bounce: 0.15, duration: 0.35 }}
              />
            )}
            <span className="relative z-10 flex items-center gap-1">
              <ShieldAlert className="w-3 h-3 text-[#B8873A]" />
              <span>By Severity</span>
            </span>
          </button>
        </div>

        {/* Time range pills — events only; a warning is either in force or not */}
        {variant === 'embedded' && sourceToggle}
        {source === 'warnings' ? (
          <span className="text-[9px] font-mono text-[#7A8599] uppercase tracking-wider">In force now</span>
        ) : (
        <div className="flex items-center gap-0.5 text-[9px] font-mono">
          {(['24h', '7d', 'all'] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => {
                setHoveredIndex(null);
                setTimeRange(r);
              }}
              className={cn(
                'px-1.5 py-0.5 rounded transition-all cursor-pointer font-medium',
                timeRange === r
                  ? 'bg-[#1B2432] text-white font-bold shadow-2xs'
                  : 'text-[#7A8599] hover:text-[#1B2432] hover:bg-[#EFE9DC]'
              )}
            >
              {r === 'all' ? 'ALL' : r.toUpperCase()}
            </button>
          ))}
        </div>
        )}
      </div>

      {/* Nothing to plot: say so rather than drawing an invented distribution. */}
      {shownError ? (
        <div className="flex-1 flex items-center justify-center">
          <ErrorState
            label={source === 'events' ? 'the event distribution' : 'the official warnings'}
            error={shownError}
            compact
          />
        </div>
      ) : shownLoaded && shown.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center">
          <EmptyState
            title={source === 'events' ? 'No events in this range' : 'No official warnings in force'}
            hint={
              source === 'events'
                ? 'An event forms once two nearby reports corroborate each other.'
                : 'No IMD, CWC or SDMA warning is in force right now.'
            }
            compact
            className="py-2"
          />
          {source === 'events' && (alerts?.length ?? 0) > 0 && (
            <button
              type="button"
              onClick={() => chooseSource('warnings')}
              className="text-[10px] font-medium text-[#4A6670] underline underline-offset-2 hover:text-[#1B2432]"
            >
              Show the {alerts!.length} official warnings in force
            </button>
          )}
        </div>
      ) : (
      /* Chart and Legend container */
      <div className="flex flex-row items-center gap-2.5 flex-1 min-h-0 justify-between">
        {/* Donut chart with Center Hole Inspection Readout */}
        <div className="relative w-[128px] h-[128px] flex-shrink-0 flex items-center justify-center">
          {mounted && total > 0 ? (
            <ResponsiveContainer width="100%" height="100%" minWidth={110} minHeight={110}>
              <PieChart
                key={`${source}-${activeTab}-${timeRange}`}
                margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
              >
                <Pie
                  data={shown}
                  cx="50%"
                  cy="50%"
                  innerRadius={38}
                  outerRadius={60}
                  paddingAngle={3}
                  dataKey="value"
                  nameKey="name"
                  startAngle={90}
                  endAngle={-270}
                  isAnimationActive={true}
                  animationDuration={600}
                  animationEasing="ease-out"
                  stroke="#F7F3EA"
                  strokeWidth={2}
                  onMouseEnter={(_, index) => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  {shown.map((entry, index) => (
                    <Cell
                      key={`cell-${entry.name}-${index}`}
                      fill={entry.color}
                      opacity={
                        hoveredIndex === null || hoveredIndex === index ? 1 : 0.35
                      }
                      className="cursor-pointer transition-opacity duration-150"
                    />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          ) : total === 0 ? (
            <div className="w-[104px] h-[104px] rounded-full border border-dashed border-[#D5CDBC] flex flex-col items-center justify-center text-center p-2 bg-[#F7F3EA]/50">
              <span className="text-base font-bold text-[#A0988A] font-mono">0</span>
              <span className="text-[8px] text-[#B0A898] uppercase tracking-wider">No events</span>
            </div>
          ) : null}

          {/* Dedicated Center Hole Readout (Eliminates floating tooltip collisions) */}
          {total > 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center px-1">
              {activeItem ? (
                <div className="flex flex-col items-center justify-center">
                  <span
                    className="text-lg font-bold tabular-nums font-mono leading-none"
                    style={{ color: activeItem.color }}
                  >
                    {activeItem.value}
                  </span>
                  <span className="text-[10px] font-semibold text-[#1B2432] truncate max-w-[68px] mt-0.5 leading-tight">
                    {activeItem.name}
                  </span>
                  <span className="text-[9px] text-[#7A8599] font-mono leading-none mt-0.5">
                    {total > 0 ? Math.round((Number(activeItem.value) / total) * 100) : 0}%
                  </span>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center">
                  <span className="text-xl font-bold text-[#1B2432] tabular-nums font-mono leading-none">
                    {total}
                  </span>
                  <span className="text-[9px] text-[#7A8599] font-medium uppercase tracking-wider mt-0.5 leading-none">
                    {source === 'warnings' ? 'Warnings' : 'Events'}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="flex-1 min-w-0 space-y-0.5 max-h-[126px] overflow-y-auto custom-scrollbar pr-0.5">
          {total === 0 ? (
            <div className="text-[10px] text-[#A0988A] text-center italic py-6">
              No incidents recorded in this time range.
            </div>
          ) : (
            shown.map((item, index) => {
              const isHovered = hoveredIndex === index;
              const pct = total > 0 ? Math.round((Number(item.value) / total) * 100) : 0;
              return (
                <div
                  key={item.name}
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  className={cn(
                    'flex items-center justify-between py-0.5 px-1.5 rounded text-[10px] cursor-pointer transition-colors',
                    isHovered
                      ? 'bg-[#EFE9DC] font-medium shadow-2xs'
                      : 'hover:bg-[#F7F3EA]'
                  )}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <div
                      className={cn(
                        'w-2 h-2 rounded-full flex-shrink-0 transition-transform duration-150',
                        isHovered && 'scale-125'
                      )}
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="truncate text-[#1B2432] text-[10px]">{item.name}</span>
                  </div>

                  <div className="flex items-center gap-1.5 flex-shrink-0 ml-1">
                    <span className="text-[9px] font-mono text-[#7A8599]">{pct}%</span>
                    <span className="font-semibold text-[#1B2432] tabular-nums font-mono min-w-[16px] text-right">
                      {item.value}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
      )}
    </div>
  );

  if (variant === 'embedded') {
    return content;
  }

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.4 }}
      className="h-full"
    >
      <Card hover={false} className="h-full flex flex-col p-3" density="compact">
        <CardHeader
          density="compact"
          className="p-0 pb-1.5 mb-0 flex items-center justify-between"
          title={
            <span style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              {title}
            </span>
          }
          action={sourceToggle}
        />
        {content}
      </Card>
    </motion.div>
  );
}
