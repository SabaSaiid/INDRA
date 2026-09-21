'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  FileText,
  CheckCircle2,
  Clock,
  MapPin,
  ShieldCheck,
  Search,
  AlertTriangle,
  Loader2,
  Send,
  Radio,
  RefreshCw,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import ReportSubmissionModal from '@/components/ReportSubmissionModal';
import { useSidebar } from '@/lib/useSidebar';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchRecentFeed, type FeedItem } from '@/lib/api';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';

function formatRelativeTime(ts?: string, fallbackTime?: string): string {
  if (fallbackTime && !ts) return fallbackTime;
  if (!ts) return 'just now';
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ${mins % 60}m ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch {
    return fallbackTime || 'recently';
  }
}

const SOURCE_COLORS: Record<string, string> = {
  citizen: 'bg-blue-50 text-blue-700 border-blue-200',
  sensor: 'bg-amber-50 text-amber-700 border-amber-200',
  imd: 'bg-rose-50 text-rose-700 border-rose-200',
  official: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  social: 'bg-amber-50 text-amber-700 border-amber-200',
  twitter: 'bg-purple-50 text-purple-700 border-purple-200',
  news: 'bg-slate-50 text-slate-700 border-slate-200',
};

export default function ReportsPage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [search, setSearch] = useState('');
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const { subscribe } = useIndraWebSocket();

  const loadFeed = useCallback(async () => {
    try {
      const data = await fetchRecentFeed(50);
      setFeedItems(data);
    } catch {
      // fallback handled in api.ts
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadFeed();
  }, [loadFeed]);

  // Real-time WebSocket updates
  useEffect(() => {
    return subscribe('reports-page', (msg) => {
      if (['NEW_REPORT', 'VERIFIED_EVENT', 'EVENT_REVIEWED'].includes(msg.type)) {
        loadFeed();
      }
    });
  }, [subscribe, loadFeed]);

  const filtered = feedItems.filter((item) => {
    if (!search) return true;
    const q = search.toLowerCase();
    const textContent = item.message || '';
    return (
      textContent.toLowerCase().includes(q) ||
      item.source?.toLowerCase().includes(q) ||
      (item.sourceLabel && item.sourceLabel.toLowerCase().includes(q))
    );
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[280px]'
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
                  Field Reports &amp; Ground Truth Repository
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  {feedItems.length} INGESTED RECORDS
                </span>
              </div>
              <p className="text-xs text-slate-300">
                Multi-channel verification pipeline combining citizen crowdsourced observations, IoT hydro-sensors, Doppler radar, and satellite telemetry.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={() => setReportModalOpen(true)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#B5482E] text-white text-xs font-semibold hover:bg-[#8C3420] transition-colors shadow-sm"
              >
                <Send className="w-3.5 h-3.5" /> Submit Report
              </button>
              <div className="flex items-center gap-2 bg-emerald-950/60 border border-emerald-500/30 px-3 py-1.5 rounded-xl text-xs font-mono text-emerald-400">
                <Radio className="w-3.5 h-3.5 animate-pulse" />
                <span>LIVE INGESTION</span>
              </div>
              <button
                onClick={() => {
                  setLoading(true);
                  loadFeed();
                }}
                disabled={loading}
                className="p-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Refresh feed"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Search bar & Filter */}
          <div className="relative max-w-md">
            <Search className="w-4 h-4 text-[#A0988A] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search reports by location, source, or message text..."
              className="w-full pl-9 pr-3 py-2 bg-white border border-[#E8E2D4] rounded-xl text-xs text-[#1B2432] placeholder-[#A0988A] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 shadow-2xs transition-all"
            />
          </div>

          {/* Reports Grid */}
          {loading && feedItems.length === 0 ? (
            <div className="flex items-center justify-center py-24 bg-white rounded-2xl border border-[#E8E2D4]">
              <Loader2 className="w-6 h-6 animate-spin text-[#B5482E]" />
              <span className="ml-2 text-xs font-medium text-[#7A8599]">Loading reports feed…</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-24 text-[#7A8599] text-xs bg-white rounded-2xl border border-[#E8E2D4]">
              No reports match the current search.
            </div>
          ) : (
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="visible"
              className="grid grid-cols-1 md:grid-cols-2 gap-4"
            >
              {filtered.map((item, idx) => {
                const srcColor = SOURCE_COLORS[item.source] || SOURCE_COLORS.citizen;
                const messageText = item.message || 'No message content';
                const timeDisplay = formatRelativeTime(item.timestamp, item.time);

                return (
                  <motion.div
                    key={item.id || idx}
                    variants={fadeIn}
                    className="bg-white rounded-2xl border border-[#E8E2D4] p-5 shadow-2xs hover:shadow-md transition-all flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-md border ${srcColor}`}>
                            {item.sourceLabel ? item.sourceLabel.toUpperCase() : (item.source?.toUpperCase() || 'CITIZEN')}
                          </span>
                          {item.city && (
                            <span className="text-xs text-[#7A8599] flex items-center gap-1 font-medium">
                              <MapPin className="w-3 h-3 text-[#A0988A]" /> {item.city}
                            </span>
                          )}
                        </div>
                        {item.confidence !== undefined && (
                          <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200 font-semibold">
                            <ShieldCheck className="w-3.5 h-3.5" />
                            {typeof item.confidence === 'number' ? `${(item.confidence * 100).toFixed(0)}%` : item.confidence}
                          </span>
                        )}
                      </div>

                      <div className="space-y-2 mb-4">
                        <p className="text-xs text-[#4A5568] bg-[#F7F3EA] p-3 rounded-xl border border-[#E8E2D4] leading-relaxed">
                          &ldquo;{messageText}&rdquo;
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-[#F0EBE0] text-xs text-[#7A8599]">
                      <span className="text-[11px] font-mono font-medium">{item.eventType || item.type || item.sourceLabel || 'Telemetry Report'}</span>
                      <div className="flex items-center gap-1 font-mono text-[11px] text-[#A0988A]">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{timeDisplay}</span>
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
          onSubmitted={() => loadFeed()}
        />
      </div>
    </div>
  );
}
