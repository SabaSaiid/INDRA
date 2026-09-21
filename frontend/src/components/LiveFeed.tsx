'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  feedSourceConfig,
  type FeedSourceType,
  type FeedItem,
} from '@/lib/ui-config';
import { fetchRecentFeed } from '@/lib/api';
import { ArrowRight } from 'lucide-react';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';

// Source label abbreviation
const sourceAbbr: Record<FeedSourceType, string> = {
  citizen: 'CTZN',
  social:  'SOCI',
  imd:     'IMD',
  news:    'NEWS',
};

export default function LiveFeed() {
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);

  // Fetch live feed data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRecentFeed(10);
        // An empty feed is a real state: nobody has reported anything yet.
        if (!cancelled) {
          setFeedItems(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // WebSocket for real-time NEW_REPORT pushes
  useEffect(() => {
    const wsUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
      .replace('http://', 'ws://')
      .replace('https://', 'wss://');

    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${wsUrl}/ws/events`);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'NEW_REPORT' && msg.report) {
            const newItem: FeedItem = {
              id: msg.report.id || `ws-${Date.now()}`,
              source: 'citizen' as FeedSourceType,
              sourceLabel: 'Citizen report',
              message: msg.report.text || msg.report.raw_text || 'New report received',
              time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }),
            };
            setFeedItems((prev) => [newItem, ...prev.slice(0, 9)]);
          }
        } catch {
          // ignore malformed WS messages
        }
      };
    } catch {
      console.warn('[INDRA] WebSocket connection failed (non-fatal)');
    }

    return () => {
      if (ws) ws.close();
    };
  }, []);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.6 }}
    >
      <Card hover={false} className="h-full" density="compact">
        <CardHeader
          density="compact"
          title={
            <span style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              Live Reports
            </span>
          }
          action={
            <button className="flex items-center gap-1 text-[10px] font-medium text-[#7A8599] hover:text-ink transition-colors">
              View all
              <ArrowRight className="w-3 h-3" />
            </button>
          }
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="custom-scrollbar overflow-y-auto"
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
            const source = (item.source || 'news') as FeedSourceType;
            const sourceStyle = feedSourceConfig[source] || feedSourceConfig.news;
            const abbr = sourceAbbr[source] ?? 'LOG';

            return (
              <motion.div
                key={item.id}
                variants={listItemSlideIn}
                className="flex items-center gap-2 py-1.5 border-b border-[#F0EBE0] last:border-0 px-1 transition-colors hover:bg-[#F7F3EA] rounded"
              >
                {/* Micro source pill */}
                <span
                  className="text-[9px] font-semibold flex-shrink-0 tabular-nums px-1 py-0.5 rounded"
                  style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    color: sourceStyle.color,
                    backgroundColor: `${sourceStyle.color}18`,
                  }}
                >
                  {abbr}
                </span>

                {/* Content — single line */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[10px] font-semibold text-ink flex-shrink-0">
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
