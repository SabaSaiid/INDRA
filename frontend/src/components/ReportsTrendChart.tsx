'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { type TrendDataPoint } from '@/lib/ui-config';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { fetchReportsTrend } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { ArrowRight } from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useThemeTokens } from '@/lib/useThemeTokens';

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const val = payload[0].value ?? 0;
    return (
      <div className="bg-surface-raised/95 backdrop-blur-md text-text rounded-lg shadow-xl border border-border px-3 py-2 text-xs">
        <p className="text-[10px] text-text-muted font-medium mb-1">{label}</p>
        <div className="flex items-center gap-1.5 font-mono">
          <span className="w-2 h-2 rounded-full bg-brand animate-pulse" />
          <span className="text-sm font-bold text-text tabular-nums">
            {val.toLocaleString()}
          </span>
          <span className="text-[10px] text-text-muted font-sans">reports</span>
        </div>
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
  title,
  className,
}: ReportsTrendChartProps = {}) {
  const { t } = useTranslation();
  const tokens = useThemeTokens();
  const chartTitle = title ?? t('nav.field_reports');
  const [mounted, setMounted] = useState(false);
  const [dateRange, setDateRange] = useState<'7d' | '14d' | '30d'>('7d');
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const { subscribe } = useIndraWebSocket();

  useEffect(() => {
    setMounted(true);
  }, []);

  // A new report changes today's count.
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
  const days = Number(dateRange.replace('d', '')) || 7;
  const avgPerDay = useMemo(() => (days > 0 ? Math.round(total / days) : 0), [total, days]);

  const { peakCount, peakDate } = useMemo(() => {
    if (!trendData.length) return { peakCount: 0, peakDate: '—' };
    let max = -1;
    let d = '—';
    for (const item of trendData) {
      const cnt = Number(item.reports) || 0;
      if (cnt > max) {
        max = cnt;
        d = item.date || '—';
      }
    }
    return { peakCount: Math.max(0, max), peakDate: d };
  }, [trendData]);

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

  // Clean Y-axis tick formatter preventing large number truncation
  const formatYTick = (val: number): string => {
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(1).replace(/\.0$/, '')}k`;
    return `${val}`;
  };

  // Determine interval so no dates get skipped in 7d view
  const xAxisInterval = useMemo(() => {
    if (trendData.length <= 8) return 0;
    if (trendData.length <= 15) return 1;
    return 'preserveStartEnd';
  }, [trendData.length]);

  const rangeButtons = (
    <div className="flex items-center gap-0.5 bg-surface-raised p-0.5 rounded-lg border border-border" role="group" aria-label="Date range">
      {(['7d', '14d', '30d'] as const).map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => setDateRange(r)}
          className={`px-2 py-0.5 rounded-md text-[10px] font-semibold transition-all ${
            dateRange === r
              ? 'bg-surface text-text shadow-2xs'
              : 'text-text-muted hover:text-text'
          }`}
        >
          {r}
        </button>
      ))}
    </div>
  );

  const chartContent = (
    <div className={`flex flex-col flex-1 min-h-0 ${className ?? ''}`}>
      {/* Subheader shown in embedded mode or if no CardHeader */}
      {variant === 'embedded' && (
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] text-[#7A8599]">
            {loaded && !error && (
              <span>
                Total: <strong className="font-mono text-[#1B2432] font-semibold">{total.toLocaleString()}</strong> ({days}d)
                {avgPerDay > 0 && <span className="ml-1.5 font-mono text-[#7A8599]">· ~{avgPerDay.toLocaleString()}/day</span>}
              </span>
            )}
          </div>
          {rangeButtons}
        </div>
      )}

      {/* Main Chart Area */}
      <div className="h-[140px] min-h-[140px] w-full pt-1 relative">
        {error ? (
          <div className="h-full flex items-center justify-center">
            <ErrorState label="the reports trend" error={error} compact />
          </div>
        ) : mounted && (
          <>
            <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={140}>
              <AreaChart
                data={trendData.length ? trendData : []}
                margin={{ top: 8, right: 12, left: 2, bottom: 2 }}
              >
                <defs>
                  <linearGradient id="reportGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={tokens.brand} stopOpacity={0.22} />
                    <stop offset="95%" stopColor={tokens.brand} stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke={tokens.border}
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: tokens.textMuted, fontFamily: 'JetBrains Mono, monospace' }}
                  dy={6}
                  interval={xAxisInterval}
                  minTickGap={10}
                />
                {/* Counts: whole numbers only, formatted to avoid cutting off digits */}
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: tokens.textMuted, fontFamily: 'JetBrains Mono, monospace' }}
                  dx={-2}
                  allowDecimals={false}
                  domain={[0, (max: number) => Math.max(1, Math.ceil(max * 1.05))]}
                  width={36}
                  tickFormatter={formatYTick}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="linear"
                  dataKey="reports"
                  stroke={tokens.brand}
                  strokeWidth={2.2}
                  fill="url(#reportGradient)"
                  dot={(props: any) =>
                    props?.payload?.reports > 0 ? (
                      <circle
                        key={`dot-${props.index}`}
                        cx={props.cx}
                        cy={props.cy}
                        r={3.2}
                        fill={tokens.brand}
                        stroke={tokens.surface}
                        strokeWidth={1.8}
                      />
                    ) : (
                      <g key={`dot-${props.index}`} />
                    )
                  }
                  activeDot={{
                    r: 5,
                    strokeWidth: 2,
                    stroke: tokens.surface,
                    fill: tokens.brand,
                  }}
                  animationBegin={100}
                  animationDuration={800}
                  animationEasing="ease-out"
                />
              </AreaChart>
            </ResponsiveContainer>
            {/* Zero-volume hint overlay — shown only when all days have 0 reports */}
            {loaded && total === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="bg-surface/80 border border-border backdrop-blur-sm rounded-lg px-3 py-1.5 text-center">
                  <p className="text-[10px] text-text-muted font-medium">
                    {t('analytics.trend_no_reports_hint')}
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer metadata & quick navigation */}
      {variant === 'card' && loaded && !error && total > 0 && (
        <div className="flex items-center justify-between pt-1.5 px-0.5 text-[10px] text-text-muted border-t border-border mt-auto">
          <span className="truncate">
            Peak: <strong className="font-mono text-text">{peakCount.toLocaleString()}</strong> ({peakDate})
          </span>
          <Link
            href="/reports"
            className="flex items-center gap-1 text-brand hover:underline font-medium transition-colors ml-2 flex-shrink-0"
          >
            <span>View all</span>
            <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
      )}
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
      <Card hover={false} className="h-full flex flex-col p-3" density="compact">
        <CardHeader
          density="compact"
          className="p-0 pb-1 mb-1 flex items-center justify-between"
          title={
            <div className="flex items-center gap-2">
              <span className="font-display">
                {chartTitle}
              </span>
              {loaded && !error && total > 0 && (
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-brand/10 text-brand border border-brand/20 font-semibold tracking-tight">
                  {total.toLocaleString()}
                </span>
              )}
            </div>
          }
          subtitle={
            <span className="text-[11px] text-text-muted flex items-center gap-1.5 font-normal">
              <span>{days}d trend</span>
              {avgPerDay > 0 && (
                <>
                  <span>·</span>
                  <span className="font-mono text-text-secondary">~{avgPerDay.toLocaleString()}/day</span>
                </>
              )}
            </span>
          }
          action={rangeButtons}
        />
        {chartContent}
      </Card>
    </motion.div>
  );
}


