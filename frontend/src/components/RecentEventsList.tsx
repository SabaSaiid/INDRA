'use client';

import React, { useEffect, useState } from 'react';
import Image from 'next/image';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  severityConfig,
  verificationConfig,
  type RecentEvent,
} from '@/lib/ui-config';
import { fetchEvents, apiEventsToRecentEvents, formatPlace } from '@/lib/api';
import { getRelativeTime } from '@/lib/utils';
import { getWeatherMedia } from '@/lib/weather-media';
import { ArrowRight } from 'lucide-react';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';

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
  events: propEvents,
  loading: propLoading,
  error: propError,
}: {
  onSelectEvent?: (event: RecentEvent) => void;
  selectedEventId?: string;
  events?: RecentEvent[];
  loading?: boolean;
  error?: unknown;
}) {
  const [internalEvents, setInternalEvents] = useState<RecentEvent[]>([]);
  const [internalLoading, setInternalLoading] = useState<boolean>(true);
  const [internalError, setInternalError] = useState<unknown>(null);

  const isControlled = propEvents !== undefined;
  const events = isControlled ? propEvents : internalEvents;
  const error = isControlled ? propError : internalError;
  const isLoading = propLoading !== undefined ? propLoading : (isControlled ? false : internalLoading);

  useEffect(() => {
    if (isControlled) return;
    let cancelled = false;
    (async () => {
      try {
        const apiEvents = await fetchEvents({ time_range: '7d' });
        // No length check: zero verified events is a fact about the world, not
        // a failed request.
        if (!cancelled) {
          setInternalEvents(apiEventsToRecentEvents(apiEvents));
          setInternalError(null);
        }
      } catch (err) {
        if (!cancelled) setInternalError(err);
      } finally {
        if (!cancelled) setInternalLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isControlled]);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.4 }}
      className="h-full max-h-[318px] flex flex-col min-h-0"
    >
      <Card hover={false} className="h-full max-h-[318px] flex flex-col min-h-0 overflow-hidden" density="compact">
        <CardHeader
          density="compact"
          className="flex-shrink-0"
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

        {isLoading ? (
          <div className="flex-1 min-h-0 space-y-0.5 custom-scrollbar overflow-y-auto pr-0.5">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex items-center gap-2.5 py-1.5 border-b border-[#F0EBE0] last:border-0 pl-2 pr-1.5">
                <div className="w-12 h-9 rounded-md bg-[#E8E2D4] animate-pulse flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-1.5 mb-1">
                    <div className="h-3 w-28 bg-[#E8E2D4] rounded animate-pulse" />
                    <div className="h-2.5 w-14 bg-[#E8E2D4] rounded animate-pulse" />
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-16 bg-[#E8E2D4] rounded animate-pulse" />
                    <div className="h-2.5 w-10 bg-[#E8E2D4] rounded animate-pulse" />
                    <div className="h-2.5 w-12 bg-[#E8E2D4] rounded animate-pulse" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="flex-1 min-h-0 flex items-center justify-center">
            <ErrorState label="recent events" error={error} compact />
          </div>
        ) : events.length === 0 ? (
          <div className="flex-1 min-h-0 flex items-center justify-center">
            <EmptyState
              title="No verified events yet"
              hint="Events appear here once two nearby reports corroborate each other."
              compact
            />
          </div>
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="flex-1 min-h-0 space-y-0.5 custom-scrollbar overflow-y-auto scroll-smooth pr-1"
          >
            {events.map((event) => {
              const severity = severityConfig[event.severity] || severityConfig.moderate;
              const verification = verificationConfig[event.verification] || verificationConfig['under-review'];
              const isSelected = selectedEventId === event.id;
              const spine = spineColor[event.severity] ?? '#9CA3AF';
              const media = getWeatherMedia(event.eventType);

              return (
                <motion.div
                  key={event.id}
                  variants={listItemSlideIn}
                  onClick={() => onSelectEvent?.(event)}
                  className={`group flex items-center gap-2.5 py-1.5 border-b border-[#F0EBE0] last:border-0 pl-2 pr-1.5 rounded-sm transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-[#F0EBE0]'
                      : 'hover:bg-[#F7F3EA]'
                  }`}
                  style={{
                    borderLeft: `3px solid ${spine}`,
                  }}
                >
                  {/* Weather Condition Photo */}
                  <div
                    className={`relative w-12 h-9 rounded-md overflow-hidden flex-shrink-0 bg-[#E8E2D4] border border-[#E8E2D4] shadow-2xs transition-all ${
                      isSelected ? 'ring-1.5 ring-blue-500' : ''
                    }`}
                  >
                    <Image
                      src={media.src}
                      alt={`${media.condition} in ${event.placeLabel ?? formatPlace(event.city, event.state)}`}
                      width={48}
                      height={36}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      unoptimized
                    />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1.5">
                      {/* Place name */}
                      <p
                        className="text-xs font-medium text-ink truncate"
                        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                      >
                        {event.placeLabel ?? formatPlace(event.city, event.state)}
                      </p>
                      <span
                        className="text-[9px] font-medium flex-shrink-0"
                        style={{ color: verification.color }}
                      >
                        {verification.label}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] text-[#7A8599] truncate font-medium">{event.eventType}</span>
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
        )}

        {/* Telemetry Status Footer */}
        <div className="mt-auto pt-1.5 pb-0.5 border-t border-[#F0EBE0] flex items-center justify-between text-[10px] text-[#7A8599] font-mono flex-shrink-0">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>{events.length} active incidents</span>
          </span>
          <span className="text-[9px] uppercase tracking-wider text-[#A0988A] flex items-center gap-1">
            {events.length > 4 ? (
              <>
                <span>Scroll for more</span>
                <span className="text-[10px]">↓</span>
              </>
            ) : (
              'IMD • NDRF Synced'
            )}
          </span>
        </div>
      </Card>
    </motion.div>
  );
}
