'use client';

/**
 * PipelineThroughputPanel
 *
 * Tab 4 — AI Pipeline.
 * Displays the ML pipeline's live telemetry metrics as a 2×3 tile grid:
 *   - Fused Rate
 *   - Duplicate Rate
 *   - Verification Rate
 *   - Flagged Reports
 *   - Unfused Reports
 *   - Total Reports
 *
 * Data is passed as a prop (telemetry) from the parent tab container,
 * which fetches fetchMlObservatory() once and distributes the result.
 *
 * Also renders the consensus_weights table.
 */

import React from 'react';
import {
  GitMerge, Copy, CheckCircle, Flag, Unlink, Database, ShieldCheck,
} from 'lucide-react';
import type { MlObservatoryData } from '@/lib/api';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { useThemeTokens } from '@/lib/useThemeTokens';

// ─── Metric tile ──────────────────────────────────────────────────────────────

interface MetricTileProps {
  label: string;
  value: string;
  sub: string;
  icon: React.ElementType;
  accentColor: string;
}

function MetricTile({ label, value, sub, icon: Icon, accentColor }: MetricTileProps) {
  return (
    <div className="bg-surface rounded-xl border border-border p-4 flex flex-col gap-1 shadow-2xs relative overflow-hidden hover:shadow-md hover:-translate-y-0.5 transition-all duration-200">
      <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-xl" style={{ backgroundColor: accentColor }} />
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        <span className="font-medium">{label}</span>
        <Icon className="w-4 h-4" style={{ color: accentColor }} />
      </div>
      <div className="text-2xl font-bold tabular-nums font-mono text-text">
        {value}
      </div>
      <div className="text-[10px] text-text-muted">{sub}</div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

interface Props {
  telemetry: MlObservatoryData['live_telemetry'];
  weights: MlObservatoryData['consensus_weights'];
}

export default function PipelineThroughputPanel({ telemetry, weights }: Props) {
  const { t } = useTranslation();
  const tokens = useThemeTokens();
  const {
    total_reports,
    fused_reports,
    unfused_reports,
    duplicate_reports,
    verified_events,
    flagged_reports,
  } = telemetry;

  const fusedRate = total_reports > 0
    ? `${Math.round((fused_reports / total_reports) * 100)}%`
    : '—';
  const dupRate = total_reports > 0
    ? `${Math.round((duplicate_reports / total_reports) * 100)}%`
    : '—';
  const verifyRate = fused_reports > 0
    ? `${Math.round((verified_events / fused_reports) * 100)}%`
    : '—';

  const tiles: MetricTileProps[] = [
    {
      label: t('analytics.ai_fused_rate') || 'Fused Rate',
      value: fusedRate,
      sub: `${fused_reports.toLocaleString('en-IN')} of ${total_reports.toLocaleString('en-IN')} reports linked to an event`,
      icon: GitMerge,
      accentColor: tokens.status.verified,
    },
    {
      label: t('analytics.ai_duplicate_rate') || 'Duplicate Rate',
      value: dupRate,
      sub: `${duplicate_reports.toLocaleString('en-IN')} duplicates caught by the pipeline`,
      icon: Copy,
      accentColor: '#8B5CF6',
    },
    {
      label: t('analytics.ai_verification_rate') || 'Verification Rate',
      value: verifyRate,
      sub: `${verified_events.toLocaleString('en-IN')} of ${fused_reports.toLocaleString('en-IN')} clusters verified`,
      icon: CheckCircle,
      accentColor: '#2563EB',
    },
    {
      label: t('analytics.ai_flagged') || 'Flagged',
      value: flagged_reports.toLocaleString('en-IN'),
      sub: 'Reports flagged for misinformation review',
      icon: Flag,
      accentColor: tokens.severity.critical,
    },
    {
      label: t('analytics.ai_unfused') || 'Unfused',
      value: unfused_reports.toLocaleString('en-IN'),
      sub: 'Reports still unlinked — no matching cluster yet',
      icon: Unlink,
      accentColor: tokens.severity.high,
    },
    {
      label: 'Total Reports',
      value: total_reports.toLocaleString('en-IN'),
      sub: 'All-time reports ingested by the platform',
      icon: Database,
      accentColor: tokens.brand,
    },
  ];

  return (
    <div className="space-y-6">

      {/* ── Metric tiles ──────────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-bold text-text mb-3 font-display">
          {t('analytics.ai_throughput_title') || 'Pipeline Throughput Metrics'}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tiles.map((tile) => (
            <MetricTile key={tile.label} {...tile} />
          ))}
        </div>
      </div>

      {/* ── Verification Weights Table ─────────────────────────────────────── */}
      {weights && weights.length > 0 && (
        <div className="bg-surface rounded-xl border border-border shadow-2xs overflow-hidden">
          <div className="p-5 border-b border-border">
            <h3 className="text-sm font-bold text-text flex items-center gap-2 font-display">
              <ShieldCheck className="w-4 h-4 text-brand" />
              {t('analytics.ai_weights_title') || 'Consensus Scoring Weights'}
            </h3>
            <p className="text-[11px] text-text-muted mt-0.5">
              {t('analytics.ai_weights_subtitle') || 'Deterministic factors used to compute the AI confidence score'}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-surface-raised text-text-muted">
                  <th className="text-left px-4 py-2.5 font-semibold">Factor</th>
                  <th className="text-right px-4 py-2.5 font-semibold">Weight</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Metric</th>
                  <th className="text-center px-4 py-2.5 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {weights.map((w) => (
                  <tr key={w.factor} className="border-t border-border hover:bg-surface-raised/50 transition-colors">
                    <td className="px-4 py-2.5 font-medium text-text">{w.factor}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="font-mono font-bold text-brand">
                        {(w.weight * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-text-muted">{w.metric}</td>
                    <td className="px-4 py-2.5 text-center">
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                          w.status === 'active'
                            ? 'bg-status-verified/15 text-status-verified'
                            : w.status === 'experimental'
                            ? 'bg-severity-high/15 text-severity-high'
                            : 'bg-surface-raised text-text-muted'
                        }`}
                      >
                        {w.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
