'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  recentEvents,
  severityConfig,
  verificationConfig,
  type RecentEvent,
} from '@/lib/mock-data';
import { fetchEvents, apiEventsToRecentEvents } from '@/lib/api';
import { getRelativeTime } from '@/lib/utils';
import { ArrowRight, MapPin, CheckCircle2, Clock } from 'lucide-react';

export default function RecentEventsList() {
  const [events, setEvents] = useState<RecentEvent[]>(recentEvents);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const apiEvents = await fetchEvents({ time_range: '7d' });
        if (!cancelled && apiEvents.length > 0) {
          setEvents(apiEventsToRecentEvents(apiEvents));
        }
      } catch {
        // mock data already set
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.4 }}
    >
      <Card hover={false} className="h-full">
        <CardHeader
          title="Recent Weather Events"
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
          style={{ maxHeight: '380px' }}
        >
          {events.map((event, index) => {
            const severity = severityConfig[event.severity] || severityConfig.moderate;
            const verification = verificationConfig[event.verification] || verificationConfig['under-review'];

            return (
              <motion.div
                key={event.id}
                variants={listItemSlideIn}
                className="flex items-center gap-3 py-3 border-b border-slate-50 last:border-0 hover:bg-slate-50/50 rounded-lg px-1 transition-colors cursor-pointer"
              >
                {/* Thumbnail */}
                <div
                  className="w-14 h-14 rounded-xl flex-shrink-0 flex items-center justify-center"
                  style={{ background: event.imageGradient }}
                >
                  <MapPin className="w-5 h-5 text-white/80" />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <p className="text-sm font-semibold text-text-primary truncate">
                      {event.city}, {event.state}
                    </p>
                    <Badge variant={event.severity} animated={index === 0}>
                      {severity.label}
                    </Badge>
                  </div>
                  <p className="text-xs text-text-secondary">{event.eventType}</p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[10px] text-text-muted flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {getRelativeTime(event.timestamp)}
                    </span>
                  </div>
                </div>

                {/* Verification */}
                <div className="flex-shrink-0">
                  <span
                    className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full"
                    style={{
                      backgroundColor: verification.bg,
                      color: verification.textColor,
                    }}
                  >
                    {event.verification === 'verified' ? (
                      <CheckCircle2 className="w-3 h-3" />
                    ) : (
                      <Clock className="w-3 h-3" />
                    )}
                    {verification.label}
                  </span>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </Card>
    </motion.div>
  );
}
