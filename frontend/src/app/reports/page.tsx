'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
  Camera,
  Download,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  CheckCircle2,
  Eye,
  Database,
} from 'lucide-react';
import Link from 'next/link';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import ReportSubmissionModal from '@/components/ReportSubmissionModal';
import ForensicMediaModal from '@/components/ForensicMediaModal';
import { ErrorState } from '@/components/ui/empty-state';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchFieldReports, formatPlace, triggerRecluster, type FieldReport } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import { formatAgo, formatIst } from '@/lib/utils';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { useRoleContext } from '@/lib/useRoleContext';

const WINDOW_HOURS = 720;

type SourceFilter = 'all' | 'CITIZEN_APP' | 'OFFICIAL_DISPATCH' | 'SOCIAL_MEDIA' | 'NEWS_MEDIA';
type StatusFilter = 'all' | 'pending' | 'in_event' | 'duplicate' | 'held' | 'stale';

function statusOf(r: FieldReport): Exclude<StatusFilter, 'all'> {
  if (r.duplicate) return 'duplicate';
  if (r.fused) return 'in_event';
  return 'pending';
}

const STATUS_STYLE: Record<Exclude<StatusFilter, 'all'>, { label: string; cls: string }> = {
  pending: { label: 'Awaiting corroboration', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  in_event: { label: 'Part of an event', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  duplicate: { label: 'Duplicate, suppressed', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
  held: { label: 'Held / Context-only', cls: 'bg-purple-50 text-purple-700 border-purple-200' },
  stale: { label: 'Stale (>48h)', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
};

const SOURCE_STYLE: Record<string, { label: string; cls: string }> = {
  CITIZEN_APP: { label: 'CITIZEN REPORT', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  OFFICIAL_DISPATCH: { label: 'OFFICIAL DISPATCH', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  SOCIAL_MEDIA: { label: 'FEDIVERSE / SOCIAL', cls: 'bg-purple-50 text-purple-700 border-purple-200' },
  NEWS_MEDIA: { label: 'NEWS FEED', cls: 'bg-slate-50 text-slate-700 border-slate-200' },
};

export default function ReportsPage() {
  const { t } = useTranslation();
  const { effectiveRole } = useRoleContext();
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
  const [selectedReportForForensics, setSelectedReportForForensics] = useState<FieldReport | null>(null);
  const [isReclustering, setIsReclustering] = useState(false);
  const [reclusterFeedback, setReclusterFeedback] = useState<string | null>(null);
  const { connected, subscribe } = useIndraWebSocket();

  const isCitizen = effectiveRole === 'CITIZEN';
  const isAdminOrAnalyst = effectiveRole === 'ADMIN' || effectiveRole === 'ANALYST';

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
    const c = { pending: 0, in_event: 0, duplicate: 0, held: 0, stale: 0 };
    reports.forEach((r) => {
      const s = statusOf(r);
      c[s] = (c[s] || 0) + 1;
    });
    return c;
  }, [reports]);

  const filtered = useMemo(() => {
    return reports.filter((r) => {
      if (sourceFilter !== 'all' && r.source_type !== sourceFilter) return false;
      if (statusFilter !== 'all' && statusOf(r) !== statusFilter) return false;
      // In citizen perspective, suppress duplicates to protect signal clarity
      if (isCitizen && r.duplicate) return false;

      if (!search) return true;
      const q = search.toLowerCase();
      return [r.text, r.district, r.state, r.source_type, r.event_code]
        .some((v) => (v ?? '').toLowerCase().includes(q));
    });
  }, [reports, sourceFilter, statusFilter, isCitizen, search]);

  const handleRecluster = async () => {
    setIsReclustering(true);
    setReclusterFeedback(null);
    try {
      const res = await triggerRecluster();
      setReclusterFeedback(`DBSCAN Complete: ${res.clusters_count} clusters formed across ${res.reports_clustered} reports.`);
      await loadReports();
    } catch (err: any) {
      setReclusterFeedback(`Recluster failed: ${err.message}`);
    } finally {
      setIsReclustering(false);
      setTimeout(() => setReclusterFeedback(null), 5000);
    }
  };

  const handleExport = (format: 'csv' | 'geojson') => {
    const url = `/api/reports/export?format=${format}`;
    window.open(url, '_blank');
  };

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
                {effectiveRole === 'ADMIN' && (
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-purple-500/20 text-purple-200 border border-purple-500/30">
                    OMNI INGESTION ACTIVE
                  </span>
                )}
                {isCitizen && (
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-200 border border-emerald-500/30">
                    CITIZEN PRIVACY MODE (DPDP FUZZED)
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-300">
                {isCitizen
                  ? 'Public citizen reports and official emergency advisories across verified incident zones.'
                  : 'Full omni-stream: citizen uploads, official dispatches, Fediverse signals, news RSS, duplicates, and unclustered items.'}
              </p>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
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
                <span>{connected ? 'Live' : 'Paused'}</span>
              </div>
              <button
                onClick={() => {
                  setLoading(true);
                  loadReports();
                }}
                disabled={loading}
                className="p-2 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Refresh reports"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Admin Omni Command Bar (Visible to Admin & Analyst) */}
          {isAdminOrAnalyst && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-white border border-[#E8E2D4] p-3 rounded-2xl shadow-xs flex flex-col sm:flex-row items-center justify-between gap-3"
            >
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-lg bg-purple-50 text-purple-700">
                  <Database className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-xs font-bold text-[#1B2432] block">Omni Ingestion Highway</span>
                  <span className="text-[10px] text-[#7A8599]">
                    100% Raw Stream · Spatial DBSCAN Engine · Cryptographic Export
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {reclusterFeedback && (
                  <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-lg border border-emerald-200">
                    {reclusterFeedback}
                  </span>
                )}
                {effectiveRole === 'ADMIN' && (
                  <button
                    onClick={handleRecluster}
                    disabled={isReclustering}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#7C3AED] text-white text-xs font-semibold hover:bg-[#6D28D9] transition-all shadow-xs disabled:opacity-50"
                  >
                    {isReclustering ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                    {isReclustering ? 'Clustering…' : 'Recluster Queue'}
                  </button>
                )}
                <button
                  onClick={() => handleExport('csv')}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-[#F3F4F6] text-[#1B2432] text-xs font-semibold hover:bg-[#E5E7EB] border border-[#E8E2D4] transition-colors"
                >
                  <Download className="w-3.5 h-3.5" /> CSV Export
                </button>
                <button
                  onClick={() => handleExport('geojson')}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-[#F3F4F6] text-[#1B2432] text-xs font-semibold hover:bg-[#E5E7EB] border border-[#E8E2D4] transition-colors"
                >
                  <Download className="w-3.5 h-3.5" /> GeoJSON
                </button>
              </div>
            </motion.div>
          )}

          {/* Search and Filters */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            <div className="relative w-full lg:max-w-md">
              <Search className="w-4 h-4 text-[#A0988A] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search report text, district, docket, state, hazard..."
                className="w-full pl-9 pr-3 py-2 bg-white border border-[#E8E2D4] rounded-xl text-xs text-[#1B2432] placeholder-[#A0988A] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 shadow-2xs transition-all"
              />
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Source Filter */}
              <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-white border border-[#E8E2D4]" role="group" aria-label="Source">
                {([
                  ['all', 'All Sources'],
                  ['CITIZEN_APP', 'Citizen App'],
                  ['OFFICIAL_DISPATCH', 'Official'],
                  ...(!isCitizen
                    ? [
                        ['SOCIAL_MEDIA', 'Fediverse'],
                        ['NEWS_MEDIA', 'News RSS'],
                      ]
                    : []),
                ] as Array<[SourceFilter, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setSourceFilter(key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
                      sourceFilter === key ? 'bg-[#1B2432] text-white font-semibold' : 'text-[#7A8599] hover:text-[#1B2432]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* Status Filter */}
              <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-white border border-[#E8E2D4]" role="group" aria-label="Status">
                {([
                  ['all', `All · ${reports.length}`],
                  ['pending', `Pending · ${counts.pending}`],
                  ['in_event', `In Event · ${counts.in_event}`],
                  ...(!isCitizen
                    ? [
                        ['duplicate', `Duplicates · ${counts.duplicate}`],
                      ]
                    : []),
                ] as Array<[StatusFilter, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setStatusFilter(key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
                      statusFilter === key ? 'bg-[#1B2432] text-white font-semibold' : 'text-[#7A8599] hover:text-[#1B2432]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Reports Grid */}
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
                const displayLat = isCitizen ? r.lat.toFixed(2) : r.lat.toFixed(4);
                const displayLng = isCitizen ? r.lng.toFixed(2) : r.lng.toFixed(4);

                return (
                  <motion.div
                    key={r.id}
                    variants={fadeIn}
                    className="bg-white rounded-2xl border border-[#E8E2D4] p-5 shadow-2xs hover:shadow-md transition-all flex flex-col justify-between"
                  >
                    <div>
                      {/* Card Header */}
                      <div className="flex items-start justify-between gap-2 mb-3">
                        <div className="flex items-center gap-2 flex-wrap min-w-0">
                          <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-md border ${src.cls}`}>
                            {src.label}
                          </span>
                          <span className="text-xs text-[#4A5568] flex items-center gap-1 font-medium min-w-0">
                            <MapPin className="w-3 h-3 text-[#A0988A] flex-shrink-0" />
                            <span className="truncate">{formatPlace(r.district, r.state)}</span>
                          </span>
                        </div>
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${status.cls}`}>
                          {status.label}
                        </span>
                      </div>

                      {/* Text */}
                      <p className="text-xs text-[#4A5568] bg-[#F7F3EA] p-3 rounded-xl border border-[#E8E2D4] leading-relaxed mb-3">
                        &ldquo;{r.text || 'No message text'}&rdquo;
                      </p>

                      {/* Depth & Event Details */}
                      <div className="flex items-center gap-3 flex-wrap text-[11px] text-[#7A8599] mb-3">
                        {r.depth_cm != null && (
                          <span className="flex items-center gap-1">
                            <Droplets className="w-3.5 h-3.5 text-blue-500" />
                            Depth: ~{r.depth_cm} cm
                          </span>
                        )}
                        {r.fused && (
                          <Link href="/events" className="flex items-center gap-1 text-emerald-700 hover:underline font-semibold">
                            <Layers className="w-3.5 h-3.5" />
                            {r.event_code ? `Event ${r.event_code}` : 'Open Event'}
                          </Link>
                        )}
                        {r.credibility_score != null && !isCitizen && (
                          <span className="font-mono text-emerald-700">
                            Trust: {Math.round(r.credibility_score * 100)}%
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Card Footer */}
                    <div className="pt-2 border-t border-[#F0EBE0] flex items-center justify-between gap-2 text-xs text-[#7A8599]">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono">
                          {displayLat}, {displayLng}
                        </span>
                        {isCitizen && (
                          <span className="text-[9px] text-[#7A8599] bg-[#E8E2D4]/50 px-1 rounded">
                            Fuzzed
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        {/* Forensic Inspector Trigger */}
                        {!isCitizen && (
                          <button
                            onClick={() => setSelectedReportForForensics(r)}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 transition-colors"
                            title="Inspect forensic metadata, EXIF, and media"
                          >
                            <Camera className="w-3 h-3" />
                            Forensics
                          </button>
                        )}

                        <div className="flex items-center gap-1 font-mono text-[11px] text-[#A0988A]" title={r.created_at ?? ''}>
                          <Clock className="w-3 h-3" />
                          <span>{formatAgo(r.created_at)}</span>
                        </div>
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

        {/* Forensic Media & Metadata Inspector Modal */}
        <ForensicMediaModal
          report={selectedReportForForensics}
          open={!!selectedReportForForensics}
          onClose={() => setSelectedReportForForensics(null)}
        />
      </div>
    </div>
  );
}
