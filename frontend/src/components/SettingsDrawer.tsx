'use client';

import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import {
  X,
  Settings,
  Globe,
  Map as MapIcon,
  Volume2,
  Play,
  Layers,
  Gauge,
  Wifi,
  RotateCcw,
  Download,
  Upload,
  Shield,
  Check,
  AlertTriangle,
  Sliders,
  Bell,
  Mail,
  Phone,
  Lock,
  Timer,
  ArrowRight,
} from 'lucide-react';
import {
  useSettings,
  type BasemapPreset,
  type ProjectionPreset,
  type SirenPattern,
  type TempUnit,
  type WindUnit,
  type RainUnit,
  type CoordFormat,
  type TimezoneMode,
  type ThemeMode,
  type RefreshInterval,
  type IdleLockMinutes,
  formatTemperature,
  formatWindSpeed,
  formatRainfall,
  formatCoordinates,
} from '@/lib/useSettings';
import { cn } from '@/lib/utils';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { SUPPORTED_LANGUAGES } from '@/lib/i18n/types';

interface SettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabKey = 'map' | 'alerts' | 'units' | 'hud' | 'notifications' | 'security' | 'network' | 'system';

// ── Animation variants ──────────────────────────────────────────────────────

const backdropVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.25 } },
  exit: { opacity: 0, transition: { duration: 0.2 } },
};

const panelVariants = {
  hidden: { x: '100%' },
  visible: { x: 0, transition: { type: 'spring', damping: 28, stiffness: 260, delay: 0.04 } },
  exit: { x: '100%', transition: { type: 'spring', damping: 32, stiffness: 320 } },
};

const headerVariants = {
  hidden: { opacity: 0, y: -10 },
  visible: { opacity: 1, y: 0, transition: { delay: 0.18, duration: 0.22 } },
};

const navRailVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.04, delayChildren: 0.22 } },
};

const navItemVariants = {
  hidden: { opacity: 0, x: -8 },
  visible: { opacity: 1, x: 0, transition: { type: 'spring', stiffness: 300, damping: 24 } },
};

// ── Tab direction tracking (Phase B) ──────────────────────────────────────

const TAB_ORDER: TabKey[] = ['map', 'alerts', 'units', 'hud', 'notifications', 'security', 'network', 'system'];

function TabContent({ tabKey, direction, children }: { tabKey: string; direction: number; children: React.ReactNode }) {
  return (
    <AnimatePresence mode="wait" custom={direction}>
      <motion.div
        key={tabKey}
        custom={direction}
        initial={{ x: direction * 18, opacity: 0, filter: 'blur(3px)' }}
        animate={{ x: 0, opacity: 1, filter: 'blur(0px)', transition: { type: 'spring', damping: 22, stiffness: 280 } }}
        exit={{ x: direction * -18, opacity: 0, filter: 'blur(3px)', transition: { duration: 0.11 } }}
        className="space-y-4"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// ── Spring Toggle (Phase C1) ────────────────────────────────────────────────

function SpringToggle({ value, onChange, size = 'sm' }: { value: boolean; onChange: () => void; size?: 'sm' | 'md' }) {
  const isLg = size === 'md';
  return (
    <button
      onClick={onChange}
      className={cn('relative shrink-0 cursor-pointer rounded-full transition-colors duration-200 focus:outline-none', isLg ? 'h-6 w-11' : 'h-5 w-9')}
      style={{ background: value ? '#B5482E' : '#374151' }}
      role="switch"
      aria-checked={value}
    >
      <AnimatePresence>
        {value && (
          <motion.span
            key="glow"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            className="absolute inset-0 rounded-full ring-2 ring-[#F97316]/35 ring-offset-1 ring-offset-[#111827]"
          />
        )}
      </AnimatePresence>
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        className={cn('absolute top-0.5 rounded-full bg-white shadow-md', isLg ? 'h-5 w-5' : 'h-4 w-4')}
        style={{ left: value ? (isLg ? 'calc(100% - 22px)' : 'calc(100% - 18px)') : '2px' }}
      />
    </button>
  );
}

// ── Section Header (Phase C3) ─────────────────────────────────────────────

function SectionHeader({ icon: Icon, label }: { icon: React.ComponentType<{ className?: string }>; label: string }) {
  return (
    <div className="mb-2.5">
      <h3 className="text-[10px] font-bold font-mono tracking-widest uppercase text-slate-400 flex items-center gap-1.5 mb-1">
        <Icon className="w-3 h-3 text-[#F97316]" />
        {label}
      </h3>
      <motion.div
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ delay: 0.06, duration: 0.28, ease: 'easeOut' }}
        className="h-px origin-left"
        style={{ background: 'linear-gradient(90deg, rgba(249,115,22,0.5) 0%, transparent 100%)' }}
      />
    </div>
  );
}

// ── Selection Card (Phase C2) ─────────────────────────────────────────────

function SelectCard({
  isSelected, onClick, children, className,
}: {
  isSelected: boolean; onClick: () => void; children: React.ReactNode; className?: string;
}) {
  return (
    <motion.button
      onClick={onClick}
      whileHover={{ y: -2, scale: 1.01 }}
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 400, damping: 20 }}
      className={cn(
        'p-2.5 rounded-xl border text-left transition-colors duration-150',
        isSelected
          ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-[0_0_0_1px_#B5482E,_0_4px_16px_rgba(181,72,46,0.22)]'
          : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/25 hover:bg-white/[0.07]',
        className,
      )}
    >
      {children}
    </motion.button>
  );
}

// ── Toggle Row ────────────────────────────────────────────────────────────

function ToggleRow({
  label, desc, value, onChange, warn,
}: {
  label: React.ReactNode; desc?: React.ReactNode; value: boolean; onChange: () => void; warn?: React.ReactNode;
}) {
  return (
    <div className="px-3 py-2.5 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold text-white leading-tight">{label}</p>
        {warn && <p className="text-[9px] text-amber-400 font-mono mt-0.5">{warn}</p>}
        {desc && <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">{desc}</p>}
      </div>
      <SpringToggle value={value} onChange={onChange} />
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function SettingsDrawer({ isOpen, onClose }: SettingsDrawerProps) {
  const { language: currentLang, setLanguage: changeLang } = useTranslation();
  const { settings, updateSettings, resetSettings, testAlarm } = useSettings();
  const [activeTab, setActiveTab] = useState<TabKey>('map');
  const [direction, setDirection] = useState(1);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const handleTabChange = (tab: TabKey) => {
    setDirection(TAB_ORDER.indexOf(tab) >= TAB_ORDER.indexOf(activeTab) ? 1 : -1);
    setActiveTab(tab);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape' && isOpen) onClose(); };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3000);
  };

  const handleTestAudio = (pattern?: SirenPattern) => {
    setIsPlayingAudio(true);
    testAlarm(pattern);
    setTimeout(() => setIsPlayingAudio(false), 1800);
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(settings, null, 2));
    const a = document.createElement('a');
    a.setAttribute('href', dataStr);
    a.setAttribute('download', `indra_settings_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('Configuration exported as JSON');
  };

  const handleImportJson = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try { updateSettings(JSON.parse(event.target?.result as string)); showToast('Configuration imported successfully'); }
      catch { showToast('Failed to parse settings JSON file'); }
    };
    reader.readAsText(file);
  };

  const tabGroups = [
    { tabs: [
      { key: 'map' as TabKey, label: 'Map', icon: Globe },
      { key: 'alerts' as TabKey, label: 'Alerts', icon: Volume2 },
      { key: 'units' as TabKey, label: 'Units', icon: Gauge },
      { key: 'hud' as TabKey, label: 'Style', icon: Sliders },
    ]},
    { tabs: [
      { key: 'notifications' as TabKey, label: 'Notify', icon: Bell },
      { key: 'security' as TabKey, label: 'Security', icon: Lock },
      { key: 'network' as TabKey, label: 'Network', icon: Wifi },
    ]},
    { tabs: [
      { key: 'system' as TabKey, label: 'Backup', icon: Shield },
    ]},
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop — directional vignette (Phase D2) */}
          <motion.div
            variants={backdropVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={onClose}
            className="fixed inset-0 z-50"
            style={{
              background: 'radial-gradient(ellipse 65% 100% at 100% 50%, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.42) 100%)',
              backdropFilter: 'blur(6px)',
            }}
          />

          {/* Panel (Phase D3 — staggered entry) */}
          <motion.aside
            variants={panelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed right-0 top-0 h-screen z-50 flex overflow-hidden"
            style={{
              width: 'min(520px, 100vw)',
              background: 'linear-gradient(170deg, #182235 0%, #0f1924 55%, #0a1218 100%)',
              borderLeft: '1px solid rgba(255,255,255,0.07)',
              boxShadow: '-16px 0 48px rgba(0,0,0,0.55)',
            }}
          >
            {/* ── Phase A: Left Icon Rail ─────────────────────────── */}
            <motion.nav
              variants={navRailVariants}
              initial="hidden"
              animate="visible"
              className="w-[52px] shrink-0 flex flex-col pt-[58px] pb-3 border-r border-white/[0.06]"
              style={{ background: 'rgba(0,0,0,0.22)' }}
            >
              {tabGroups.map((group, gi) => (
                <React.Fragment key={gi}>
                  {gi > 0 && <div className="mx-2.5 my-1.5 h-px bg-white/[0.07]" />}
                  {group.tabs.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.key;
                    return (
                      <motion.button
                        key={tab.key}
                        variants={navItemVariants}
                        whileHover={{ scale: 1.08, x: 2 }}
                        whileTap={{ scale: 0.93 }}
                        onClick={() => handleTabChange(tab.key)}
                        className={cn(
                          'relative flex flex-col items-center justify-center gap-0.5 h-[46px] w-full transition-colors duration-150',
                          isActive ? 'text-[#F97316]' : 'text-slate-600 hover:text-slate-300',
                        )}
                        title={tab.label}
                      >
                        {isActive && (
                          <motion.span
                            layoutId="nav-active-bar"
                            className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-r-full bg-[#F97316]"
                            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                          />
                        )}
                        {isActive && (
                          <motion.span
                            layoutId="nav-active-bg"
                            className="absolute inset-1 rounded-xl"
                            style={{ background: 'rgba(181,72,46,0.13)' }}
                            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                          />
                        )}
                        <Icon className="w-[15px] h-[15px] relative z-10" />
                        <span className={cn('text-[8px] font-bold tracking-wide relative z-10', isActive ? 'text-[#F97316]' : 'text-slate-600')}>
                          {tab.label}
                        </span>
                      </motion.button>
                    );
                  })}
                </React.Fragment>
              ))}
            </motion.nav>

            {/* ── Right content ──────────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

              {/* Header (Phase D1) */}
              <motion.div
                variants={headerVariants}
                initial="hidden"
                animate="visible"
                className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-white/[0.07]"
                style={{ background: 'rgba(0,0,0,0.28)' }}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <motion.div
                    whileHover={{ rotate: 90 }}
                    transition={{ type: 'spring', stiffness: 280, damping: 16 }}
                    className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-[#F97316]"
                    style={{ background: 'rgba(181,72,46,0.16)', border: '1px solid rgba(181,72,46,0.38)' }}
                  >
                    <Settings className="w-4 h-4" />
                  </motion.div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-bold tracking-wide text-white truncate" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        INDRA Settings
                      </h2>
                      <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        SYNC
                      </span>
                    </div>
                    <p className="text-[9px] text-slate-500 font-mono">SIH26069 &middot; auto-saves locally</p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="hidden sm:flex items-center text-[9px] font-mono text-slate-600 bg-white/[0.05] px-1.5 py-0.5 rounded border border-white/[0.07]">ESC</span>
                  <motion.button
                    whileHover={{ scale: 1.1, rotate: 90 }}
                    whileTap={{ scale: 0.88 }}
                    transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                    onClick={onClose}
                    className="w-8 h-8 rounded-lg bg-white/[0.05] border border-white/[0.08] flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
                    aria-label="Close settings"
                  >
                    <X className="w-4 h-4" />
                  </motion.button>
                </div>
              </motion.div>

              {/* Toast — bounce entry (Phase E1) */}
              <AnimatePresence>
                {toastMsg && (
                  <motion.div
                    key="toast"
                    initial={{ opacity: 0, y: -14, scale: 0.88 }}
                    animate={{ opacity: 1, y: 0, scale: 1, transition: { type: 'spring', stiffness: 420, damping: 22 } }}
                    exit={{ opacity: 0, y: -10, scale: 0.92, transition: { duration: 0.15 } }}
                    className="shrink-0 flex items-center gap-2 px-4 py-2 bg-emerald-500/15 border-b border-emerald-500/25 text-emerald-300 text-[11px] font-mono"
                  >
                    <Check className="w-3.5 h-3.5 shrink-0" />
                    <span>{toastMsg}</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Scrollable area (Phase E3 — drawer-scroll orange scrollbar) */}
              <div className="flex-1 overflow-y-auto p-4 drawer-scroll">

                {/* MAP */}
                {activeTab === 'map' && (
                  <TabContent tabKey="map" direction={direction}>
                    <div>
                      <SectionHeader icon={Globe} label="Default Map Projection" />
                      <div className="grid grid-cols-2 gap-2">
                        {[
                          { id: 'globe', label: '3D Spherical Globe', desc: 'True curvature & orbit', icon: Globe },
                          { id: 'mercator', label: '2D Flat Mercator', desc: 'Standard planar grid', icon: MapIcon },
                        ].map((proj) => {
                          const Icon = proj.icon;
                          const isSel = settings.mapProjection === proj.id;
                          return (
                            <SelectCard key={proj.id} isSelected={isSel} onClick={() => updateSettings({ mapProjection: proj.id as ProjectionPreset })}>
                              <div className="flex items-center justify-between mb-1">
                                <Icon className={cn('w-4 h-4', isSel ? 'text-[#F97316]' : 'text-slate-400')} />
                                {isSel && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                              </div>
                              <p className="text-xs font-semibold text-white">{proj.label}</p>
                              <p className="text-[10px] text-slate-400 leading-tight mt-0.5">{proj.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Layers} label="Default Basemap Style" />
                      <div className="grid grid-cols-2 gap-2">
                        {[
                          { id: 'satellite', label: 'Satellite', badge: 'ESRI HIGH-RES' },
                          { id: 'dark', label: 'Dark Tactical', badge: 'CARTO DARK' },
                          { id: 'topo', label: 'Topographic', badge: 'TERRAIN HYBRID' },
                          { id: 'street', label: 'Street Vector', badge: 'OPENSTREETMAP' },
                        ].map((base) => {
                          const isSel = settings.defaultBasemap === base.id;
                          return (
                            <SelectCard key={base.id} isSelected={isSel} onClick={() => updateSettings({ defaultBasemap: base.id as BasemapPreset })}>
                              <div className="flex items-center justify-between mb-0.5">
                                <span className="text-xs font-medium text-white">{base.label}</span>
                                {isSel && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                              </div>
                              <span className="text-[9px] font-mono text-slate-500">{base.badge}</span>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                      <p className="text-xs font-semibold text-white">Map layers</p>
                      <p className="text-[10px] text-slate-400 leading-tight mt-0.5">INDRA events, SACHET warnings and unfused citizen reports. Toggle them on the map.</p>
                    </div>

                    <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
                      <div>
                        <p className="text-xs font-semibold text-white">Globe Ambient Orbit</p>
                        <p className="text-[10px] text-slate-400">Slow auto-rotation when idle</p>
                      </div>
                      <SpringToggle value={settings.globeAutoRotate} onChange={() => updateSettings({ globeAutoRotate: !settings.globeAutoRotate })} />
                    </div>
                  </TabContent>
                )}

                {/* ALERTS */}
                {activeTab === 'alerts' && (
                  <TabContent tabKey="alerts" direction={direction}>
                    <div className="p-4 rounded-xl border border-[#B5482E]/30" style={{ background: 'linear-gradient(135deg,rgba(181,72,46,0.12),rgba(255,255,255,0.02))' }}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                          <Volume2 className="w-5 h-5 text-[#F97316]" />
                          <div>
                            <h4 className="text-xs font-bold text-white uppercase font-mono">Emergency Siren</h4>
                            <p className="text-[10px] text-slate-400">Synthesized tone for critical events</p>
                          </div>
                        </div>
                        <SpringToggle size="md" value={settings.audioAlertsEnabled} onChange={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })} />
                      </div>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-[11px] font-mono text-slate-300">
                          <span>Volume</span>
                          <span className="font-bold text-[#F97316]">{Math.round(settings.alertVolume * 100)}%</span>
                        </div>
                        <input type="range" min="0.1" max="1.0" step="0.05" disabled={!settings.audioAlertsEnabled} value={settings.alertVolume} onChange={(e) => updateSettings({ alertVolume: parseFloat(e.target.value) })} className="w-full accent-[#E05D38] h-1.5 bg-slate-800 rounded-lg cursor-pointer disabled:opacity-40" />
                      </div>
                      <div className="mt-4 flex items-center justify-between pt-3 border-t border-white/10">
                        <span className="text-[11px] text-slate-400 font-mono">Synthesizer Test</span>
                        <motion.button whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.95 }} onClick={() => handleTestAudio()} disabled={!settings.audioAlertsEnabled || isPlayingAudio} className={cn('flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all', isPlayingAudio ? 'bg-[#B5482E] text-white animate-pulse' : 'bg-[#B5482E]/20 hover:bg-[#B5482E]/35 text-white border border-[#B5482E]/50')}>
                          <Play className="w-3.5 h-3.5 fill-current" />
                          {isPlayingAudio ? 'Sounding...' : 'Test Siren'}
                        </motion.button>
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Volume2} label="Siren Pattern" />
                      <div className="grid grid-cols-2 gap-2">
                        {[
                          { id: 'warble_fast', label: 'Tactical Warble', desc: 'Rapid 8Hz sweep' },
                          { id: 'siren_continuous', label: 'Continuous Siren', desc: 'Civil defense dual-pitch' },
                          { id: 'pulsed_beacon', label: 'Pulsed Beacon', desc: '3-stage audio beep' },
                          { id: 'chime_two_tone', label: 'Operational Chime', desc: 'Gentle ping' },
                        ].map((pat) => {
                          const isSel = settings.sirenPattern === pat.id;
                          return (
                            <SelectCard key={pat.id} isSelected={isSel} onClick={() => { updateSettings({ sirenPattern: pat.id as SirenPattern }); if (settings.audioAlertsEnabled) handleTestAudio(pat.id as SirenPattern); }}>
                              <div className="flex items-center justify-between"><span className="text-xs font-medium text-white">{pat.label}</span>{isSel && <Check className="w-3 h-3 text-[#F97316]" />}</div>
                              <span className="text-[10px] text-slate-400 mt-0.5 block">{pat.desc}</span>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={AlertTriangle} label="Alert Threshold" />
                      <div className="grid grid-cols-2 gap-1.5">
                        {[
                          { id: 'ALL', label: 'All Incidents', desc: 'Low, Moderate & Critical' },
                          { id: 'MODERATE_PLUS', label: 'Moderate+', desc: 'Exclude minor warnings' },
                          { id: 'HIGH_PLUS', label: 'High & Critical', desc: 'Severe hazard bulletins' },
                          { id: 'CRITICAL_ONLY', label: 'Critical Only', desc: 'Flash floods / cyclones' },
                        ].map((sev) => {
                          const isSel = settings.minSeverityThreshold === sev.id;
                          return (
                            <SelectCard key={sev.id} isSelected={isSel} onClick={() => updateSettings({ minSeverityThreshold: sev.id as any })}>
                              <p className="text-xs font-medium text-white">{sev.label}</p>
                              <p className="text-[9px] text-slate-400">{sev.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Volume2} label="Telemetry Polling" />
                      <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                        {[{ id: 5, label: '5s' }, { id: 15, label: '15s' }, { id: 30, label: '30s' }, { id: 0, label: 'Manual' }].map((rate) => {
                          const isSel = settings.autoRefreshInterval === rate.id;
                          return (
                            <motion.button key={rate.id} whileHover={{ y: -1 }} whileTap={{ scale: 0.95 }} onClick={() => updateSettings({ autoRefreshInterval: rate.id as RefreshInterval })} className={cn('py-2 px-1 text-center rounded-lg border transition-colors', isSel ? 'bg-[#B5482E] text-white border-[#B5482E] font-bold shadow-sm' : 'bg-white/[0.04] border-white/10 text-slate-400 hover:text-white hover:bg-white/[0.08]')}>
                              {rate.label}
                            </motion.button>
                          );
                        })}
                      </div>
                    </div>
                  </TabContent>
                )}

                {/* UNITS */}
                {activeTab === 'units' && (
                  <TabContent tabKey="units" direction={direction}>
                    <div className="p-3.5 rounded-xl border border-white/10" style={{ background: 'rgba(255,255,255,0.04)' }}>
                      <p className="text-[10px] font-mono uppercase text-[#F97316] font-bold mb-2.5">Live Output Sample</p>
                      <div className="grid grid-cols-3 gap-2 font-mono text-center">
                        {[
                          { label: 'Temp', value: formatTemperature(32.4, settings.tempUnit), color: 'text-amber-400' },
                          { label: 'Wind', value: formatWindSpeed(68, settings.windUnit), color: 'text-sky-400' },
                          { label: 'Rain', value: formatRainfall(85.5, settings.rainUnit), color: 'text-blue-400' },
                        ].map((item) => (
                          <div key={item.label} className="bg-black/30 p-2 rounded-lg border border-white/10">
                            <span className="text-[9px] text-slate-500 block">{item.label}</span>
                            <span className={cn('text-sm font-bold', item.color)}>{item.value}</span>
                          </div>
                        ))}
                      </div>
                      <div className="mt-2 text-center text-[10px] font-mono text-slate-500">
                        <span className="text-emerald-400">{formatCoordinates(25.5941, 85.1376, settings.coordFormat)}</span>
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Gauge} label="Temperature" />
                      <div className="grid grid-cols-2 gap-2">
                        {[{ id: 'celsius', label: 'Celsius (°C)', desc: 'IMD standard' }, { id: 'fahrenheit', label: 'Fahrenheit (°F)', desc: 'Imperial' }].map((u) => {
                          const isSel = settings.tempUnit === u.id;
                          return (
                            <SelectCard key={u.id} isSelected={isSel} onClick={() => updateSettings({ tempUnit: u.id as TempUnit })}>
                              <p className="text-xs font-semibold text-white">{u.label}</p>
                              <p className="text-[10px] text-slate-400">{u.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Gauge} label="Wind Speed" />
                      <div className="grid grid-cols-3 gap-2">
                        {[{ id: 'kmh', label: 'km/h', desc: 'Civil' }, { id: 'knots', label: 'Knots', desc: 'Maritime' }, { id: 'ms', label: 'm/s', desc: 'Scientific' }].map((u) => {
                          const isSel = settings.windUnit === u.id;
                          return (
                            <SelectCard key={u.id} isSelected={isSel} onClick={() => updateSettings({ windUnit: u.id as WindUnit })} className="text-center">
                              <p className="text-xs font-mono font-semibold text-white">{u.label}</p>
                              <p className="text-[9px] text-slate-500">{u.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Gauge} label="Coordinates" />
                      <div className="space-y-1.5">
                        {[
                          { id: 'dd', label: 'Decimal Degrees', sample: '25.5941\u00b0 N, 85.1376\u00b0 E' },
                          { id: 'dms', label: 'Degrees Minutes Seconds', sample: "25\u00b035'38\"N, 85\u00b008'15\"E" },
                          ...(settings.advancedCoordFormats ? [{ id: 'mgrs', label: 'Military Grid (MGRS)', sample: '45R 25594 85137' }] : []),
                        ].map((cf) => {
                          const isSel = settings.coordFormat === cf.id;
                          return (
                            <SelectCard key={cf.id} isSelected={isSel} onClick={() => updateSettings({ coordFormat: cf.id as CoordFormat })} className="flex items-center justify-between">
                              <div><p className="text-xs font-medium text-white">{cf.label}</p><p className="text-[10px] font-mono text-slate-400">{cf.sample}</p></div>
                              {isSel && <Check className="w-4 h-4 text-[#F97316] shrink-0" />}
                            </SelectCard>
                          );
                        })}
                        {!settings.advancedCoordFormats && <p className="text-[10px] text-slate-500 pl-1">Enable MGRS in Security tab to unlock Military Grid.</p>}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Gauge} label="Timezone" />
                      <div className="grid grid-cols-2 gap-2">
                        {[{ id: 'ist', label: 'IST (UTC +05:30)', desc: 'New Delhi' }, { id: 'utc', label: 'UTC Zulu', desc: 'Aviation / Global' }].map((tz) => {
                          const isSel = settings.timezone === tz.id;
                          return (
                            <SelectCard key={tz.id} isSelected={isSel} onClick={() => updateSettings({ timezone: tz.id as TimezoneMode })}>
                              <p className="text-xs font-semibold text-white">{tz.label}</p>
                              <p className="text-[10px] text-slate-400">{tz.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>
                  </TabContent>
                )}

                {/* HUD */}
                {activeTab === 'hud' && (
                  <TabContent tabKey="hud" direction={direction}>
                    <div>
                      <SectionHeader icon={Globe} label="Interface Language / \u092d\u093e\u0937\u093e" />
                      <div className="grid grid-cols-3 gap-1.5 max-h-44 overflow-y-auto pr-1 drawer-scroll">
                        {Object.entries(SUPPORTED_LANGUAGES).map(([code, meta]) => {
                          const isSel = currentLang === code;
                          return (
                            <SelectCard key={code} isSelected={isSel} onClick={() => changeLang(code as any)} className="p-2">
                              <p className="text-xs truncate" style={{ fontFamily: meta.fontFamily }}>{meta.nativeName}</p>
                              <p className="text-[9px] text-slate-400 truncate">{meta.name}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Sliders} label="Interface Theme" />
                      <div className="grid grid-cols-3 gap-2">
                        {[{ id: 'dark', label: 'Dark', desc: 'Ops mode' }, { id: 'light', label: 'Light', desc: 'Day use' }, { id: 'high_contrast', label: 'High Contrast', desc: 'Field glare' }].map((m) => {
                          const isSel = settings.themeMode === m.id;
                          return (
                            <SelectCard key={m.id} isSelected={isSel} onClick={() => updateSettings({ themeMode: m.id as ThemeMode })} className="text-center">
                              <p className="text-xs font-semibold text-white">{m.label}</p>
                              <p className="text-[9px] text-slate-400 mt-0.5">{m.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Sliders} label="Display Density" />
                      <div className="grid grid-cols-2 gap-2">
                        {[{ id: 'standard', label: 'Standard', desc: 'Comfortable spacing' }, { id: 'compact', label: 'Compact', desc: 'High-density metrics' }].map((d) => {
                          const isSel = settings.uiDensity === d.id;
                          return (
                            <SelectCard key={d.id} isSelected={isSel} onClick={() => updateSettings({ uiDensity: d.id as any })}>
                              <p className="text-xs font-semibold text-white">{d.label}</p>
                              <p className="text-[10px] text-slate-400">{d.desc}</p>
                            </SelectCard>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <SectionHeader icon={Sliders} label="Visual Effects" />
                      <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06]" style={{ background: 'rgba(255,255,255,0.03)' }}>
                        <ToggleRow label="Glassmorphism & Glow" desc="Translucent cards and backdrop blurs" value={settings.glassmorphismEffects} onChange={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })} />
                        <ToggleRow label="Reduced Motion" desc="Disable animations on low-spec devices" value={settings.reducedMotion} onChange={() => updateSettings({ reducedMotion: !settings.reducedMotion })} />
                      </div>
                    </div>
                  </TabContent>
                )}

                {/* NOTIFICATIONS */}
                {activeTab === 'notifications' && (
                  <TabContent tabKey="notifications" direction={direction}>
                    <div>
                      <SectionHeader icon={Bell} label="Alert Delivery" />
                      <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06]" style={{ background: 'rgba(255,255,255,0.03)' }}>
                        <ToggleRow label="In-app notifications" desc="Dashboard banner for new events" value={settings.notifyInApp} onChange={() => updateSettings({ notifyInApp: !settings.notifyInApp })} />
                        <div className="px-3 py-2.5 space-y-2">
                          <ToggleRow
                            label={<span className="flex items-center gap-1.5"><Mail className="w-3 h-3" /> Email alerts</span>}
                            warn="\u26a0 Backend endpoint not yet live"
                            value={settings.notifyEmail}
                            onChange={() => updateSettings({ notifyEmail: !settings.notifyEmail })}
                          />
                          <AnimatePresence>
                            {settings.notifyEmail && (
                              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                <input type="email" placeholder="your@email.gov.in" value={settings.notifyEmailAddress} onChange={(e) => updateSettings({ notifyEmailAddress: e.target.value })} className="w-full px-3 py-1.5 text-xs rounded-lg bg-white/[0.08] border border-white/20 text-white placeholder-slate-500 focus:outline-none focus:border-[#B5482E] transition-colors" />
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                        <div className="px-3 py-2.5 space-y-2">
                          <ToggleRow
                            label={<span className="flex items-center gap-1.5"><Phone className="w-3 h-3" /> SMS / WhatsApp</span>}
                            warn="\u26a0 SMS gateway not yet live"
                            value={settings.notifyPhoneEnabled}
                            onChange={() => updateSettings({ notifyPhoneEnabled: !settings.notifyPhoneEnabled })}
                          />
                          <AnimatePresence>
                            {settings.notifyPhoneEnabled && (
                              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                <input type="tel" placeholder="+91 98765 43210" value={settings.notifyPhone} onChange={(e) => updateSettings({ notifyPhone: e.target.value })} className="w-full px-3 py-1.5 text-xs rounded-lg bg-white/[0.08] border border-white/20 text-white placeholder-slate-500 focus:outline-none focus:border-[#B5482E] transition-colors" />
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      </div>
                    </div>
                  </TabContent>
                )}

                {/* SECURITY */}
                {activeTab === 'security' && (
                  <TabContent tabKey="security" direction={direction}>
                    <div>
                      <SectionHeader icon={Timer} label="Auto-lock after idle" />
                      <p className="text-[10px] text-slate-500 mb-2.5">Shows a lock screen after inactivity. Click anywhere to resume.</p>
                      <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                        {([{ id: 0, label: 'Off' }, { id: 5, label: '5 min' }, { id: 15, label: '15 min' }, { id: 30, label: '30 min' }] as { id: IdleLockMinutes; label: string }[]).map((opt) => {
                          const isSel = settings.idleLockMinutes === opt.id;
                          return (
                            <motion.button key={opt.id} whileHover={{ y: -1 }} whileTap={{ scale: 0.95 }} onClick={() => updateSettings({ idleLockMinutes: opt.id })} className={cn('py-2 px-1 text-center rounded-lg border transition-colors', isSel ? 'bg-[#B5482E] text-white border-[#B5482E] font-bold shadow-sm' : 'bg-white/[0.04] border-white/10 text-slate-400 hover:text-white hover:bg-white/[0.08]')}>
                              {opt.label}
                            </motion.button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06]" style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <ToggleRow label="MGRS / Military Grid Reference" desc="Unlock MGRS coord format in Units tab" value={settings.advancedCoordFormats} onChange={() => updateSettings({ advancedCoordFormats: !settings.advancedCoordFormats })} />
                    </div>

                    <div className="p-3 rounded-xl border border-white/[0.08]" style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <p className="text-xs font-semibold text-white flex items-center gap-1.5"><Lock className="w-3.5 h-3.5 text-slate-400" /> Change Password</p>
                      {/* TODO(backend): POST /api/auth/change-password { currentPassword, newPassword } */}
                      <p className="text-[9px] text-amber-400 font-mono mt-0.5">\u26a0 Requires backend auth endpoint (not yet live)</p>
                      <p className="text-[10px] text-slate-500 mt-1">Contact your INDRA system administrator to reset credentials.</p>
                    </div>
                  </TabContent>
                )}

                {/* NETWORK */}
                {activeTab === 'network' && (
                  <TabContent tabKey="network" direction={direction}>
                    <div className="p-4 rounded-xl border border-white/[0.08]" style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <div className="flex items-center gap-2 mb-2">
                        <Wifi className="w-4 h-4 text-[#F97316]" />
                        <p className="text-xs font-semibold text-white">Live Data Source</p>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Every panel reads the live INDRA API and WebSocket. There is no simulated mode \u2014 an empty database shows empty, an unreachable backend shows an error.
                      </p>
                      <div className="mt-3 flex items-center gap-1.5 text-[10px] font-mono text-emerald-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        WebSocket connected
                      </div>
                    </div>
                  </TabContent>
                )}

                {/* SYSTEM */}
                {activeTab === 'system' && (
                  <TabContent tabKey="system" direction={direction}>
                    <div className="p-4 rounded-xl border border-white/[0.08] space-y-3" style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <div>
                        <h4 className="text-xs font-bold text-white uppercase font-mono">Preferences Backup</h4>
                        <p className="text-[11px] text-slate-400 mt-0.5">Export your GIS presets, alert thresholds and measurement units.</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} onClick={handleExportJson} className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#B5482E] hover:bg-[#A03D25] text-white text-xs font-semibold font-mono transition-colors shadow-sm">
                          <Download className="w-3.5 h-3.5" /> Export JSON
                        </motion.button>
                        <label className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-white/[0.07] hover:bg-white/[0.11] border border-white/15 text-slate-200 text-xs font-semibold font-mono cursor-pointer transition-colors shadow-sm">
                          <Upload className="w-3.5 h-3.5" /> Import
                          <input type="file" accept=".json" onChange={handleImportJson} className="hidden" />
                        </label>
                      </div>
                    </div>

                    <div className="p-4 rounded-xl border border-[#8C2F26]/30 space-y-2" style={{ background: 'rgba(140,47,38,0.10)' }}>
                      <div className="flex items-center gap-2 text-rose-400 text-xs font-bold font-mono">
                        <AlertTriangle className="w-4 h-4" />
                        FACTORY DEFAULTS RESET
                      </div>
                      <p className="text-xs text-slate-400">Reverts all GIS basemaps, audio alarms, measurement units and telemetry rates.</p>
                      <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} onClick={() => { resetSettings(); showToast('All settings reset to factory defaults'); }} className="mt-1 flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#8C2F26]/30 hover:bg-[#8C2F26]/50 text-rose-200 border border-[#8C2F26]/50 text-xs font-mono font-semibold transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Reset to Defaults
                      </motion.button>
                    </div>
                  </TabContent>
                )}

              </div>{/* end scroll area */}

              {/* Footer — premium CTA (Phase E2) */}
              <div className="shrink-0 px-4 py-3 flex items-center justify-between" style={{ background: 'rgba(0,0,0,0.28)', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-center gap-1.5 text-[10px] font-mono text-slate-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
                  Auto-saved to local memory
                </div>
                <Link href="/settings" onClick={onClose} className="group flex items-center gap-1.5 text-[11px] font-semibold text-[#F97316] hover:text-[#FFA04A] transition-colors">
                  <span>Full Settings</span>
                  <motion.span className="inline-flex" whileHover={{ x: 3 }} transition={{ type: 'spring', stiffness: 400, damping: 20 }}>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </motion.span>
                </Link>
              </div>

            </div>{/* end right panel */}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
