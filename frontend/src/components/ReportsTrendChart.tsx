'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { reportsTrend, type TrendDataPoint } from '@/lib/mock-data';
import { fetchReportsTrend } from '@/lib/api';
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
          {payload[0].value} reports
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
  const [trendData, setTrendData] = useState<TrendDataPoint[]>(reportsTrend);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch live trend data and re-fetch when range changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchReportsTrend(dateRange);
        if (!cancelled && data.length > 0) {
          setTrendData(data);
        }
      } catch {
        // mock data already set
      }
    })();
    return () => { cancelled = true; };
  }, [dateRange]);

  const chartContent = (
    <div className={className}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-text-secondary font-medium">Incident & Sensor Volume</span>
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
        {mounted && (
          <ResponsiveContainer width="100%" height="100%" minWidth={250} minHeight={145}>
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
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: '#94A3B8' }}
                dx={-8}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="reports"
                stroke="#2563EB"
                strokeWidth={2.5}
                fill="url(#reportGradient)"
                dot={false}
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

