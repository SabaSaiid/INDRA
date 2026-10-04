'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Cpu,
  Sparkles,
  Send,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Activity,
  FileCode,
  Gauge,
  ShieldCheck,
  Zap,
  BarChart3,
  Copy,
  Check,
} from 'lucide-react';
import {
  fetchMlObservatory,
  testNlpClassification,
  type MlObservatoryData,
  type NlpTestResult,
} from '@/lib/api';

const QUICK_PROMPTS = [
  {
    label: 'Hinglish Breach',
    text: 'puliya ke upar se paani beh raha hai gaon doob gaya',
  },
  {
    label: 'Urban Flood',
    text: 'Severe waterlogging and urban flooding on main road, 3 feet water entered houses',
  },
  {
    label: 'Cloudburst Warning',
    text: 'Cloudburst reported upstream, heavy flash flood gushing through ravines',
  },
  {
    label: 'Not Relevant',
    text: 'Normal sunny day, regular traffic near civil hospital with no rain',
  },
];

const CLASS_COLORS: Record<string, { bg: string; text: string; bar: string }> = {
  URBAN_FLOOD: { bg: 'bg-blue-500/15', text: 'text-blue-700', bar: 'bg-blue-600' },
  RIVER_BREACH: { bg: 'bg-cyan-500/15', text: 'text-cyan-700', bar: 'bg-cyan-600' },
  CLOUDBURST: { bg: 'bg-purple-500/15', text: 'text-purple-700', bar: 'bg-purple-600' },
  CYCLONE_INUNDATION: { bg: 'bg-amber-500/15', text: 'text-amber-700', bar: 'bg-amber-600' },
  NOT_RELEVANT: { bg: 'bg-slate-500/15', text: 'text-slate-600', bar: 'bg-slate-400' },
};

export default function AiModelObservatory() {
  const [observatory, setObservatory] = useState<MlObservatoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // NLP test harness state
  const [testText, setTestText] = useState(QUICK_PROMPTS[0].text);
  const [testingNlp, setTestingNlp] = useState(false);
  const [nlpResult, setNlpResult] = useState<NlpTestResult | null>(null);
  const [nlpError, setNlpError] = useState<string | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchMlObservatory();
        if (!cancelled) {
          setObservatory(data);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Failed to load ML observatory');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleTestNlp = async () => {
    if (!testText.trim()) return;
    setTestingNlp(true);
    setNlpError(null);
    try {
      const res = await testNlpClassification(testText);
      setNlpResult(res);
    } catch (err: any) {
      setNlpError(err.message || 'NLP classification request failed');
    } finally {
      setTestingNlp(false);
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedHash(id);
    setTimeout(() => setCopiedHash(null), 1500);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 bg-white rounded-2xl border border-slate-200">
        <Loader2 className="w-6 h-6 animate-spin text-purple-600" />
        <span className="ml-2 text-xs font-medium text-slate-500">Loading AI / ML Model Observatory…</span>
      </div>
    );
  }

  if (error || !observatory) {
    return (
      <div className="p-6 bg-white rounded-2xl border border-rose-200 text-center space-y-2">
        <AlertTriangle className="w-8 h-8 text-rose-500 mx-auto" />
        <h3 className="text-sm font-bold text-slate-900">Observatory Unavailable</h3>
        <p className="text-xs text-slate-500">{error || 'Could not connect to ML telemetry service'}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ─── Hero Overview ────────────────────────────────────────────── */}
      <div className="bg-gradient-to-r from-[#1E1B4B] via-[#2E1065] to-[#1E1B4B] text-white p-6 rounded-2xl border border-purple-900/40 shadow-lg relative overflow-hidden">
        <div className="absolute right-0 top-0 translate-x-12 -translate-y-6 w-64 h-64 bg-purple-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <Brain className="w-5 h-5 text-purple-400" />
              <h2 className="text-lg font-bold font-mono tracking-wide">AI & ML Model Observatory</h2>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                {observatory.release_state}
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
                FROZEN SUITE v1.0
              </span>
            </div>
            <p className="text-xs text-purple-200 max-w-2xl leading-relaxed">
              Real-time audit telemetry for INDRA&apos;s frozen multi-modal AI models: IndicBERT NLP classifier,
              spatial DBSCAN grouping, SAM-2 computer vision, station anomaly detection, and duplicate suppression.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="px-3 py-2 bg-white/10 rounded-xl border border-white/10 text-right">
              <span className="text-[10px] uppercase text-purple-300 font-semibold block">Regression Tests</span>
              <span className="text-sm font-mono font-bold text-white">343 / 343 PASSED</span>
            </div>
            <div className="px-3 py-2 bg-white/10 rounded-xl border border-white/10 text-right">
              <span className="text-[10px] uppercase text-purple-300 font-semibold block">Full Backend</span>
              <span className="text-sm font-mono font-bold text-white">690 PASSED</span>
            </div>
          </div>
        </div>
      </div>

      {/* ─── Live Telemetry Cards ────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Total Reports</span>
          <span className="text-lg font-bold font-mono text-slate-900">{observatory.live_telemetry.total_reports}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">Ingested highway</span>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Fused into Events</span>
          <span className="text-lg font-bold font-mono text-emerald-600">{observatory.live_telemetry.fused_reports}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">Corroborated</span>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Unfused Queue</span>
          <span className="text-lg font-bold font-mono text-amber-600">{observatory.live_telemetry.unfused_reports}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">Awaiting neighbours</span>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Duplicates Suppressed</span>
          <span className="text-lg font-bold font-mono text-slate-600">{observatory.live_telemetry.duplicate_reports}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">Zero double-count</span>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Verified Incidents</span>
          <span className="text-lg font-bold font-mono text-purple-600">{observatory.live_telemetry.verified_events}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">100-pt receipts</span>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <span className="text-[10px] font-semibold text-slate-500 uppercase block">Penalising Flags</span>
          <span className="text-lg font-bold font-mono text-rose-600">{observatory.live_telemetry.flagged_reports}</span>
          <span className="text-[9px] text-slate-400 block mt-0.5">Credibility reduced</span>
        </div>
      </div>

      {/* ─── Interactive NLP Classifier Test Harness ────────────────── */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Zap className="w-4 h-4 text-purple-600" />
              IndicBERT Vernacular NLP Classifier — Interactive Test Harness
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Dry-run multilingual emergency text through the frozen 5-label classification model with 15x cost-sensitive recall margin.
            </p>
          </div>
          <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded bg-purple-50 text-purple-700 border border-purple-200">
            Model: nlp_classifier_v3
          </span>
        </div>

        {/* Quick Prompts */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-semibold text-slate-500">Quick Test Cases:</span>
          {QUICK_PROMPTS.map((p) => (
            <button
              key={p.label}
              onClick={() => {
                setTestText(p.text);
                setNlpResult(null);
              }}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-purple-50 hover:text-purple-700 text-slate-700 font-medium transition-colors border border-slate-200"
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Text Input */}
        <div className="space-y-2">
          <textarea
            value={testText}
            onChange={(e) => setTestText(e.target.value)}
            rows={3}
            placeholder="Type or paste emergency observation in Hindi, English, Hinglish, Bengali, Tamil, etc."
            className="w-full p-3 rounded-xl border border-slate-200 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 transition-all"
          />

          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400 font-mono">
              Character & Word TF-IDF · 5 Categories · Softmax Calibration
            </span>
            <button
              onClick={handleTestNlp}
              disabled={testingNlp || !testText.trim()}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-semibold hover:bg-purple-700 transition-all shadow-xs disabled:opacity-50"
            >
              {testingNlp ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              {testingNlp ? 'Evaluating Inferences…' : 'Run NLP Classifier'}
            </button>
          </div>
        </div>

        {nlpError && (
          <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs font-semibold text-rose-700">
            {nlpError}
          </div>
        )}

        {/* NLP Test Output Card */}
        {nlpResult && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 bg-slate-50 border border-purple-100 rounded-xl space-y-4"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-700">Top Predicted Hazard:</span>
                <span className={`px-2.5 py-0.5 rounded-lg text-xs font-mono font-bold border ${CLASS_COLORS[nlpResult.top_class]?.bg || 'bg-slate-200'} ${CLASS_COLORS[nlpResult.top_class]?.text || 'text-slate-800'}`}>
                  {nlpResult.top_class}
                </span>
                <span className="text-xs font-mono font-semibold text-emerald-600">
                  {Math.round(nlpResult.confidence * 100)}% Confidence
                </span>
              </div>

              <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500">
                <span>Features Matched: <b>{nlpResult.features_matched}</b></span>
                <span>Latency: <b>{nlpResult.latency_ms} ms</b></span>
              </div>
            </div>

            {/* Probability Bars */}
            <div className="space-y-2">
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">
                Class Probability Distribution
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {Object.entries(nlpResult.probabilities).map(([c, prob]) => {
                  const pct = Math.round(prob * 100);
                  const cfg = CLASS_COLORS[c] || { bar: 'bg-purple-600' };
                  return (
                    <div key={c} className="p-2 bg-white rounded-lg border border-slate-200 space-y-1">
                      <div className="flex justify-between text-xs font-mono">
                        <span className="font-semibold text-slate-800">{c}</span>
                        <span className="font-bold text-slate-600">{pct}%</span>
                      </div>
                      <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${cfg.bar} transition-all duration-500`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {/* ─── 6-Model Frozen Suite Registry ──────────────────────────── */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-indigo-600" />
              Multi-Modal Model Registry & SHA-256 Provenance
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Cryptographically frozen model weights and receipts verified prior to system deployment.
            </p>
          </div>
          <span className="text-xs font-mono font-semibold text-slate-500">
            {observatory.components.length} Registered Components
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {observatory.components.map((comp) => (
            <div
              key={comp.component}
              className="p-4 bg-slate-50 rounded-xl border border-slate-200 hover:border-purple-200 transition-all space-y-2.5 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
                    {comp.component}
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">
                    {comp.backend_integration_status.replace(/_/g, ' ').slice(0, 20)}…
                  </span>
                </div>
                <h4 className="text-xs font-bold text-slate-800 mt-2 truncate">{comp.version}</h4>
                <p className="text-[11px] font-mono text-slate-500 mt-0.5 truncate">
                  Artifact: {comp.artifact}
                </p>
              </div>

              {comp.artifact_sha256 && (
                <div className="pt-2 border-t border-slate-200 flex items-center justify-between text-[10px] font-mono text-slate-500">
                  <span className="truncate max-w-[170px]" title={comp.artifact_sha256}>
                    SHA: {comp.artifact_sha256.slice(0, 16)}…
                  </span>
                  <button
                    onClick={() => copyToClipboard(comp.artifact_sha256!, comp.component)}
                    className="flex items-center gap-1 text-purple-600 hover:text-purple-800"
                    title="Copy full SHA-256 hash"
                  >
                    {copiedHash === comp.component ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                    {copiedHash === comp.component ? 'Copied' : 'Copy'}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ─── 100-Point Consensus Weight Breakdown ───────────────────── */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="border-b border-slate-100 pb-3">
          <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <Gauge className="w-4 h-4 text-emerald-600" />
            100-Point Consensus Verification Formula
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Every incident event requires a composite confidence score &ge; 0.60 across 6 orthogonal corroboration factors.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {observatory.consensus_weights.map((w) => (
            <div key={w.factor} className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-800">{w.factor}</span>
                <span className="text-xs font-mono font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                  {w.weight} pts
                </span>
              </div>
              <p className="text-[11px] text-slate-500">{w.metric}</p>
              <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-600 rounded-full"
                  style={{ width: `${(w.weight / 25) * 100}%` }}
                />
              </div>
              <div className="flex justify-between items-center text-[10px] font-mono text-slate-400 pt-0.5">
                <span>Weight Share: {w.weight}%</span>
                <span className="text-emerald-600 font-semibold">{w.status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
