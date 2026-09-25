'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Shield,
  MapPin,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronRight,
  CloudRain,
  Users,
  Crosshair,
  Camera,
  Activity,
  Eye,
  Lock,
  Hash,
  FileText,
  ArrowUpDown,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  Radio,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  fetchEventDetail,
  fetchEventProvenance,
  formatPlace,
  reviewEvent,
  type EventDetail,
  type ProvenanceData,
  type ProvenanceReport,
  type AuditEntry,
} from '@/lib/api';
import { useSession, hasRole, roleLabel, COMMAND_ROLES, LEDGER_ROLES } from '@/lib/auth';
import { eventReviewState } from '@/lib/eventState';

// Issue 3 fix: per-hazard plausible maximum impact radius (km).
// NOTE TO BACKEND TEAM: impact_radius_km likely has a units bug upstream
// (degrees/meters shown as km, or a squared value). This is a display-only clamp.
const IMPACT_RADIUS_MAX_KM_MODAL: Record<string, number> = {
  'Severe Rainfall':  100,
  'Heavy Rainfall':   100,
  'Thunderstorm':     100,
  'Fog':              100,
  'Strong Winds':     150,
  'Dust Storm':       100,
  'Flood':            300,
  'Urban Flooding':   100,
};
const IMPACT_MODAL_DEFAULT_MAX = 150;

function clampImpactKm(eventId: string, eventType: string | null | undefined, rawKm: number | null | undefined): string {
  if (rawKm == null || rawKm <= 0) return '—';
  const ceiling = IMPACT_RADIUS_MAX_KM_MODAL[eventType ?? ''] ?? IMPACT_MODAL_DEFAULT_MAX;
  if (rawKm > ceiling) {
    console.warn(
      `[INDRA] Event ${eventId}: impact_radius_km=${rawKm.toFixed(1)} exceeds ` +
      `the ${ceiling} km ceiling for "${eventType}". Showing "unavailable" in modal. ` +
      `Likely a units bug upstream — check event-generation code.`
    );
    return 'unavailable';
  }
  return `${rawKm.toFixed(1)} km`;
}

// ── Factor icons & colors ────────────────────────────────────────────────────
const FACTOR_CONFIG: Record<string, { icon: React.ReactNode; color: string; bgColor: string }> = {
  'Weather Station Corroboration': { icon: <CloudRain className="w-4 h-4" />, color: '#2563EB', bgColor: '#EFF6FF' },
  'Report Density Analysis': { icon: <Users className="w-4 h-4" />, color: '#10B981', bgColor: '#D1FAE5' },
  'Spatial Coherence Score': { icon: <Crosshair className="w-4 h-4" />, color: '#8B5CF6', bgColor: '#EDE9FE' },
  'Computer Vision Analysis': { icon: <Camera className="w-4 h-4" />, color: '#F59E0B', bgColor: '#FEF3C7' },
  'Source Reliability Index': { icon: <Shield className="w-4 h-4" />, color: '#EC4899', bgColor: '#FCE7F3' },
  'Anomaly Detection Signal': { icon: <Activity className="w-4 h-4" />, color: '#6366F1', bgColor: '#E0E7FF' },
};

const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: '#FEE2E2', text: '#991B1B', border: '#FCA5A5' },
  HIGH: { bg: '#FEF3C7', text: '#92400E', border: '#FCD34D' },
  MODERATE: { bg: '#DBEAFE', text: '#1E40AF', border: '#93C5FD' },
  ADVISORY: { bg: '#D1FAE5', text: '#065F46', border: '#6EE7B7' },
  critical: { bg: '#FEE2E2', text: '#991B1B', border: '#FCA5A5' },
  high: { bg: '#FEF3C7', text: '#92400E', border: '#FCD34D' },
  moderate: { bg: '#DBEAFE', text: '#1E40AF', border: '#93C5FD' },
  low: { bg: '#D1FAE5', text: '#065F46', border: '#6EE7B7' },
};
/** A severity the API did not send, or one not listed above: grey, never Moderate. */
const UNRATED_STYLE = { bg: '#F3F4F6', text: '#6B7280', border: '#D1D5DB' };

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  AUTO_PUBLISHED: { label: 'Auto-Published', color: '#065F46', bg: '#D1FAE5' },
  PENDING_HUMAN_REVIEW: { label: 'Pending Review', color: '#92400E', bg: '#FEF3C7' },
  QUARANTINED: { label: 'Quarantined', color: '#991B1B', bg: '#FEE2E2' },
  HUMAN_APPROVED: { label: 'Human Approved', color: '#065F46', bg: '#D1FAE5' },
  REJECTED: { label: 'Rejected', color: '#6B7280', bg: '#F3F4F6' },
  UNKNOWN: { label: 'Status not reported', color: '#6B7280', bg: '#F3F4F6' },
};

interface Props {
  eventId: string | null;
  onClose: () => void;
  onEventUpdated?: (eventId: string) => void;
}

export default function EventVerificationModal({ eventId, onClose, onEventUpdated }: Props) {
  const session = useSession();
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'receipt' | 'reports' | 'audit'>('receipt');
  const [reviewAction, setReviewAction] = useState<'approve' | 'reject' | 'override_severity' | null>(null);
  const [reviewReason, setReviewReason] = useState('');
  const [overrideSeverity, setOverrideSeverity] = useState('');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewResult, setReviewResult] = useState<{ success: boolean; message: string } | null>(null);
  const [reportsExpanded, setReportsExpanded] = useState(false);

  // The same role rules the backend enforces, read from the signed-in session.
  const canReview = hasRole(session, COMMAND_ROLES);
  const canReadProvenance = hasRole(session, LEDGER_ROLES);

  const loadData = useCallback(async (eid: string) => {
    setLoading(true);
    setReviewResult(null);
    setReviewAction(null);
    const [detailResult, provResult] = await Promise.allSettled([
      fetchEventDetail(eid),
      canReadProvenance ? fetchEventProvenance(eid) : Promise.resolve(null),
    ]);
    if (detailResult.status === 'fulfilled') setDetail(detailResult.value);
    setProvenance(provResult.status === 'fulfilled' ? provResult.value : null);
    setLoading(false);
  }, [canReadProvenance]);

  useEffect(() => {
    if (eventId) loadData(eventId);
  }, [eventId, loadData]);

  const handleReview = async () => {
    if (!eventId || !reviewAction || reviewReason.length < 5) return;
    setReviewLoading(true);
    const result = await reviewEvent(eventId, reviewAction, reviewReason, overrideSeverity || undefined);
    if (result.success) {
      setReviewResult({ success: true, message: `Event ${reviewAction === 'approve' ? 'approved' : reviewAction === 'reject' ? 'rejected' : 'severity overridden'} successfully.` });
      setReviewAction(null);
      setReviewReason('');
      // Refresh data
      loadData(eventId);
      onEventUpdated?.(eventId);
    } else {
      setReviewResult({ success: false, message: result.error || 'Review failed' });
    }
    setReviewLoading(false);
  };

  if (!eventId) return null;

  const receipt = detail?.verification_receipt || provenance?.event?.verification_receipt || {};
  const factors = receipt.factors || [];
  // The share of the designed model that actually reported (0.80 while vision
  // and anomaly are offline), and the points it scored. The score means
  // nothing without its coverage, so the two are shown together.
  const coverage: number | null = typeof receipt.factor_coverage === 'number' ? receipt.factor_coverage : null;
  const totalWeighted: number | null = typeof receipt.total_weighted === 'number' ? receipt.total_weighted : null;
  const confidenceScore = detail?.confidence_score ?? provenance?.event?.confidence_score ?? 0;
  const confidencePct = Math.round(confidenceScore * 100);
  const apiReviewStatus = detail?.review_status ?? provenance?.event?.review_status;
  const severity = detail?.severity ?? provenance?.event?.severity ?? 'UNRATED';
  // Use detailEventId (not eventId) to avoid shadowing the eventId prop parameter.
  const detailEventId = detail?.id ?? provenance?.event?.id ?? eventId ?? '';
  const eventType = detail?.event_type_display ?? detail?.event_type ?? '';

  // The API's review_status and quadrant, never derived (BUG-070).
  const reviewState = eventReviewState(apiReviewStatus, detail?.quadrant);
  const reviewStatus = reviewState.reviewStatus;
  const statusStyle = STATUS_STYLES[reviewStatus] || STATUS_STYLES.UNKNOWN;
  const sevStyle = SEVERITY_STYLES[severity] || UNRATED_STYLE;
  // Why the reports and audit tabs are empty when provenance did not load.
  const provenanceGate = !session
    ? 'Sign in as an Analyst, Commander or Admin to see this.'
    : !canReadProvenance
    ? `An Analyst, Commander or Admin account can see this; you are signed in as ${roleLabel(session.role)}.`
    : 'Provenance could not be loaded from the backend.';

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-start justify-end"
        onClick={onClose}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

        {/* Slide-over panel */}
        <motion.div
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="relative w-full max-w-[560px] h-full bg-[#F7F3EA] border-l border-[#E8E2D4] shadow-2xl overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="sticky top-0 z-10 bg-[#F7F3EA]/95 backdrop-blur-md border-b border-[#E8E2D4] px-5 py-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#3C2415] flex items-center justify-center">
                  <Shield className="w-4 h-4 text-[#E8DCC8]" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-[#3C2415] font-mono tracking-wide">VERIFICATION RECEIPT</h2>
                  <p className="text-[10px] text-[#8C7A6B]">{detail?.event_code || provenance?.event?.event_code || '—'}</p>
                </div>
              </div>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#E8E2D4] transition-colors">
                <X className="w-4 h-4 text-[#8C7A6B]" />
              </button>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="w-6 h-6 animate-spin text-[#B5482E]" />
              <span className="ml-2 text-sm text-[#8C7A6B]">Loading verification data…</span>
            </div>
          ) : (
            <div className="px-5 py-4 space-y-4">
              {/* ── Event Header ───────────────────────────────────── */}
              <div className="bg-white rounded-xl border border-[#E8E2D4] p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase" style={{ background: sevStyle.bg, color: sevStyle.text, border: `1px solid ${sevStyle.border}` }}>
                      {severity}
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: statusStyle.bg, color: statusStyle.color }}>
                      {statusStyle.label}
                    </span>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-black text-[#3C2415] font-mono">{confidencePct}%</div>
                    <div className="text-[10px] text-[#8C7A6B]">Confidence</div>
                    {coverage !== null && (
                      <div data-testid="factor-coverage" className="text-[10px] font-semibold text-[#6B5E53]">
                        coverage {Math.round(coverage * 100)}% of the model
                      </div>
                    )}
                  </div>
                </div>
                {detail && (
                  <div className="flex items-center gap-4 text-xs text-[#6B5E53]">
                    <span className="flex items-center gap-1"><MapPin className="w-3 h-3" /> {formatPlace(detail.city, detail.state, detail.place_precision)}</span>
                    <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {detail.verified_at ? new Date(detail.verified_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'}</span>
                  </div>
                )}
                {detail?.impact_radius_km && (
                  <div className="text-[11px] text-[#8C7A6B]">
                    {/* Issue 3 fix: clamp impact_radius_km to per-hazard ceiling */}
                    Impact radius: {clampImpactKm(detailEventId, eventType, detail.impact_radius_km)} &bull; Quadrant: {reviewState.quadrant || '—'}
                  </div>
                )}
              </div>

              {/* ── Review Result Toast ────────────────────────────── */}
              {reviewResult && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`rounded-lg px-4 py-2.5 text-sm font-medium flex items-center gap-2 ${reviewResult.success ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-red-50 text-red-800 border border-red-200'}`}
                >
                  {reviewResult.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                  {reviewResult.message}
                </motion.div>
              )}

              {/* ── Tabs ───────────────────────────────────────────── */}
              <div className="flex gap-1 bg-[#EDE8DD] rounded-lg p-0.5">
                {(['receipt', 'reports', 'audit'] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold transition-all ${activeTab === tab ? 'bg-white text-[#3C2415] shadow-sm' : 'text-[#8C7A6B] hover:text-[#6B5E53]'}`}
                  >
                    {tab === 'receipt' ? '6-Factor Receipt' : tab === 'reports' ? `Reports${provenance ? ` (${provenance.reports.length})` : ''}` : `Audit${provenance ? ` (${provenance.audit.length})` : ''}`}
                  </button>
                ))}
              </div>

              {/* ── TAB: Verification Receipt ──────────────────────── */}
              {activeTab === 'receipt' && (
                <div className="space-y-2">
                  {factors.length > 0 ? factors.map((f: any, i: number) => {
                    const cfg = FACTOR_CONFIG[f.factor] || { icon: <Eye className="w-4 h-4" />, color: '#64748B', bgColor: '#F1F5F9' };
                    // The receipt says so directly since Day 5; the evidence text is
                    // the fallback for receipts stored before then.
                    const isOffline = f.state === 'offline' || f.evidence === 'Telemetry factor offline';
                    const pct = Math.round(f.score * 100);
                    return (
                      <div key={i} className={`bg-white rounded-lg border border-[#E8E2D4] p-3 ${isOffline ? 'opacity-60' : ''}`}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <div className="w-7 h-7 rounded-md flex items-center justify-center" style={{ background: cfg.bgColor, color: cfg.color }}>
                              {cfg.icon}
                            </div>
                            <div>
                              <div className="text-xs font-semibold text-[#3C2415]">{f.factor}</div>
                              <div className="text-[10px] text-[#8C7A6B]">Weight: {f.weight_pct}%</div>
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-sm font-bold font-mono" style={{ color: isOffline ? '#9CA3AF' : cfg.color }}>{isOffline ? '—' : `${pct}%`}</div>
                            <div className="text-[10px] text-[#8C7A6B]">{f.weighted_points?.toFixed(3) ?? '—'} pts</div>
                          </div>
                        </div>
                        {/* Progress bar */}
                        <div className="h-1.5 bg-[#F0EBE0] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${pct}%`, background: isOffline ? '#D1D5DB' : cfg.color }}
                          />
                        </div>
                        <div className="text-[10px] mt-1 text-[#8C7A6B] italic">{f.evidence}</div>
                      </div>
                    );
                  }) : (
                    <div className="bg-white rounded-lg border border-[#E8E2D4] p-6 text-center text-sm text-[#8C7A6B]">
                      <Eye className="w-5 h-5 mx-auto mb-2 opacity-40" />
                      No verification receipt data available.<br />
                      <span className="text-[10px]">Receipt data is generated when the backend pipeline processes reports into events.</span>
                    </div>
                  )}
                  {factors.length > 0 && coverage !== null && totalWeighted !== null && coverage > 0 && (
                    <div data-testid="receipt-arithmetic" className="rounded-lg bg-[#EDE8DD] px-3 py-2 text-[11px] font-mono text-[#3C2415]">
                      {totalWeighted.toFixed(4)} points ÷ {coverage.toFixed(2)} coverage = {(totalWeighted / coverage).toFixed(4)}
                      <span className="block text-[10px] text-[#8C7A6B] font-sans">
                        Offline factors carry no weight; the score is the mean over the factors that reported.
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* ── TAB: Contributing Reports ──────────────────────── */}
              {activeTab === 'reports' && (
                <div className="space-y-2">
                  {provenance && provenance.reports.length > 0 ? (
                    <>
                      {(reportsExpanded ? provenance.reports : provenance.reports.slice(0, 5)).map((r: ProvenanceReport, i: number) => (
                        <div key={r.id} className="bg-white rounded-lg border border-[#E8E2D4] p-3">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-1.5 mb-1">
                                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#F0EBE0] text-[#6B5E53]">{r.source_type}</span>
                                {r.submitted_by && (
                                  <span className="text-[10px] text-[#6B5E53]">filed by {r.submitted_by}</span>
                                )}
                                <span className="text-[10px] text-[#8C7A6B]">#{i + 1}</span>
                              </div>
                              <p className="text-xs text-[#3C2415] leading-relaxed line-clamp-2">{r.raw_text}</p>
                              <div className="flex items-center gap-3 mt-1.5 text-[10px] text-[#8C7A6B]">
                                <span><MapPin className="w-2.5 h-2.5 inline mr-0.5" />{r.latitude?.toFixed(3)}, {r.longitude?.toFixed(3)}</span>
                                <span><Clock className="w-2.5 h-2.5 inline mr-0.5" />{r.created_at ? new Date(r.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'}</span>
                              </div>
                            </div>
                            <div className="text-right ml-3">
                              <div className="text-xs font-bold font-mono text-[#B5482E]">{(r.credibility_score * 100).toFixed(0)}%</div>
                              <div className="text-[9px] text-[#8C7A6B]">credibility</div>
                            </div>
                          </div>
                        </div>
                      ))}
                      {provenance.reports.length > 5 && (
                        <button
                          onClick={() => setReportsExpanded(!reportsExpanded)}
                          className="w-full py-2 text-xs font-semibold text-[#B5482E] hover:text-[#8C3420] flex items-center justify-center gap-1"
                        >
                          {reportsExpanded ? <><ChevronUp className="w-3.5 h-3.5" /> Show less</> : <><ChevronDown className="w-3.5 h-3.5" /> Show all {provenance.reports.length} reports</>}
                        </button>
                      )}
                    </>
                  ) : (
                    <div className="bg-white rounded-lg border border-[#E8E2D4] p-6 text-center text-sm text-[#8C7A6B]">
                      <FileText className="w-5 h-5 mx-auto mb-2 opacity-40" />
                      {provenance === null ? provenanceGate : 'No contributing reports found.'}
                    </div>
                  )}
                </div>
              )}

              {/* ── TAB: SHA-256 Audit Chain ───────────────────────── */}
              {activeTab === 'audit' && (
                <div className="space-y-3">
                  {/* Chain verification status */}
                  {provenance?.chain && (
                    <div className={`rounded-lg px-4 py-2.5 flex items-center gap-2 text-xs font-semibold border ${provenance.chain.valid ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : 'bg-red-50 text-red-800 border-red-200'}`}>
                      {provenance.chain.valid ? <ShieldCheck className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
                      {provenance.chain.valid ? `Hash chain verified — ${provenance.chain.checked} blocks checked` : `Chain integrity error: ${provenance.chain.error || 'tampered'}`}
                    </div>
                  )}

                  {provenance && provenance.audit.length > 0 ? provenance.audit.map((a: AuditEntry, i: number) => (
                    <div key={a.seq} className="bg-white rounded-lg border border-[#E8E2D4] p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-6 h-6 rounded-md bg-[#3C2415] flex items-center justify-center text-[#E8DCC8]">
                            <Hash className="w-3 h-3" />
                          </div>
                          <div>
                            <span className="text-xs font-bold text-[#3C2415] uppercase">{a.action_taken.replace(/_/g, ' ')}</span>
                            <div className="text-[10px] text-[#8C7A6B]">Block #{a.seq} • {a.operator_id}</div>
                          </div>
                        </div>
                        <div className="text-[10px] text-[#8C7A6B]">{new Date(a.logged_at).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'medium' })}</div>
                      </div>
                      {a.reason && <div className="text-[11px] text-[#6B5E53] italic pl-8">&ldquo;{a.reason}&rdquo;</div>}
                      {a.details && (
                        <div className="text-[10px] text-[#8C7A6B] pl-8 space-y-0.5">
                          {a.details.from_status && <div>Status: {a.details.from_status} → {a.details.to_status}</div>}
                          {a.details.from_severity && <div>Severity: {a.details.from_severity} → {a.details.to_severity}</div>}
                          {a.details.confidence_score !== undefined && <div>Confidence: {(a.details.confidence_score * 100).toFixed(1)}%</div>}
                        </div>
                      )}
                      <div className="pl-8">
                        <div className="text-[9px] font-mono text-[#B0A898] break-all">
                          <Lock className="w-2.5 h-2.5 inline mr-1 opacity-50" />SHA-256: {a.sha256_hash}
                        </div>
                        {i > 0 && (
                          <div className="text-[9px] font-mono text-[#B0A898] break-all mt-0.5 opacity-60">
                            prev: {a.prev_hash}
                          </div>
                        )}
                      </div>
                    </div>
                  )) : (
                    <div className="bg-white rounded-lg border border-[#E8E2D4] p-6 text-center text-sm text-[#8C7A6B]">
                      <Lock className="w-5 h-5 mx-auto mb-2 opacity-40" />
                      {provenance === null ? provenanceGate : 'No audit entries for this event.'}
                    </div>
                  )}
                </div>
              )}

              {/* ── Commander Review Action Bar ────────────────────── */}
              {canReview && reviewStatus !== 'REJECTED' && (
                <div className="bg-white rounded-xl border border-[#E8E2D4] p-4 space-y-3">
                  <div className="flex items-center gap-2 text-xs font-bold text-[#3C2415] uppercase">
                    <Radio className="w-3.5 h-3.5 text-[#B5482E]" />
                    Commander Decision
                    {session && <span className="text-[9px] font-normal normal-case text-emerald-600 px-1.5 py-0.5 bg-emerald-50 rounded-full border border-emerald-200">Signed in as {session.username}</span>}
                  </div>

                  {!reviewAction ? (
                    <div className="flex gap-2">
                      {reviewStatus !== 'HUMAN_APPROVED' && (
                        <button
                          onClick={() => setReviewAction('approve')}
                          className="flex-1 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors flex items-center justify-center gap-1.5"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5" /> Approve
                        </button>
                      )}
                      <button
                        onClick={() => setReviewAction('reject')}
                        className="flex-1 py-2 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 transition-colors flex items-center justify-center gap-1.5"
                      >
                        <XCircle className="w-3.5 h-3.5" /> Reject
                      </button>
                      <button
                        onClick={() => setReviewAction('override_severity')}
                        className="flex-1 py-2 rounded-lg bg-[#3C2415] text-white text-xs font-semibold hover:bg-[#5C3B27] transition-colors flex items-center justify-center gap-1.5"
                      >
                        <ArrowUpDown className="w-3.5 h-3.5" /> Override
                      </button>
                    </div>
                  ) : (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-[#3C2415] capitalize">{reviewAction.replace(/_/g, ' ')}</span>
                        <button onClick={() => { setReviewAction(null); setReviewReason(''); }} className="text-[10px] text-[#B5482E] hover:underline">Cancel</button>
                      </div>
                      {reviewAction === 'override_severity' && (
                        <select
                          value={overrideSeverity}
                          onChange={(e) => setOverrideSeverity(e.target.value)}
                          className="w-full px-3 py-1.5 rounded-lg border border-[#E8E2D4] text-xs bg-[#F7F3EA] text-[#3C2415]"
                        >
                          <option value="">Select new severity…</option>
                          <option value="ADVISORY">Advisory</option>
                          <option value="MODERATE">Moderate</option>
                          <option value="HIGH">High</option>
                          <option value="CRITICAL">Critical</option>
                        </select>
                      )}
                      <textarea
                        value={reviewReason}
                        onChange={(e) => setReviewReason(e.target.value)}
                        placeholder="Reason for decision (min 5 characters)…"
                        className="w-full px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-[#F7F3EA] text-[#3C2415] placeholder:text-[#B0A898] resize-none h-16 focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
                      />
                      <button
                        onClick={handleReview}
                        disabled={reviewLoading || reviewReason.length < 5 || (reviewAction === 'override_severity' && !overrideSeverity)}
                        className="w-full py-2 rounded-lg text-white text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
                        style={{ background: reviewAction === 'reject' ? '#DC2626' : reviewAction === 'approve' ? '#059669' : '#3C2415' }}
                      >
                        {reviewLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Shield className="w-3.5 h-3.5" />}
                        {reviewLoading ? 'Submitting…' : `Confirm ${reviewAction.replace(/_/g, ' ')}`}
                      </button>
                    </motion.div>
                  )}
                </div>
              )}
              {!canReview && reviewStatus !== 'REJECTED' && (
                <p className="text-[11px] text-[#8C7A6B] text-center">
                  {session
                    ? `Reviewing needs a Commander or Admin account; you are signed in as ${roleLabel(session.role)}.`
                    : 'Sign in as a Commander or Admin to approve, reject or override this event.'}
                </p>
              )}
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
