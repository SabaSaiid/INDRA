'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  liveFeedItems,
  feedSourceConfig,
  type FeedSourceType,
  type FeedItem,
} from '@/lib/mock-data';
import { fetchRecentFeed } from '@/lib/api';
import { ArrowRight } from 'lucide-react';

// Source label abbreviation
const sourceAbbr: Record<FeedSourceType, string> = {
  citizen: 'CTZN',
  social:  'SOCI',
  imd:     'IMD',
  news:    'NEWS',
};

export default function LiveFeed() {
  const [feedItems, setFeedItems] = useState<FeedItem[]>(liveFeedItems);

  // Fetch live feed data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRecentFeed(10);
        if (!cancelled && data.length > 0) {
          setFeedItems(data);
        }
      } catch {
        // mock data already set
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
      <Card hover={false} className="h-full">
        <CardHeader
          title={
            <span style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              Live Reports
            </span>
          }
          action={
            <button className="flex items-center gap-1 text-xs font-medium text-[#7A8599] hover:text-ink transition-colors">
              View all
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          }
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="custom-scrollbar overflow-y-auto"
          style={{ maxHeight: '220px' }}
        >
          {feedItems.map((item) => {
            const source = (item.source || 'news') as FeedSourceType;
            const sourceStyle = feedSourceConfig[source] || feedSourceConfig.news;
            const abbr = sourceAbbr[source] ?? 'LOG';

            return (
              <motion.div
                key={item.id}
                variants={listItemSlideIn}
                className="flex items-start gap-2.5 py-2.5 border-b border-[#F0EBE0] last:border-0 px-1 transition-colors hover:bg-[#F7F3EA] rounded"
              >
                {/* Source tag in JetBrains Mono */}
                <span
                  className="text-[10px] font-medium mt-0.5 flex-shrink-0 tabular-nums"
                  style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    color: sourceStyle.color,
                  }}
                >
                  {abbr}
                </span>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 mb-0.5">
                    <span className="text-xs font-semibold text-ink">
                      {item.sourceLabel}
                    </span>
                    <span
                      className="text-[10px] text-[#B0A898] tabular-nums"
                      style={{ fontFamily: 'JetBrains Mono, monospace' }}
                    >
                      {item.time}
                    </span>
                  </div>
                  <p className="text-xs text-[#4A5568] leading-relaxed line-clamp-2">
                    {item.message}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </Card>
    </motion.div>
  );
}
