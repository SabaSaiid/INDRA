'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { type DistributionItem } from '@/lib/ui-config';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { fetchEventDistribution } from '@/lib/api';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Layers, ShieldAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export type DistributionTab = 'hazard' | 'severity';
export type TimeRangeFilter = '24h' | '7d' | 'all';

interface EventDistributionChartProps {
  variant?: 'card' | 'embedded';
  title?: string;
  initialTab?: DistributionTab;
  className?: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
    payload: DistributionItem;
  }>;
  total: number;
}

function CustomDonutTooltip({ active, payload, total }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const data = payload[0];
    const pct = total > 0 ? ((data.value / total) * 100).toFixed(1) : '0';
    return (
      <div className="bg-slate-900/95 backdrop-blur-md text-white text-xs rounded-xl shadow-xl border border-slate-700/80 px-3.5 py-2.5 space-y-1.5 z-50 pointer-events-none">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full shadow-sm"
            style={{ backgroundColor: data.payload.color }}
          />
          <span className="font-semibold text-slate-100">{data.name}</span>
        </div>
        <div className="flex items-baseline justify-between gap-4 text-slate-300">
          <span className="font-mono text-base font-bold text-white tabular-nums">
            {data.value}
          </span>
          <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/50">
            {pct}% of total
          </span>
        </div>
      </div>
    );
  }
  return null;
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

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch live distribution data based on activeTab and timeRange
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchEventDistribution(activeTab, timeRange);
        // Nothing to group is a real answer; it is not a reason to draw a chart
        // of numbers nobody computed.
        if (!cancelled) {
          setDistribution(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setDistribution([]);
          setError(err);
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTab, timeRange]);

  const total = useMemo(() => {
    return distribution.reduce((sum, item) => sum + (Number(item.value) || 0), 0);
  }, [distribution]);

  const activeItem = hoveredIndex !== null ? distribution[hoveredIndex] : null;

  const content = (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header controls & Tab switcher */}
      <div className="flex flex-row items-center justify-between gap-1.5 mb-2.5">
        {/* Dimension Tabs (Hazard vs Severity) */}
        <div className="inline-flex p-0.5 rounded-lg bg-slate-100 border border-slate-200/80">
          <button
            type="button"
            onClick={() => {
              setActiveTab('hazard');
              setHoveredIndex(null);
            }}
            className={cn(
              'flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium transition-all cursor-pointer',
              activeTab === 'hazard'
                ? 'bg-white text-slate-900 shadow-sm font-semibold'
                : 'text-slate-500 hover:text-slate-800'
            )}
          >
            <Layers className="w-3 h-3 text-blue-500" />
            <span>Hazard Type</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab('severity');
              setHoveredIndex(null);
            }}
            className={cn(
              'flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium transition-all cursor-pointer',
              activeTab === 'severity'
                ? 'bg-white text-slate-900 shadow-sm font-semibold'
                : 'text-slate-500 hover:text-slate-800'
            )}
          >
            <ShieldAlert className="w-3 h-3 text-amber-500" />
            <span>Severity</span>
          </button>
        </div>

        {/* Time range pills */}
        <div className="flex items-center gap-0.5 text-[10px]">
          {(['24h', '7d', 'all'] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setTimeRange(r)}
              className={cn(
                'px-1.5 py-0.5 rounded font-mono transition-colors cursor-pointer',
                timeRange === r
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'
              )}
            >
              {r === 'all' ? 'All' : r.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Nothing to plot: say so rather than drawing an invented distribution. */}
      {error ? (
        <div className="flex-1 flex items-center justify-center">
          <ErrorState label="the event distribution" error={error} compact />
        </div>
      ) : loaded && distribution.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <EmptyState
            title="No events to group yet"
            hint="The breakdown appears once events are verified."
            compact
          />
        </div>
      ) : (
      /* Chart and Legend container */
      <div className="flex flex-row items-center gap-3 flex-1 justify-center">
        {/* Donut chart — compact 130px */}
        <div className="relative w-[130px] h-[130px] flex-shrink-0 flex items-center justify-center">
          {mounted && (
            <ResponsiveContainer width="100%" height="100%" minWidth={120} minHeight={120}>
              <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <Tooltip
                  content={<CustomDonutTooltip total={total} />}
                  wrapperStyle={{ outline: 'none' }}
                />
                <Pie
                  data={distribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={36}
                  outerRadius={60}
                  paddingAngle={3}
                  dataKey="value"
                  nameKey="name"
                  startAngle={90}
                  endAngle={-270}
                  isAnimationActive={true}
                  animationDuration={800}
                  animationEasing="ease-out"
                  stroke="#ffffff"
                  strokeWidth={2}
                  onMouseEnter={(_, index) => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  {distribution.map((entry, index) => (
                    <Cell
                      key={`cell-${entry.name}-${index}`}
                      fill={entry.color}
                      opacity={
                        hoveredIndex === null || hoveredIndex === index ? 1 : 0.4
                      }
                      className="cursor-pointer transition-opacity duration-200"
                    />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          )}

          {/* Center dynamic metric */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center px-2">
            <AnimatePresence mode="wait">
              {activeItem ? (
                <motion.div
                  key={`hovered-${activeItem.name}`}
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  transition={{ duration: 0.15 }}
                  className="flex flex-col items-center"
                >
                  <span
                    className="text-lg font-bold tabular-nums"
                    style={{ color: activeItem.color }}
                  >
                    {activeItem.value}
                  </span>
                  <span className="text-[9px] font-medium text-slate-700 truncate max-w-[70px]">
                    {activeItem.name}
                  </span>
                  <span className="text-[8px] text-slate-400 font-mono">
                    {total > 0 ? Math.round((activeItem.value / total) * 100) : 0}%
                  </span>
                </motion.div>
              ) : (
                <motion.div
                  key="total-display"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  transition={{ duration: 0.2 }}
                  className="flex flex-col items-center"
                >
                  <span className="text-xl font-bold text-slate-900 tabular-nums">
                    {total}
                  </span>
                  <span className="text-[9px] text-slate-500 font-medium uppercase tracking-wider">
                    {activeTab === 'hazard' ? 'Incidents' : 'Events'}
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Legend — compact items */}
        <div className="flex-1 w-full space-y-0.5 min-w-[100px] max-h-[130px] overflow-y-auto custom-scrollbar pr-0.5">
          {distribution.map((item, index) => {
            const isHovered = hoveredIndex === index;
            const pct = total > 0 ? Math.round((item.value / total) * 100) : 0;
            return (
              <div
                key={item.name}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                className={cn(
                  'flex items-center justify-between py-0.5 px-1.5 rounded text-[10px] cursor-pointer transition-all',
                  isHovered
                    ? 'bg-slate-100 font-medium'
                    : 'hover:bg-slate-50'
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
                  <span className="truncate text-slate-700">{item.name}</span>
                </div>

                <div className="flex items-center gap-1.5 flex-shrink-0 ml-1">
                  <span className="text-[9px] font-mono text-slate-400">{pct}%</span>
                  <span className="font-semibold text-slate-900 tabular-nums min-w-[18px] text-right">{item.value}</span>
                </div>
              </div>
            );
          })}
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
      <Card hover={false} className="h-full flex flex-col p-3.5">
        <CardHeader title={title} density="compact" className="p-0 pb-1 mb-0" />
        {content}
      </Card>
    </motion.div>
  );
}

