'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { type FeedItem } from '@/lib/ui-config';
import { fetchRecentFeed } from '@/lib/api';
import { ArrowRight } from 'lucide-react';
import { formatIst } from '@/lib/utils';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { useTranslation } from '@/lib/i18n/useTranslation';

// Source styling and abbreviations
const sourceConfig: Record<string, { color: string; bg: string; abbr: string }> = {
  citizen: { color: '#4A6670', bg: '#EDF1F3', abbr: 'CTZN' },
  official: { color: '#1B2432', bg: '#E8E2D4', abbr: 'OFCL' },
  social:  { color: '#B8873A', bg: '#F7F2E7', abbr: 'SOCI' },
  imd:     { color: '#8C2F26', bg: '#F5EBEA', abbr: 'IMD' },
  news:    { color: '#7A8599', bg: '#EEF0F4', abbr: 'NEWS' },
  event:   { color: '#8C2F26', bg: '#FEE2E2', abbr: 'EVNT' },
  review:  { color: '#065F46', bg: '#D1FAE5', abbr: 'AUDT' },
  warning: { color: '#9A3412', bg: '#FFEDD5', abbr: 'WARN' },
};

// IMD colour for a warning's CAP severity.
const WARNING_COLOR: Record<string, string> = {
  CRITICAL: '#DC2626',
  HIGH: '#EA580C',
  MODERATE: '#CA8A04',
  ADVISORY: '#059669',
};

function hrefFor(item: FeedItem): string {
  if (item.source === 'warning') return '/alerts';
  if (item.source === 'event' || item.source === 'review') return '/events';
  return '/reports';
}

function sortKey(item: FeedItem): string {
  return item.at || '';
}

export default function LiveFeed() {
  const { t } = useTranslation();
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  // Operator reviews come only over the socket; the feed endpoint has no
  // stream for them. Kept apart so a refetch does not wipe them.
  const [reviewItems, setReviewItems] = useState<FeedItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const { connected, subscribe } = useIndraWebSocket();

  // The feed merges reports, events and official warnings in force. Warnings
  // come from the SACHET poller, which broadcasts nothing, so the feed also
  // refetches every minute; reports and events refetch the moment they are
  // announced. It used to show citizen reports only, stamped with their UTC
  // clock time and no date: one three-day-old line reading "14:57".
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRecentFeed(15);
        if (!cancelled) {
          setFeedItems(data || []);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') setRefreshTick((t) => t + 1);
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    return subscribe('live-feed-component', (msg) => {
      if (msg.type === 'NEW_REPORT' || msg.type === 'VERIFIED_EVENT') {
        setRefreshTick((t) => t + 1);
      } else if (msg.type === 'EVENT_REVIEWED' && msg.event) {
        // The operator id is on msg.review, not on the event.
        const item: FeedItem = {
          id: `ws-rev-${msg.event.id ?? ''}-${Date.now()}`,
          source: 'review',
          sourceLabel: 'Operator review',
          message: `${msg.event.event_code || 'Event'} → ${
            String(msg.event.review_status || 'reviewed').replace(/_/g, ' ').toLowerCase()
          } by ${msg.review?.operator_id || 'an operator'}`,
          time: formatIst(new Date()),
          at: new Date().toISOString(),
        };
        setReviewItems((prev) => [item, ...prev].slice(0, 5));
        setRefreshTick((t) => t + 1);
      }
    });
  }, [subscribe]);

  const items = useMemo(
    () =>
      [...reviewItems, ...feedItems]
        .sort((a, b) => (sortKey(b) > sortKey(a) ? 1 : sortKey(b) < sortKey(a) ? -1 : 0))
        .slice(0, 15),
    [reviewItems, feedItems]
  );

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.6 }}
      className="h-full"
    >
      <Card hover={false} className="h-full flex flex-col min-h-0" density="compact">
        <CardHeader
          density="compact"
          title={
            <span className="flex items-center gap-1.5" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              <span>{t('dashboard.live_feed')}</span>
              {connected && (
                <span className="flex items-center gap-1 text-[9px] font-mono text-emerald-600 font-normal">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  {t('kpis.live_label')}
                </span>
              )}
            </span>
          }
          action={
            <Link
              href="/reports"
              className="flex items-center gap-1 text-[10px] font-medium text-[#7A8599] hover:text-[#1B2432] transition-colors"
            >
              <span>{t('common.view_all')}</span>
              <ArrowRight className="w-3 h-3" />
            </Link>
          }
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="custom-scrollbar overflow-y-auto flex-1 min-h-0"
          style={{ maxHeight: '185px' }}
        >
          {error && items.length === 0 ? (
            <ErrorState label="the live feed" error={error} compact />
          ) : loaded && items.length === 0 ? (
            <EmptyState
              title={t('dashboard.no_reports')}
              hint="Reports, events and official warnings stream in here as they arrive."
              compact
            />
          ) : null}
          {items.map((item) => {
            const cfg = sourceConfig[item.source] || sourceConfig.news;
            const accent =
              item.source === 'warning' ? WARNING_COLOR[item.severity ?? ''] ?? cfg.color : cfg.color;
            const when = item.at ? formatIst(item.at) : item.time;
            const localizedSource = (() => {
              const lower = (item.sourceLabel || '').toLowerCase();
              if (lower.includes('citizen')) return t('kpis.citizen_reports');
              if (lower.includes('official') || lower.includes('warning') || lower.includes('alert')) return t('nav.official_warnings');
              if (lower.includes('review') || lower.includes('operator')) return t('receipt.commander_review');
              if (lower.includes('event')) return t('nav.incident_events');
              return item.sourceLabel;
            })();

            return (
              <motion.div key={item.id} variants={listItemSlideIn}>
                <Link
                  href={hrefFor(item)}
                  title={[item.sourceLabel, item.message, item.place].filter(Boolean).join(' — ')}
                  className="flex items-center gap-2 py-1.5 border-b border-[#F0EBE0] last:border-0 px-1 transition-colors hover:bg-[#F7F3EA] rounded"
                >
                  {/* Micro source badge */}
                  <span
                    className="text-[9px] font-semibold flex-shrink-0 tabular-nums px-1 py-0.5 rounded"
                    style={{
                      fontFamily: 'JetBrains Mono, monospace',
                      color: accent,
                      backgroundColor: `${accent}18`,
                    }}
                  >
                    {cfg.abbr}
                  </span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[10px] font-semibold text-[#1B2432] flex-shrink-0 max-w-[40%] truncate">
                        {localizedSource}
                      </span>
                      <span className="text-[9px] text-[#4A5568] truncate flex-1 min-w-0">
                        {item.message}
                      </span>
                      <span
                        className="text-[9px] text-[#B0A898] tabular-nums flex-shrink-0"
                        style={{ fontFamily: 'JetBrains Mono, monospace' }}
                      >
                        {when}
                      </span>
                    </div>
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </motion.div>
      </Card>
    </motion.div>
  );
}
