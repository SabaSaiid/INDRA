'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { type TrendDataPoint } from '@/lib/ui-config';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { fetchReportsTrend } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white rounded-lg shadow-lg border border-slate-100 px-3 py-2">
        <p className="text-xs font-medium text-text-primary">{label}</p>
        <p className="text-sm font-bold text-primary tabular-nums">
          {payload[0].value} {payload[0].value === 1 ? 'report' : 'reports'}
        </p>
      </div>
    );
  }
  return null;
}

interface ReportsTrendChartProps {
  variant?: 'card' | 'embedded';
  title?: string;
  className?: string;
}

export default function ReportsTrendChart({
  variant = 'card',
  title = 'Reports Trend',
  className,
}: ReportsTrendChartProps = {}) {
  const [mounted, setMounted] = useState(false);
  const [dateRange, setDateRange] = useState('7d');
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const { subscribe } = useIndraWebSocket();

  useEffect(() => {
    setMounted(true);
  }, []);

  // A new report changes today's count. The chart used to load once and never
  // again, so a report filed during the demo never showed on it.
  useEffect(() => {
    return subscribe(`reports-trend-${variant}`, (msg) => {
      if (msg.type === 'NEW_REPORT') setRefreshTick((t) => t + 1);
    });
  }, [subscribe, variant]);

  // The day rolls over at IST midnight whether or not anything arrives.
  useEffect(() => {
    const id = setInterval(() => setRefreshTick((t) => t + 1), 300_000);
    return () => clearInterval(id);
  }, []);

  const total = useMemo(() => trendData.reduce((n, d) => n + (Number(d.reports) || 0), 0), [trendData]);
  const days = dateRange.replace('d', '');

  // Fetch live trend data and re-fetch when range changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchReportsTrend(dateRange);
        if (!cancelled) {
          setTrendData(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setTrendData([]);
          setError(err);
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [dateRange, refreshTick]);

  const chartContent = (
    <div className={className}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-text-secondary font-medium">
          Reports per day
          {loaded && !error && (
            <span className="ml-1.5 font-mono text-[#7A8599]">
              · {total} in {days} days
            </span>
          )}
        </span>
        <select
          value={dateRange}
          onChange={(e) => setDateRange(e.target.value)}
          className="text-[10px] px-2 py-0.5 rounded border border-slate-200 bg-white text-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
          aria-label="Date range"
        >
          <option value="7d">7d</option>
          <option value="14d">14d</option>
          <option value="30d">30d</option>
        </select>
      </div>

      <div className="h-[145px] min-h-[145px] -ml-2">
        {error ? (
          <div className="h-full flex items-center justify-center">
            <ErrorState label="the reports trend" error={error} compact />
          </div>
        ) : loaded && (trendData.length === 0 || total === 0) ? (
          <div className="h-full flex items-center justify-center">
            <EmptyState
              title={`No reports in the last ${days} days`}
              hint="The trend fills in as reports are submitted."
              compact
            />
          </div>
        ) : mounted && (
          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={145}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="reportGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563EB" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#2563EB" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#E2E8F0"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: '#94A3B8' }}
                dy={8}
                interval="preserveStartEnd"
                minTickGap={12}
              />
              {/* Counts: whole numbers only. The axis printed a "0.5" tick. */}
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: '#94A3B8' }}
                dx={-8}
                allowDecimals={false}
                domain={[0, (max: number) => Math.max(1, max)]}
                width={28}
              />
              <Tooltip content={<CustomTooltip />} />
              {/* Linear, with a dot on every day that had reports. The
                  monotone spline drew a single report as a smooth bell
                  spreading over the days either side of it. */}
              <Area
                type="linear"
                dataKey="reports"
                stroke="#2563EB"
                strokeWidth={2}
                fill="url(#reportGradient)"
                dot={(props: any) =>
                  props?.payload?.reports > 0 ? (
                    <circle
                      key={`dot-${props.index}`}
                      cx={props.cx}
                      cy={props.cy}
                      r={3}
                      fill="#2563EB"
                      stroke="white"
                      strokeWidth={1.5}
                    />
                  ) : (
                    <g key={`dot-${props.index}`} />
                  )
                }
                activeDot={{
                  r: 5,
                  strokeWidth: 2,
                  stroke: '#2563EB',
                  fill: 'white',
                }}
                animationBegin={100}
                animationDuration={1000}
                animationEasing="ease-out"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );

  if (variant === 'embedded') {
    return chartContent;
  }

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.55 }}
      className="h-full"
    >
      <Card hover={false} className="h-full flex flex-col p-3.5">
        <CardHeader title={title} density="compact" className="p-0 pb-1 mb-0" />
        {chartContent}
      </Card>
    </motion.div>
  );
}

