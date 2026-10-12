'use client';

/**
 * GeoHeatmapSummaryCard
 *
 * Tab 3 — Geo Risk.
 * Shows summary statistics from the H3 heatmap API: top hot cells,
 * total cells with activity, and a window selector (24h / 48h / 7d).
 *
 * Data source: GET /api/geo/heatmap?window=24h (fetchGeoHeatmap)
 *
 * A full Leaflet map is NOT loaded here to avoid the heavy bundle.
 * The "View on Live Map →" link navigates to /live-map.
 */

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Flame, ArrowRight } from 'lucide-react';
import { fetchGeoHeatmap, type GeoHeatmapResponse, ApiError } from '@/lib/api';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { useTranslation } from '@/lib/i18n/useTranslation';

type Window = '24h' | '48h' | '7d';

const WINDOWS: { key: Window; label: string }[] = [
  { key: '24h', label: '24 h' },
  { key: '48h', label: '48 h' },
  { key: '7d',  label: '7 d' },
];

export default function GeoHeatmapSummaryCard({ refreshTick }: { refreshTick: number }) {
  const { t } = useTranslation();
  const [window, setWindow] = useState<Window>('24h');
  const [data, setData] = useState<GeoHeatmapResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchGeoHeatmap({ window })
      .then((d) => { if (!cancelled) { setData(d); setError(null); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err); setLoading(false); } });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window, refreshTick]);

  const topCells = data?.cells
    ? [...data.cells].sort((a, b) => b.report_count - a.report_count).slice(0, 5)
    : [];
  const maxCount = topCells[0]?.report_count ?? 1;
  const totalActive = data?.cells?.filter((c) => c.report_count > 0).length ?? 0;

  return (
    <div className="bg-[#FDFAF5] p-5 rounded-xl border border-[#E8E2D4] shadow-sm flex flex-col gap-4">

      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3
            className="text-sm font-bold text-[#1B2432] flex items-center gap-2"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            <Flame className="w-4 h-4 text-orange-500" />
            {t('analytics.geo_heatmap_title')}
          </h3>
          <p className="text-[11px] text-[#7A8599] mt-0.5">
            {t('analytics.geo_heatmap_subtitle')}
          </p>
        </div>

        {/* Window selector */}
        <div className="flex items-center gap-1 bg-[#F0EBE0] p-0.5 rounded-lg">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              type="button"
              onClick={() => setWindow(w.key)}
              className={`text-[11px] font-semibold px-2.5 py-1 rounded-md transition-all ${
                window === w.key
                  ? 'bg-white text-[#1B2432] shadow-sm'
                  : 'text-[#7A8599] hover:text-[#1B2432]'
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats row */}
      {data && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-[#F7F3EA] rounded-xl p-3 text-center">
            <div
              className="text-xl font-bold tabular-nums text-[#1B2432]"
              style={{ fontFamily: 'JetBrains Mono, monospace' }}
            >
              {totalActive}
            </div>
            <div className="text-[10px] text-[#7A8599] mt-0.5">active cells</div>
          </div>
          <div className="bg-[#F7F3EA] rounded-xl p-3 text-center">
            <div
              className="text-xl font-bold tabular-nums text-[#1B2432]"
              style={{ fontFamily: 'JetBrains Mono, monospace' }}
            >
              {data.cells.reduce((s, c) => s + c.report_count, 0).toLocaleString('en-IN')}
            </div>
            <div className="text-[10px] text-[#7A8599] mt-0.5">total reports</div>
          </div>
          <div className="bg-[#F7F3EA] rounded-xl p-3 text-center">
            <div
              className="text-xl font-bold tabular-nums text-[#1B2432]"
              style={{ fontFamily: 'JetBrains Mono, monospace' }}
            >
              {data.resolution}
            </div>
            <div className="text-[10px] text-[#7A8599] mt-0.5">H3 resolution</div>
          </div>
        </div>
      )}

      {/* Content */}
      {loading && !data ? (
        <div className="h-40 animate-pulse bg-[#F0EBE0] rounded-xl" />
      ) : error && !data ? (
        <ErrorState
          label="heatmap data"
          error={
            error instanceof ApiError && error.status === 404
              ? 'GET /api/geo/heatmap is not available on this backend version.'
              : error
          }
          compact
        />
      ) : data && totalActive === 0 ? (
        <EmptyState
          title="No heatmap activity in this window"
          hint="Reports are still being collected or this window is quiet."
          compact
        />
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-[#7A8599] uppercase tracking-wide">
            Top 5 Hot Cells
          </div>
          {topCells.map((cell, i) => {
            const pct = Math.max(4, (cell.report_count / maxCount) * 100);
            return (
              <div key={cell.h3} className="flex items-center gap-3">
                <span
                  className="text-[10px] font-bold text-[#7A8599] w-4 text-right shrink-0"
                >
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between mb-0.5">
                    <span
                      className="text-[10px] font-mono text-[#4A5568] truncate"
                      title={cell.h3}
                    >
                      {cell.h3}
                    </span>
                    <span className="text-[10px] font-mono font-bold text-[#1B2432] ml-2">
                      {cell.report_count}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[#E8E2D4] overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: i === 0 ? '#DC2626' : i === 1 ? '#F97316' : '#F59E0B',
                      }}
                    />
                  </div>
                  <div className="text-[9px] text-[#94A3B8] mt-0.5">
                    {cell.lat.toFixed(4)}, {cell.lng.toFixed(4)}
                    {cell.linked_report_count > 0 && ` · ${cell.linked_report_count} fused`}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Link to live map */}
      <Link
        href="/live-map"
        className="flex items-center justify-center gap-1.5 text-xs font-semibold text-[#2563EB] hover:text-[#1D4ED8] transition-colors mt-1 border border-[#E8E2D4] rounded-xl py-2 hover:bg-[#EFF6FF]"
      >
        {t('analytics.geo_view_map') || 'View on Live Map'}
        <ArrowRight className="w-3.5 h-3.5" />
      </Link>
    </div>
  );
}
