'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  FileText,
  Clock,
  MapPin,
  Search,
  Loader2,
  Send,
  Radio,
  RefreshCw,
  Droplets,
  Layers,
} from 'lucide-react';
import Link from 'next/link';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import ReportSubmissionModal from '@/components/ReportSubmissionModal';
import { ErrorState } from '@/components/ui/empty-state';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchFieldReports, formatPlace, type FieldReport } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { formatAgo, formatIst } from '@/lib/utils';
import { useTranslation } from '@/lib/i18n/useTranslation';

/*
 * The repository of stored reports. It was built on GET /api/feed/recent,
 * which carries no place, no status and only a clock time, so every card said
 * "Citizen report" and a UTC time with no date, the location search could
 * never match, and nothing said whether a report had gone anywhere. It now
 * reads the reports themselves, fused and duplicate ones included, for 30 days.
 */

const WINDOW_HOURS = 720;

type SourceFilter = 'all' | 'CITIZEN_APP' | 'OFFICIAL_DISPATCH';
type StatusFilter = 'all' | 'pending' | 'in_event' | 'duplicate';

function statusOf(r: FieldReport): Exclude<StatusFilter, 'all'> {
  if (r.duplicate) return 'duplicate';
  if (r.fused) return 'in_event';
  return 'pending';
}

const STATUS_STYLE: Record<Exclude<StatusFilter, 'all'>, { label: string; cls: string }> = {
  pending: { label: 'Awaiting corroboration', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  in_event: { label: 'Part of an event', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  duplicate: { label: 'Duplicate, suppressed', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
};

const SOURCE_STYLE: Record<string, { label: string; cls: string }> = {
  CITIZEN_APP: { label: 'CITIZEN REPORT', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  OFFICIAL_DISPATCH: { label: 'OFFICIAL DISPATCH', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  SOCIAL_MEDIA: { label: 'SOCIAL MEDIA', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  NEWS_MEDIA: { label: 'NEWS', cls: 'bg-slate-50 text-slate-700 border-slate-200' },
};

export default function ReportsPage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [reports, setReports] = useState<FieldReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const { connected, subscribe } = useIndraWebSocket();

  const loadReports = useCallback(async () => {
    try {
      const data = await fetchFieldReports(200, WINDOW_HOURS, false);
      setReports(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  // A new report, or an event that swallowed some, changes this list.
  useEffect(() => {
    return subscribe('reports-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        loadReports();
      }
    });
  }, [subscribe, loadReports]);

  const counts = useMemo(() => {
    const c = { pending: 0, in_event: 0, duplicate: 0 };
    reports.forEach((r) => { c[statusOf(r)] += 1; });
    return c;
  }, [reports]);

  const filtered = reports.filter((r) => {
    if (sourceFilter !== 'all' && r.source_type !== sourceFilter) return false;
    if (statusFilter !== 'all' && statusOf(r) !== statusFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return [r.text, r.district, r.state, r.source_type, r.event_code]
      .some((v) => (v ?? '').toLowerCase().includes(q));
  });

  return (
    <div className="min-h-screen bg-[#F7F3EA] text-[#1B2432]">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileMenuOpen}
        onMobileClose={closeMobile}
      />

      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed ? 'md:ml-[68px]' : 'md:ml-[272px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header */}
          <div className="bg-gradient-to-r from-[#1B2432] via-[#243042] to-[#1B2432] text-white p-5 rounded-2xl border border-[#2D3C52] shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <FileText className="w-5 h-5 text-[#B5482E]" />
                <h1
                  className="text-xl font-bold tracking-wide"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  {t('nav.field_reports')}
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  {reports.length} {t('kpis.citizen_reports')} · 30 DAYS
                </span>
              </div>
              <p className="text-xs text-slate-300">
                Citizen reports and official dispatches as stored. Each is placed in its district and
                checked for duplicates; two that corroborate each other nearby form an event.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={() => setReportModalOpen(true)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#B5482E] text-white text-xs font-semibold hover:bg-[#8C3420] transition-colors shadow-sm"
              >
                <Send className="w-3.5 h-3.5" /> {t('nav.report_incident')}
              </button>
              <div
                className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-mono ${
                  connected
                    ? 'bg-emerald-950/60 border border-emerald-500/30 text-emerald-400'
                    : 'bg-amber-950/40 border border-amber-500/30 text-amber-400'
                }`}
              >
                <Radio className={`w-3.5 h-3.5 ${connected ? 'animate-pulse' : ''}`} />
                <span>{connected ? 'Updates live' : 'Updates paused'}</span>
              </div>
              <button
                onClick={() => {
                  setLoading(true);
                  loadReports();
                }}
                disabled={loading}
                className="p-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Refresh reports"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Search and filters */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            <div className="relative w-full lg:max-w-md">
              <Search className="w-4 h-4 text-[#A0988A] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('nav.search_placeholder')}
                className="w-full pl-9 pr-3 py-2 bg-white border border-[#E8E2D4] rounded-xl text-xs text-[#1B2432] placeholder-[#A0988A] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 shadow-2xs transition-all"
              />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-white border border-[#E8E2D4]" role="group" aria-label="Source">
                {([
                  ['all', t('common.view_all')],
                  ['CITIZEN_APP', t('kpis.citizen_reports')],
                  ['OFFICIAL_DISPATCH', t('nav.official_warnings')],
                ] as Array<[SourceFilter, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setSourceFilter(key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
                      sourceFilter === key ? 'bg-[#1B2432] text-white' : 'text-[#7A8599] hover:text-[#1B2432]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-white border border-[#E8E2D4]" role="group" aria-label="Status">
                {([
                  ['all', `${t('common.view_all')} · ${reports.length}`],
                  ['pending', `${t('kpis.awaiting_review')} · ${counts.pending}`],
                  ['in_event', `${t('nav.incident_events')} · ${counts.in_event}`],
                  ['duplicate', `${t('status.QUARANTINED')} · ${counts.duplicate}`],
                ] as Array<[StatusFilter, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setStatusFilter(key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
                      statusFilter === key ? 'bg-[#1B2432] text-white' : 'text-[#7A8599] hover:text-[#1B2432]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Reports grid */}
          {loading && reports.length === 0 ? (
            <div className="flex items-center justify-center py-24 bg-white rounded-2xl border border-[#E8E2D4]">
              <Loader2 className="w-6 h-6 animate-spin text-[#B5482E]" />
              <span className="ml-2 text-xs font-medium text-[#7A8599]">{t('common.loading')}…</span>
            </div>
          ) : loadError && reports.length === 0 ? (
            <div className="bg-white rounded-2xl border border-[#E8E2D4]">
              <ErrorState label="field reports" error={loadError} onRetry={() => { setLoading(true); loadReports(); }} />
            </div>
          ) : reports.length === 0 ? (
            <div className="text-center py-20 px-4 bg-white rounded-2xl border border-[#E8E2D4]">
              <p className="text-sm font-medium text-[#4A5568]">No reports in the last 30 days</p>
              <p className="text-xs text-[#7A8599] mt-1">
                Reports filed from the citizen app or with Submit Report appear here as they are stored.
              </p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-24 text-[#7A8599] text-xs bg-white rounded-2xl border border-[#E8E2D4]">
              No reports match the current search and filters.
            </div>
          ) : (
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="visible"
              className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4"
            >
              {filtered.map((r) => {
                const src = SOURCE_STYLE[r.source_type] ?? { label: r.source_type, cls: SOURCE_STYLE.NEWS_MEDIA.cls };
                const st = statusOf(r);
                const status = STATUS_STYLE[st];
                const srcLabel = r.source_type === 'CITIZEN_APP'
                  ? t('kpis.citizen_reports')
                  : r.source_type === 'OFFICIAL_DISPATCH'
                  ? t('nav.official_warnings')
                  : src.label;
                const statusLabel = st === 'pending'
                  ? t('kpis.awaiting_review')
                  : st === 'in_event'
                  ? t('nav.incident_events')
                  : t('status.QUARANTINED');
                return (
                  <motion.div
                    key={r.id}
                    variants={fadeIn}
                    className="bg-white rounded-2xl border border-[#E8E2D4] p-5 shadow-2xs hover:shadow-md transition-all flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2 mb-3">
                        <div className="flex items-center gap-2 flex-wrap min-w-0">
                          <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-md border ${src.cls}`}>
                            {srcLabel}
                          </span>
                          <span className="text-xs text-[#4A5568] flex items-center gap-1 font-medium min-w-0">
                            <MapPin className="w-3 h-3 text-[#A0988A] flex-shrink-0" />
                            <span className="truncate">{formatPlace(r.district, r.state)}</span>
                          </span>
                        </div>
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${status.cls}`}>
                          {statusLabel}
                        </span>
                      </div>

                      <p className="text-xs text-[#4A5568] bg-[#F7F3EA] p-3 rounded-xl border border-[#E8E2D4] leading-relaxed mb-3">
                        &ldquo;{r.text || 'No message text'}&rdquo;
                      </p>

                      <div className="flex items-center gap-3 flex-wrap text-[11px] text-[#7A8599] mb-3">
                        {r.depth_cm != null && (
                          <span className="flex items-center gap-1">
                            <Droplets className="w-3.5 h-3.5 text-blue-500" />
                            Water depth read from the text: ~{r.depth_cm} cm
                          </span>
                        )}
                        {r.fused && (
                          <Link href="/events" className="flex items-center gap-1 text-emerald-700 hover:underline">
                            <Layers className="w-3.5 h-3.5" />
                            {r.event_code ? `Event ${r.event_code}` : 'Open its event'}
                          </Link>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-[#F0EBE0] text-xs text-[#7A8599]">
                      <span className="text-[11px] font-mono">
                        {r.lat.toFixed(4)}, {r.lng.toFixed(4)}
                      </span>
                      <div className="flex items-center gap-1 font-mono text-[11px] text-[#A0988A]" title={r.created_at ?? ''}>
                        <Clock className="w-3.5 h-3.5" />
                        <span>{formatIst(r.created_at)} IST · {formatAgo(r.created_at)}</span>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </main>

        {/* Report Submission Modal */}
        <ReportSubmissionModal
          open={reportModalOpen}
          onClose={() => setReportModalOpen(false)}
          onSubmitted={() => loadReports()}
        />
      </div>
    </div>
  );
}
