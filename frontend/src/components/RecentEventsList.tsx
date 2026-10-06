'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { fadeSlideUp, staggerContainer, listItemSlideIn } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import {
  severityConfig,
  verificationConfig,
  type RecentEvent,
} from '@/lib/ui-config';
import {
  fetchEvents,
  apiEventsToRecentEvents,
  formatPlace,
  fetchAgencyAlerts,
  type AgencyAlert,
} from '@/lib/api';
import { getRelativeTime, formatAgo } from '@/lib/utils';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { getHazardTile, type HazardIconName } from '@/lib/hazard-tile';
import {
  ArrowRight,
  CircleAlert,
  CloudFog,
  CloudLightning,
  CloudRain,
  Mountain,
  Thermometer,
  Waves,
  Wind,
  type LucideIcon,
} from 'lucide-react';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

// IMD colour code for a CAP severity, as the Early Warnings page shows it.
const WARNING_STYLE: Record<string, { label: string; color: string }> = {
  CRITICAL: { label: 'Red', color: '#DC2626' },
  HIGH: { label: 'Orange', color: '#EA580C' },
  MODERATE: { label: 'Yellow', color: '#CA8A04' },
  ADVISORY: { label: 'Advisory', color: '#059669' },
};



const HAZARD_ICONS: Record<HazardIconName, LucideIcon> = {
  flood: Waves,
  rain: CloudRain,
  thunderstorm: CloudLightning,
  cyclone: Wind,
  fog: CloudFog,
  heatwave: Thermometer,
  landslide: Mountain,
  other: CircleAlert,
};

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
  const { connected } = useIndraWebSocket();
  const { t } = useTranslation();
  const [internalEvents, setInternalEvents] = useState<RecentEvent[]>([]);
  const [internalLoading, setInternalLoading] = useState<boolean>(true);
  const [internalError, setInternalError] = useState<unknown>(null);

  const [alerts, setAlerts] = useState<AgencyAlert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState<boolean>(true);
  const [alertsError, setAlertsError] = useState<unknown>(null);

  const [source, setSource] = useState<'events' | 'warnings'>('events');
  const [sourceChosen, setSourceChosen] = useState(false);

  const isControlled = propEvents !== undefined;
  const events = isControlled ? propEvents : internalEvents;
  const error = isControlled ? propError : internalError;
  const isLoading = propLoading !== undefined ? propLoading : (isControlled ? false : internalLoading);

  // Fetch official warnings from SACHET (IMD, CWC, SDMA)
  useEffect(() => {
    let cancelled = false;
    const loadAlerts = () => {
      fetchAgencyAlerts(20)
        .then((rows) => {
          if (!cancelled) {
            setAlerts(rows);
            setAlertsError(null);
            setAlertsLoading(false);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setAlertsError(err);
            setAlertsLoading(false);
          }
        });
    };
    loadAlerts();
    const id = setInterval(loadAlerts, 120_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // When events are 0 and real agency warnings exist, automatically open on Warnings
  useEffect(() => {
    if (sourceChosen) return;
    if (!isLoading && events.length === 0 && alerts.length > 0) {
      setSource('warnings');
    }
  }, [isLoading, events.length, alerts.length, sourceChosen]);

  useEffect(() => {
    if (isControlled) return;
    let cancelled = false;
    (async () => {
      try {
        const apiEvents = await fetchEvents({ time_range: '7d' });
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

  const activeCount = source === 'warnings' ? alerts.length : events.length;

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.4 }}
      className="h-full min-h-[300px] max-h-[520px] lg:min-h-0 lg:max-h-none flex flex-col"
    >
      <Card hover={false} className="h-full flex flex-col min-h-0 overflow-hidden" density="compact">
        <CardHeader
          density="compact"
          className="flex-shrink-0"
          title={
            <div className="flex items-center gap-2">
              <span style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                {source === 'warnings' ? t('nav.official_warnings') : t('dashboard.recent_events')}
              </span>
              <div className="flex items-center gap-0.5 bg-[#E8E2D4] p-0.5 rounded-sm">
                <button
                  type="button"
                  onClick={() => { setSource('events'); setSourceChosen(true); }}
                  className={`px-1.5 py-0.5 text-[9px] font-mono rounded-xs transition-colors ${
                    source === 'events' ? 'bg-white text-ink font-semibold shadow-2xs' : 'text-[#7A8599] hover:text-ink'
                  }`}
                  title="Citizen-fused events"
                >
                  Events {events.length > 0 ? `(${events.length})` : ''}
                </button>
                <button
                  type="button"
                  onClick={() => { setSource('warnings'); setSourceChosen(true); }}
                  className={`px-1.5 py-0.5 text-[9px] font-mono rounded-xs transition-colors ${
                    source === 'warnings' ? 'bg-white text-ink font-semibold shadow-2xs' : 'text-[#7A8599] hover:text-ink'
                  }`}
                  title="Official IMD / NDMA warnings in force"
                >
                  Warnings {alerts.length > 0 ? `(${alerts.length})` : ''}
                </button>
              </div>
            </div>
          }
          action={
            <Link
              href={source === 'warnings' ? '/alerts' : '/events'}
              className="flex items-center gap-1 text-[10px] font-medium text-[#7A8599] hover:text-ink transition-colors"
            >
              {t('common.view_all')}
              <ArrowRight className="w-3 h-3" />
            </Link>
          }
        />

        {source === 'events' && isLoading ? (
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
        ) : source === 'events' && error ? (
          <div className="flex-1 min-h-0 flex items-center justify-center">
            <ErrorState label="recent events" error={error} compact />
          </div>
        ) : source === 'events' && events.length === 0 ? (
          <div className="flex-1 min-h-0 flex flex-col items-center justify-center p-3 text-center">
            <EmptyState
              title={t('chart.no_events_range')}
              hint={t('dashboard.no_events')}
              compact
              className="py-2"
            />
            {alerts.length > 0 && (
              <button
                type="button"
                onClick={() => { setSource('warnings'); setSourceChosen(true); }}
                className="mt-1 text-[11px] font-medium text-blue-700 hover:text-blue-900 underline"
              >
                View {alerts.length} live official warnings in force →
              </button>
            )}
          </div>
        ) : source === 'events' ? (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="flex-1 min-h-0 space-y-0.5 custom-scrollbar overflow-y-auto scroll-smooth pr-1"
          >
            {events.map((event) => {
              const severity = severityConfig[event.severity] || severityConfig.unrated;
              const verification = verificationConfig[event.verification] || verificationConfig['under-review'];
              const isSelected = selectedEventId === event.id;
              const spine = spineColor[event.severity] ?? '#9CA3AF';
              const tile = getHazardTile(event.eventType);
              const HazardIcon = HAZARD_ICONS[tile.iconName];

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
                  <div
                    role="img"
                    aria-label={`${event.eventType} icon`}
                    className={`relative w-12 h-9 rounded-md overflow-hidden flex-shrink-0 flex items-center justify-center border border-[#E8E2D4] shadow-2xs transition-all ${
                      isSelected ? 'ring-1.5 ring-blue-500' : ''
                    }`}
                    style={{ background: tile.gradient }}
                  >
                    <HazardIcon className="w-4 h-4 text-white/90" aria-hidden="true" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1.5">
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
                        {t.status(event.verification)}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] text-[#7A8599] truncate font-medium">{t.hazard(event.eventType)}</span>
                      <span
                        className="text-[9px] font-semibold flex-shrink-0"
                        style={{ color: severity.color }}
                      >
                        {t.severity(event.severity)}
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
        ) : alertsLoading ? (
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
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : alertsError ? (
          <div className="flex-1 min-h-0 flex items-center justify-center">
            <ErrorState label="official warnings" error={alertsError} compact />
          </div>
        ) : alerts.length === 0 ? (
          <div className="flex-1 min-h-0 flex flex-col items-center justify-center p-3 text-center">
            <EmptyState
              title={t('nav.official_warnings')}
              hint="No official agency warnings currently in force"
              compact
              className="py-2"
            />
          </div>
        ) : (
          /* Live Official Warnings rendered as first-class hazard cards */
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="flex-1 min-h-0 space-y-0.5 custom-scrollbar overflow-y-auto scroll-smooth pr-1"
          >
            {alerts.map((a) => {
              const style = WARNING_STYLE[a.severity ?? ''] ?? { label: 'Unrated', color: '#9CA3AF' };
              const spine = style.color;
              const tile = getHazardTile(a.event || 'other');
              const HazardIcon = HAZARD_ICONS[tile.iconName];
              const isSelected = selectedEventId === `alert-${a.id}`;
              const sevKey = (a.severity || 'moderate').toLowerCase();

              return (
                <motion.div
                  key={a.id}
                  variants={listItemSlideIn}
                  onClick={() => {
                    onSelectEvent?.({
                      id: `alert-${a.id}`,
                      city: a.location_label ?? '',
                      state: '',
                      placeLabel: a.location_label ?? 'Location unresolved',
                      eventType: (a.event || 'other') as any,
                      severity: sevKey as any,
                      verification: 'verified',
                      timestamp: new Date(a.sent_at || Date.now()),
                      imageGradient: tile.gradient,
                    });
                  }}
                  className={`group flex items-center gap-2.5 py-1.5 border-b border-[#F0EBE0] last:border-0 pl-2 pr-1.5 rounded-sm transition-all cursor-pointer ${
                    isSelected ? 'bg-[#F0EBE0]' : 'hover:bg-[#F7F3EA]'
                  }`}
                  style={{ borderLeft: `3px solid ${spine}` }}
                >
                  <div
                    role="img"
                    aria-label={`${a.event || 'Warning'} icon`}
                    className={`relative w-12 h-9 rounded-md overflow-hidden flex-shrink-0 flex items-center justify-center border border-[#E8E2D4] shadow-2xs transition-all ${
                      isSelected ? 'ring-1.5 ring-blue-500' : ''
                    }`}
                    style={{ background: tile.gradient }}
                  >
                    <HazardIcon className="w-4 h-4 text-white/90" aria-hidden="true" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1.5">
                      <p
                        className="text-xs font-medium text-ink truncate"
                        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                      >
                        {a.location_label || 'Location unresolved'}
                      </p>
                      <span
                        className="text-[9px] font-semibold flex-shrink-0"
                        style={{ color: style.color }}
                      >
                        {t.severity(a.severity)}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] text-[#7A8599] truncate font-medium">
                        {a.event ? t.hazard(a.event) : t('nav.official_warnings')}
                      </span>
                      <span className="text-[9px] text-[#7A8599] truncate font-medium">
                        · {a.sender || 'IMD / Agency'}
                      </span>
                      <span
                        className="text-[9px] text-[#B0A898] flex-shrink-0 ml-auto"
                        style={{ fontFamily: 'JetBrains Mono, monospace' }}
                      >
                        {formatAgo(a.sent_at)}
                      </span>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </motion.div>
        )}

        {/* Status footer: live state with accurate counter and source */}
        <div className="mt-auto pt-1.5 pb-0.5 border-t border-[#F0EBE0] flex items-center justify-between text-[10px] text-[#7A8599] flex-shrink-0">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-500 animate-pulse' : 'bg-[#B8873A]'}`}
              title={connected ? 'Live updates connected' : 'Live updates offline — reconnecting'}
            />
            {source === 'warnings' ? (
              <>
                <span className="font-mono tabular-nums font-semibold text-ink">{alerts.length}</span>
                <span>{t('nav.official_warnings')}</span>
                <span className="text-[#A0988A] font-mono text-[9px]"><bdi>· Live</bdi></span>
              </>
            ) : (
              <>
                <span className="font-mono tabular-nums font-semibold text-ink">{events.length}</span>
                <span>{t('chart.events')}</span>
                <span className="text-[#A0988A] font-mono text-[9px]"><bdi>· 7d</bdi></span>
              </>
            )}
          </span>
          <span className="text-[9px] uppercase tracking-wider text-[#A0988A] flex items-center gap-1">
            {source === 'warnings' ? (
              'NDMA SACHET · IMD'
            ) : activeCount > 4 ? (
              <>
                <span>{t('chart.scroll_more')}</span>
                <span className="text-[10px]">↓</span>
              </>
            ) : connected ? (
              t('chart.live_from_api')
            ) : (
              'From the INDRA API · updates paused'
            )}
          </span>
        </div>
      </Card>
    </motion.div>
  );
}
