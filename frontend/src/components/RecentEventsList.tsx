'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  recentEvents,
  severityConfig,
  verificationConfig,
  type RecentEvent,
} from '@/lib/mock-data';
import { fetchEvents, apiEventsToRecentEvents } from '@/lib/api';
import { getRelativeTime } from '@/lib/utils';
import { ArrowRight } from 'lucide-react';

// Spine color per severity (Low Pressure palette)
const spineColor: Record<string, string> = {
  critical: '#8C2F26',
  high:     '#B8873A',
  moderate: '#4A6670',
  low:      '#9CA3AF',
};

export default function RecentEventsList({
  onSelectEvent,
  selectedEventId,
}: {
  onSelectEvent?: (event: RecentEvent) => void;
  selectedEventId?: string;
}) {
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
      <Card hover={false} className="h-full" density="compact">
        <CardHeader
          density="compact"
          title={
            <span style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              Recent Events
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
          className="space-y-0 custom-scrollbar overflow-y-auto"
          style={{ maxHeight: '310px' }}
        >
          {events.map((event) => {
            const severity = severityConfig[event.severity] || severityConfig.moderate;
            const verification = verificationConfig[event.verification] || verificationConfig['under-review'];
            const isSelected = selectedEventId === event.id;
            const spine = spineColor[event.severity] ?? '#9CA3AF';

            return (
              <motion.div
                key={event.id}
                variants={listItemSlideIn}
                onClick={() => onSelectEvent?.(event)}
                className={`flex items-start gap-2 py-1.5 border-b border-[#F0EBE0] last:border-0 pl-2.5 pr-1.5 rounded-sm transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-[#F0EBE0]'
                    : 'hover:bg-[#F7F3EA]'
                }`}
                style={{
                  borderLeft: `3px solid ${spine}`,
                }}
              >
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-1.5">
                    {/* Place name */}
                    <p
                      className="text-xs font-medium text-ink truncate"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      {event.city}, {event.state}
                    </p>
                    <span
                      className="text-[9px] font-medium flex-shrink-0"
                      style={{ color: verification.color }}
                    >
                      {verification.label}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[9px] text-[#7A8599] truncate">{event.eventType}</span>
                    <span
                      className="text-[9px] font-semibold flex-shrink-0"
                      style={{ color: severity.color }}
                    >
                      {severity.label}
                    </span>
                    <span
                      className="text-[9px] text-[#B0A898] flex-shrink-0"
                      style={{ fontFamily: 'JetBrains Mono, monospace' }}
                    >
                      {getRelativeTime(event.timestamp)}
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
