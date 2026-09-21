'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  feedSourceConfig,
  type FeedSourceType,
  type FeedItem,
} from '@/lib/ui-config';
import { fetchRecentFeed } from '@/lib/api';
import { ArrowRight, Radio } from 'lucide-react';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';

// Source styling and abbreviations
const sourceConfig: Record<string, { color: string; bg: string; abbr: string }> = {
  citizen: { color: '#4A6670', bg: '#EDF1F3', abbr: 'CTZN' },
  social:  { color: '#B8873A', bg: '#F7F2E7', abbr: 'SOCI' },
  imd:     { color: '#8C2F26', bg: '#F5EBEA', abbr: 'IMD' },
  news:    { color: '#7A8599', bg: '#EEF0F4', abbr: 'NEWS' },
  event:   { color: '#8C2F26', bg: '#FEE2E2', abbr: 'EVNT' },
  review:  { color: '#065F46', bg: '#D1FAE5', abbr: 'AUDT' },
};

export default function LiveFeed() {
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const { connected, subscribe } = useIndraWebSocket();

  // Initial fetch of recent feed items
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRecentFeed(12);
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
  }, []);

  // Centralized WebSocket listener handling NEW_REPORT, VERIFIED_EVENT, and EVENT_REVIEWED
  useEffect(() => {
    return subscribe('live-feed-component', (msg) => {
      const nowTime = new Date().toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      });

      if (msg.type === 'NEW_REPORT' && msg.report) {
        const rep = msg.report;
        const newItem: FeedItem = {
          id: rep.id || `ws-rep-${Date.now()}`,
          source: (rep.source_type === 'sensor' ? 'imd' : 'citizen') as FeedSourceType,
          sourceLabel: rep.source_type === 'sensor' ? 'Sensor pulse' : 'Citizen report',
          message: rep.text || rep.raw_text || 'Ground incident report received',
          time: nowTime,
        };
        setFeedItems((prev) => [newItem, ...prev.slice(0, 14)]);
      } else if (msg.type === 'VERIFIED_EVENT' && msg.event) {
        const ev = msg.event;
        const confPct = Math.round((ev.confidence_score || 0.85) * 100);
        const newItem: FeedItem = {
          id: ev.id || `ws-ev-${Date.now()}`,
          source: 'imd' as FeedSourceType,
          sourceLabel: 'Verified Event',
          message: `${ev.event_type || ev.eventType || 'Event'} cluster formed in ${ev.city || 'Area'} (${confPct}% conf)`,
          time: nowTime,
        };
        setFeedItems((prev) => [newItem, ...prev.slice(0, 14)]);
      } else if (msg.type === 'EVENT_REVIEWED') {
        const newItem: FeedItem = {
          id: `ws-rev-${Date.now()}`,
          source: 'imd' as FeedSourceType,
          sourceLabel: 'Audit Action',
          message: `${msg.event_code || 'Event'} marked ${msg.review_status || msg.action || 'REVIEWED'} by ${msg.operator_id || 'Commander'}`,
          time: nowTime,
        };
        setFeedItems((prev) => [newItem, ...prev.slice(0, 14)]);
      }
    });
  }, [subscribe]);

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
              <span>Live Feed</span>
              {connected && (
                <span className="flex items-center gap-1 text-[9px] font-mono text-emerald-600 font-normal">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  LIVE
                </span>
              )}
            </span>
          }
          action={
            <Link
              href="/reports"
              className="flex items-center gap-1 text-[10px] font-medium text-[#7A8599] hover:text-[#1B2432] transition-colors"
            >
              <span>View all</span>
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
          {error && feedItems.length === 0 ? (
            <ErrorState label="the live feed" error={error} compact />
          ) : loaded && feedItems.length === 0 ? (
            <EmptyState
              title="No reports yet"
              hint="Incoming citizen reports stream in here as they arrive."
              compact
            />
          ) : null}
          {feedItems.map((item) => {
            const cfg = sourceConfig[item.source] || sourceConfig.news;

            return (
              <motion.div
                key={item.id}
                variants={listItemSlideIn}
                className="flex items-center gap-2 py-1.5 border-b border-[#F0EBE0] last:border-0 px-1 transition-colors hover:bg-[#F7F3EA] rounded"
              >
                {/* Micro source badge */}
                <span
                  className="text-[9px] font-semibold flex-shrink-0 tabular-nums px-1 py-0.5 rounded"
                  style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    color: cfg.color,
                    backgroundColor: `${cfg.color}18`,
                  }}
                >
                  {cfg.abbr}
                </span>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[10px] font-semibold text-[#1B2432] flex-shrink-0">
                      {item.sourceLabel}
                    </span>
                    <span className="text-[9px] text-[#4A5568] truncate flex-1 min-w-0">
                      {item.message}
                    </span>
                    <span
                      className="text-[9px] text-[#B0A898] tabular-nums flex-shrink-0"
                      style={{ fontFamily: 'JetBrains Mono, monospace' }}
                    >
                      {item.time}
                    </span>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </Card>
    </motion.div>
  );
}
