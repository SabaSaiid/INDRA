'use client';

/**
 * WarningsEventsAlignment
 *
 * Tab 5 — Hazard Trends.
 * Back-to-back horizontal bar chart comparing:
 *   - Official agency warning count per hazard (left, orange)
 *   - Verified event count per hazard (right, blue)
 *
 * Shows where official warnings align with or diverge from ground-truth events.
 *
 * Data sources:
 *   - GET /api/alerts/agency?limit=200 (fetchAgencyAlerts)
 *   - GET /api/events?limit=200 (fetchEvents)
 */

import React, { useEffect, useState, useMemo } from 'react';
import { AlignJustify } from 'lucide-react';
import { fetchAgencyAlerts, fetchEvents, type AgencyAlert, type ApiEvent, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

interface AlignRow {
  hazard: string;
  warnings: number;
  events: number;
}

function normalizeHazardName(raw: string | null | undefined): string {
  if (!raw) return 'Unknown';
  return raw.trim();
}

export default function WarningsEventsAlignment({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [alerts, setAlerts] = useState<AgencyAlert[] | null>(null);
  const [events, setEvents] = useState<ApiEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchAgencyAlerts(200),
      fetchEvents({ limit: 200 }),
    ])
      .then(([a, e]) => {
        if (!cancelled) { setAlerts(a); setEvents(e); setError(null); }
      })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  const rows: AlignRow[] = useMemo(() => {
    const warnMap = new Map<string, number>();
    const evtMap  = new Map<string, number>();

    (alerts ?? []).forEach((a) => {
      const key = normalizeHazardName(a.event);
      warnMap.set(key, (warnMap.get(key) ?? 0) + 1);
    });
    (events ?? []).forEach((e) => {
      const key = normalizeHazardName(e.eventType);
      evtMap.set(key, (evtMap.get(key) ?? 0) + 1);
    });

    const allKeys = Array.from(new Set([...Array.from(warnMap.keys()), ...Array.from(evtMap.keys())]));
    return Array.from(allKeys)
      .map((hazard) => ({
        hazard,
        warnings: warnMap.get(hazard) ?? 0,
        events:   evtMap.get(hazard) ?? 0,
      }))
      .filter((r) => r.warnings > 0 || r.events > 0)
      .sort((a, b) => (b.warnings + b.events) - (a.warnings + a.events))
      .slice(0, 12);
  }, [alerts, events]);

  const maxVal = useMemo(
    () => Math.max(1, ...rows.map((r) => Math.max(r.warnings, r.events))),
    [rows]
  );

  // ── Loading
  if ((!alerts || !events) && !error) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <div className="h-64 animate-pulse bg-[#F0EBE0] rounded-xl" />
      </div>
    );
  }

  // ── Error
  if (error && !alerts) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <ErrorState label="warnings/events alignment" error={error} compact />
      </div>
    );
  }

  // ── Empty
  if (rows.length === 0) {
    return (
      <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm">
        <EmptyState
          title="No data to compare yet"
          hint="Alignment appears once both agency warnings and verified events are present."
          compact
        />
      </div>
    );
  }

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3
            className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            <AlignJustify className="w-4 h-4 text-purple-500" />
            {t('analytics.hazard_alignment_title') || 'Warnings vs Events Alignment'}
          </h3>
          <p className="text-[11px] text-[#7A8599] mt-0.5">
            {t('analytics.hazard_alignment_subtitle') || 'Official agency warnings (orange) vs. verified ground-truth events (blue) per hazard'}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[#7A8599] shrink-0">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-orange-400" /> Warnings
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-blue-500" /> Events
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {rows.map((row) => {
          const wPct = Math.max(2, (row.warnings / maxVal) * 100);
          const ePct = Math.max(2, (row.events   / maxVal) * 100);
          const label = t.hazard(row.hazard) !== row.hazard ? t.hazard(row.hazard) : row.hazard;
          return (
            <div key={row.hazard} className="flex flex-col gap-0.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-[#1B2432] truncate max-w-[200px]" title={label}>
                  {label}
                </span>
                <div className="flex items-center gap-3 text-[10px] font-mono text-[#4A5568]">
                  <span className="text-orange-500 font-bold">{row.warnings}</span>
                  <span className="text-[#94A3B8]">|</span>
                  <span className="text-blue-500 font-bold">{row.events}</span>
                </div>
              </div>
              {/* Dual bars */}
              <div className="flex flex-col gap-1">
                {/* Warnings bar */}
                <div className="flex items-center gap-2">
                  <span className="text-[9px] text-[#7A8599] w-12 text-right shrink-0">warn</span>
                  <div className="flex-1 h-2 rounded-full bg-[#E8E2D4] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-orange-400 transition-all duration-500"
                      style={{ width: `${wPct}%` }}
                    />
                  </div>
                </div>
                {/* Events bar */}
                <div className="flex items-center gap-2">
                  <span className="text-[9px] text-[#7A8599] w-12 text-right shrink-0">event</span>
                  <div className="flex-1 h-2 rounded-full bg-[#E8E2D4] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all duration-500"
                      style={{ width: `${ePct}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-[#7A8599] border-t border-[#E8E2D4] pt-2">
        Agency warnings: {alerts?.length ?? 0} most recent · Events: {events?.length ?? 0} most recent
      </p>
    </div>
  );
}
