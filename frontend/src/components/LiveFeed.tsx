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
import { ArrowRight, User, Share2, CloudSun, Newspaper } from 'lucide-react';

const sourceIcons: Record<FeedSourceType, React.ComponentType<{ className?: string }>> = {
  citizen: User,
  social: Share2,
  imd: CloudSun,
  news: Newspaper,
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
          title="Live Reports Feed"
          action={
            <button className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover transition-colors">
              View All
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          }
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="space-y-0 custom-scrollbar overflow-y-auto"
          style={{ maxHeight: '220px' }}
        >
          {feedItems.map((item) => {
            const source = (item.source || 'news') as FeedSourceType;
            const Icon = sourceIcons[source] || Newspaper;
            const sourceStyle = feedSourceConfig[source] || feedSourceConfig.news;

            return (
              <motion.div
                key={item.id}
                variants={listItemSlideIn}
                className="flex items-start gap-3 py-2.5 border-b border-slate-50 last:border-0 hover:bg-slate-50/50 rounded-lg px-1 transition-colors"
              >
                {/* Source icon */}
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{ backgroundColor: sourceStyle.bg }}
                >
                  <span style={{ color: sourceStyle.color }}>
                    <Icon className="w-4 h-4" />
                  </span>
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-semibold text-text-primary">
                      {item.sourceLabel}
                    </span>
                    <span className="text-[10px] text-text-muted tabular-nums">
                      {item.time}
                    </span>
                  </div>
                  <p className="text-xs text-text-secondary leading-relaxed line-clamp-2">
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
