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

export default function ReportsTrendChart() {
  const [dateRange, setDateRange] = useState('7d');
  const [trendData, setTrendData] = useState<TrendDataPoint[]>(reportsTrend);

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

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.55 }}
    >
      <Card hover={false} className="h-full">
        <CardHeader
          title="Reports Trend"
          action={
            <select
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
              aria-label="Date range"
            >
              <option value="7d">Last 7 days</option>
              <option value="14d">Last 14 days</option>
              <option value="30d">Last 30 days</option>
            </select>
          }
        />

        <div className="h-[200px] -ml-2">
          <ResponsiveContainer width="100%" height="100%">
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
                animationBegin={300}
                animationDuration={1500}
                animationEasing="ease-out"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </motion.div>
  );
}
