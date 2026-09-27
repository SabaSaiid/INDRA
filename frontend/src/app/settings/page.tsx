'use client';

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Settings,
  Globe,
  Map as MapIcon,
  Volume2,
  VolumeX,
  Play,
  Layers,
  Sparkles,
  Compass,
  Gauge,
  Thermometer,
  Wind,
  CloudRain,
  Clock,
  Radio,
  Wifi,
  RotateCcw,
  Download,
  Upload,
  ExternalLink,
  Shield,
  Check,
  AlertTriangle,
  Zap,
  Sliders,
  Database,
  Activity,
  Server,
  RefreshCw,
  Bell,
  Mail,
  Phone,
  Lock,
  MapPin,
  EyeOff,
  Timer,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import {
  useSettings,
  type BasemapPreset,
  type ProjectionPreset,
  type SirenPattern,
  type TempUnit,
  type WindUnit,
  type RainUnit,
  type PressureUnit,
  type CoordFormat,
  type TimezoneMode,
  type ThemeMode,
  type UiDensity,
  type SeverityThreshold,
  type RefreshInterval,
  type IdleLockMinutes,
} from '@/lib/useSettings';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { fetchHealth, type HealthReport } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from '@/lib/i18n/types';

export default function SettingsPage() {
  const { t, language, setLanguage } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const { settings, updateSettings, resetSettings, testAlarm } = useSettings();
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((h) => { if (!cancelled) { setHealth(h); setHealthError(null); } })
      .catch((err) => {
        if (!cancelled) setHealthError(err instanceof Error ? err.message : 'Backend unreachable');
      });
    return () => { cancelled = true; };
  }, []);
  const [activeSection, setActiveSection] = useState<'all' | 'map' | 'alerts' | 'units' | 'hud' | 'network' | 'notifications' | 'aor' | 'security' | 'backup'>('all');
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleTestAudio = (pattern?: SirenPattern) => {
    setIsPlayingAudio(true);
    testAlarm(pattern);
    setTimeout(() => setIsPlayingAudio(false), 1800);
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(settings, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `indra_settings_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast('Configuration exported as JSON file');
  };

  const handleImportJson = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsed = JSON.parse(event.target?.result as string);
        updateSettings(parsed);
        showToast('Configuration imported');
      } catch {
        showToast('Failed to parse settings JSON file');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="min-h-screen bg-[#F7F3EA] text-[#1E2A3B]">
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

        <main className="p-4 lg:p-6 max-w-[1500px] mx-auto space-y-6">
          {/* Toast Notification */}
          <AnimatePresence>
            {toastMessage && (
              <motion.div
                initial={{ opacity: 0, y: -10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.98 }}
                className="fixed top-20 right-6 z-50 bg-[#182235] text-white border border-white/15 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2.5 text-xs font-mono font-semibold"
              >
                <Check className="w-4 h-4 text-emerald-400" />
                <span>{toastMessage}</span>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Header Banner — Tactical Command Console Bar */}
          <motion.div
            variants={fadeIn}
            initial="hidden"
            animate="visible"
            className="text-white p-5 lg:p-6 rounded-xl border border-white/10 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4"
            style={{ background: 'linear-gradient(135deg, #182235 0%, #111827 100%)' }}
          >
            <div>
              <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
                <div className="w-8 h-8 rounded-lg bg-[#B5482E]/25 border border-[#B5482E]/50 flex items-center justify-center text-[#F97316]">
                  <Settings className="w-4 h-4 animate-spin-slow" />
                </div>
                <h1
                  className="text-lg lg:text-xl font-bold tracking-tight text-white"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  {t('nav.system_settings')}
                </h1>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-white/10 text-slate-300 border border-white/15">
                  SIH26069 • SIXTH SENSE
                </span>
              </div>
              <p className="text-xs text-slate-300 max-w-3xl leading-relaxed">
                Map, sound, unit and display preferences for this dashboard. They are saved only in this browser, never on the server.
              </p>
            </div>

            <div className="flex items-center gap-2.5 shrink-0">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.08] border border-white/15 text-xs font-mono text-slate-300">
                Saved in this browser
              </div>
              <button
                onClick={handleExportJson}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-[#B5482E] hover:bg-[#A03D25] text-white text-xs font-semibold font-mono transition-all shadow-sm"
              >
                <Download className="w-3.5 h-3.5" />
                Export JSON
              </button>
            </div>
          </motion.div>

          {/* Category Filter Pills */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
            {[
              { id: 'all', label: 'All Settings' },
              { id: 'map', label: '🗺️ Tactical GIS' },
              { id: 'alerts', label: '🔊 Audio & Refresh' },
              { id: 'units', label: '📐 Units & Grid' },
              { id: 'hud', label: '🖥️ Appearance' },
              { id: 'notifications', label: '🔔 Notifications' },
              { id: 'aor', label: '📍 Area of Ops' },
              { id: 'security', label: '🔒 Session Security' },
              { id: 'network', label: '🌐 Network' },
              { id: 'backup', label: '⚙️ Backup & Diagnostics' },
            ].map((cat) => (
              <button
                key={cat.id}
                onClick={() => setActiveSection(cat.id as any)}
                className={cn(
                  'px-3.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
                  activeSection === cat.id
                    ? 'bg-[#182235] text-white font-semibold shadow-sm border border-white/10'
                    : 'bg-[#F0EBE0] text-[#4A5568] hover:text-[#1E2A3B] hover:bg-[#E8E2D4] border border-[#E8E2D4]'
                )}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 1. TACTICAL GEOSPATIAL & MAP */}
            {(activeSection === 'all' || activeSection === 'map') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Globe className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Tactical Geospatial &amp; Map Defaults
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Projection, basemap and globe behaviour</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    GIS CONSOLE
                  </span>
                </div>

                {/* Projection Mode */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Default Tactical Projection
                  </label>
                  <div className="grid grid-cols-2 gap-2.5">
                    {[
                      { id: 'globe', label: '3D Spherical Earth', desc: 'Subcontinental orbital curvature & atmosphere', icon: Globe },
                      { id: 'mercator', label: '2D Planar Mercator', desc: 'High-speed flat grid for low-latency ops', icon: MapIcon },
                    ].map((proj) => {
                      const isSelected = settings.mapProjection === proj.id;
                      const Icon = proj.icon;
                      return (
                        <button
                          key={proj.id}
                          onClick={() => updateSettings({ mapProjection: proj.id as ProjectionPreset })}
                          className={cn(
                            'p-3 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] ring-2 ring-[#B5482E]/20 shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0] hover:border-[#D8D0C0]'
                          )}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <Icon className={cn('w-4 h-4', isSelected ? 'text-[#B5482E]' : 'text-[#7A8599]')} />
                            {isSelected && <Check className="w-4 h-4 text-[#B5482E]" />}
                          </div>
                          <p className="text-xs font-bold text-[#1E2A3B]">{proj.label}</p>
                          <p className="text-[10px] text-[#7A8599] mt-0.5">{proj.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Basemap Presets */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Default Basemap Style
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'satellite', label: 'Satellite Orthophoto', source: 'ESRI World Imagery' },
                      { id: 'dark', label: 'Dark Tactical HUD', source: 'CARTO Dark Matter' },
                      { id: 'topo', label: 'Topographic Hybrid', source: 'Terrain & Contours' },
                      { id: 'street', label: 'Clean Street Vector', source: 'OpenStreetMap' },
                    ].map((base) => {
                      const isSelected = settings.defaultBasemap === base.id;
                      return (
                        <button
                          key={base.id}
                          onClick={() => updateSettings({ defaultBasemap: base.id as BasemapPreset })}
                          className={cn(
                            'p-2.5 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0] hover:border-[#D8D0C0]'
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-[#1E2A3B]">{base.label}</span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-[#B5482E]" />}
                          </div>
                          <span className="text-[10px] font-mono text-[#7A8599] mt-0.5 block">{base.source}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Removed 22 Sep: four map-layer toggles that no feed backed. */}
                <div className="p-3 bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl">
                  <p className="text-xs font-semibold text-[#1E2A3B]">Map layers</p>
                  <p className="text-[10px] text-[#7A8599] mt-0.5">
                    The map draws three live layers: INDRA events, official warnings from SACHET,
                    and citizen reports not yet part of an event. Show or hide them with the chips
                    on the map itself.
                  </p>
                </div>

                {/* Auto Rotation */}
                <div className="p-3 bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-[#1E2A3B]">Globe Idle Auto-Orbit</p>
                    <p className="text-[10px] text-[#7A8599]">Slow atmospheric rotation when map interaction is idle</p>
                  </div>
                  <button
                    onClick={() => updateSettings({ globeAutoRotate: !settings.globeAutoRotate })}
                    className={cn(
                      'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                      settings.globeAutoRotate ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                    )}
                  >
                    <span
                      className={cn(
                        'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                        settings.globeAutoRotate ? 'translate-x-4' : 'translate-x-0'
                      )}
                    />
                  </button>
                </div>
              </motion.div>
            )}

            {/* 2. AUDIO BEACON & REFRESH */}
            {(activeSection === 'all' || activeSection === 'alerts') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Volume2 className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Audio Beacon &amp; Refresh
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">A tone synthesized in this browser, and the refresh rate</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    WEB AUDIO API
                  </span>
                </div>

                {/* Master Audio Toggle */}
                <div className="p-4 bg-[#FBF2E4] rounded-xl border border-[#E8C0B5] flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-[#B5482E] text-white flex items-center justify-center shadow-sm">
                      <Volume2 className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-[#1E2A3B]">Audio Beacon</p>
                      <p className="text-[10px] text-[#4A5568]">INDRA issues no alerts, so only the test below plays this tone</p>
                    </div>
                  </div>
                  <button
                    onClick={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })}
                    className={cn(
                      'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                      settings.audioAlertsEnabled ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                    )}
                  >
                    <span
                      className={cn(
                        'inline-block h-5 w-5 transform rounded-full bg-white transition shadow-sm',
                        settings.audioAlertsEnabled ? 'translate-x-5' : 'translate-x-0'
                      )}
                    />
                  </button>
                </div>

                {/* Volume Slider & Test Sound */}
                <div className="p-3.5 bg-[#F0EBE0]/70 rounded-xl border border-[#E8E2D4] space-y-3">
                  <div className="flex items-center justify-between text-xs font-mono text-[#1E2A3B]">
                    <span className="font-semibold">Beacon Volume</span>
                    <span className="font-bold text-[#B5482E]">{Math.round(settings.alertVolume * 100)}%</span>
                  </div>
                  <input
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    disabled={!settings.audioAlertsEnabled}
                    value={settings.alertVolume}
                    onChange={(e) => updateSettings({ alertVolume: parseFloat(e.target.value) })}
                    className="w-full accent-[#B5482E] h-1.5 bg-[#D8D0C0] rounded-lg cursor-pointer disabled:opacity-40"
                  />
                  <div className="flex items-center justify-between pt-2 border-t border-[#E8E2D4]">
                    <span className="text-[11px] text-[#7A8599]">Browser Synthesizer Test</span>
                    <button
                      onClick={() => handleTestAudio()}
                      disabled={!settings.audioAlertsEnabled || isPlayingAudio}
                      className={cn(
                        'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all',
                        isPlayingAudio
                          ? 'bg-[#B5482E] text-white animate-pulse'
                          : 'bg-[#B5482E]/15 text-[#B5482E] hover:bg-[#B5482E]/25 border border-[#B5482E]/30'
                      )}
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                      {isPlayingAudio ? 'Playing…' : 'Test Tone'}
                    </button>
                  </div>
                </div>

                {/* Siren Pattern */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Tone Pattern
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'warble_fast', label: 'Tactical Warble', desc: '8Hz rapid high-pitch disaster warning' },
                      { id: 'siren_continuous', label: 'Continuous Air Siren', desc: 'Dual-frequency civil defense sweep' },
                      { id: 'pulsed_beacon', label: 'Pulsed Beacon', desc: '3-stage rapid tactical beeps' },
                      { id: 'chime_two_tone', label: 'Operational Chime', desc: 'Subtle two-tone operational ping' },
                    ].map((pat) => {
                      const isSelected = settings.sirenPattern === pat.id;
                      return (
                        <button
                          key={pat.id}
                          onClick={() => {
                            updateSettings({ sirenPattern: pat.id as SirenPattern });
                            if (settings.audioAlertsEnabled) handleTestAudio(pat.id as SirenPattern);
                          }}
                          className={cn(
                            'p-2.5 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0] hover:border-[#D8D0C0]'
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-[#1E2A3B]">{pat.label}</span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-[#B5482E]" />}
                          </div>
                          <span className="text-[10px] text-[#7A8599] mt-0.5 block">{pat.desc}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Polling Interval */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Refresh Frequency
                  </label>
                  <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                    {[
                      { id: 5, label: '5s (Live)' },
                      { id: 15, label: '15s (Normal)' },
                      { id: 30, label: '30s (Relaxed)' },
                      { id: 0, label: 'Manual' },
                    ].map((rate) => {
                      const isSelected = settings.autoRefreshInterval === rate.id;
                      return (
                        <button
                          key={rate.id}
                          onClick={() => updateSettings({ autoRefreshInterval: rate.id as RefreshInterval })}
                          className={cn(
                            'py-2 px-1 text-center rounded-xl border transition-all',
                            isSelected
                              ? 'bg-[#182235] text-white font-bold border-[#182235] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          {rate.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </motion.div>
            )}

            {/* 3. UNITS & FORMATS */}
            {(activeSection === 'all' || activeSection === 'units') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Gauge className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Units &amp; Formats
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Measurement units, coordinate notation and timezone</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    UNITS
                  </span>
                </div>

                {/* Temperature & Wind Grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                      Temperature
                    </label>
                    <div className="grid grid-cols-2 gap-1.5">
                      {[
                        { id: 'celsius', label: '°C Celsius' },
                        { id: 'fahrenheit', label: '°F Fahrenheit' },
                      ].map((t) => (
                        <button
                          key={t.id}
                          onClick={() => updateSettings({ tempUnit: t.id as TempUnit })}
                          className={cn(
                            'py-2 px-1 text-center rounded-xl border text-xs font-medium transition-all',
                            settings.tempUnit === t.id
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#B5482E] font-bold shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                      Wind Speed
                    </label>
                    <div className="grid grid-cols-3 gap-1">
                      {[
                        { id: 'kmh', label: 'km/h' },
                        { id: 'knots', label: 'knots' },
                        { id: 'ms', label: 'm/s' },
                      ].map((w) => (
                        <button
                          key={w.id}
                          onClick={() => updateSettings({ windUnit: w.id as WindUnit })}
                          className={cn(
                            'py-2 px-1 text-center rounded-xl border text-xs font-mono font-medium transition-all',
                            settings.windUnit === w.id
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#B5482E] font-bold shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          {w.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Coordinate System */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Geospatial Coordinate Notation
                  </label>
                  <div className="space-y-1.5">
                    {[
                      { id: 'dd', label: 'Decimal Degrees (Standard)', sample: 'dd.dddd° N, ddd.dddd° E' },
                      { id: 'dms', label: 'Degrees Minutes Seconds (DMS)', sample: 'dd°mm\'ss"N, ddd°mm\'ss"E' },
                    ].map((cf) => {
                      const isSelected = settings.coordFormat === cf.id;
                      return (
                        <button
                          key={cf.id}
                          onClick={() => updateSettings({ coordFormat: cf.id as CoordFormat })}
                          className={cn(
                            'w-full p-2.5 rounded-xl border text-left flex items-center justify-between transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:border-[#D8D0C0]'
                          )}
                        >
                          <div>
                            <p className="text-xs font-semibold text-[#1E2A3B]">{cf.label}</p>
                            <p className="text-[10px] font-mono text-[#7A8599]">{cf.sample}</p>
                          </div>
                          {isSelected && <Check className="w-4 h-4 text-[#B5482E]" />}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Timezone */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Operational Timezone Display
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'ist', label: 'Indian Standard Time (IST)', desc: 'UTC+05:30 (New Delhi)' },
                      { id: 'utc', label: 'UTC Zulu Time', desc: 'UTC+00:00 (Aviation standard)' },
                    ].map((tz) => {
                      const isSelected = settings.timezone === tz.id;
                      return (
                        <button
                          key={tz.id}
                          onClick={() => updateSettings({ timezone: tz.id as TimezoneMode })}
                          className={cn(
                            'p-2.5 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:border-[#D8D0C0]'
                          )}
                        >
                          <p className="text-xs font-semibold text-[#1E2A3B]">{tz.label}</p>
                          <p className="text-[10px] text-[#7A8599]">{tz.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </motion.div>
            )}

            {/* 4. COMMAND HUD & DISPLAY */}
            {(activeSection === 'all' || activeSection === 'hud') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Sliders className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Command HUD &amp; Theme Engine
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Outdoor glare contrast, layout density &amp; visual performance</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    APPEARANCE
                  </span>
                </div>

                {/* Interface Language & Script */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] flex items-center gap-1.5 mb-1.5">
                    <Globe className="w-3.5 h-3.5 text-[#B5482E]" />
                    Interface Language / बहुभाषी प्रणाली (12 Languages)
                  </label>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                    {(Object.entries(SUPPORTED_LANGUAGES) as [SupportedLanguage, typeof SUPPORTED_LANGUAGES[SupportedLanguage]][]).map(([code, meta]) => {
                      const isSelected = language === code;
                      return (
                        <button
                          key={code}
                          onClick={() => {
                            setLanguage(code);
                            showToast(`Language switched to ${meta.name} (${meta.nativeName})`);
                          }}
                          className={cn(
                            'p-2.5 rounded-xl border text-left flex items-center justify-between transition-all',
                            isSelected
                              ? 'bg-[#182235] text-white border-[#182235] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          <div className="min-w-0">
                            <p className="text-xs font-bold truncate" style={{ fontFamily: meta.fontFamily }}>
                              {meta.nativeName}
                            </p>
                            <p className={cn('text-[10px] truncate', isSelected ? 'text-slate-300' : 'text-[#7A8599]')}>
                              {meta.name}
                            </p>
                          </div>
                          {isSelected && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Theme Mode */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Interface Theme Mode
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { id: 'dark', label: 'Dark Tactical', desc: 'Ops Room' },
                      { id: 'light', label: 'Clean Light', desc: 'Standard Office' },
                      { id: 'high_contrast', label: 'High Contrast', desc: 'Field Glare HUD' },
                    ].map((th) => {
                      const isSelected = settings.themeMode === th.id;
                      return (
                        <button
                          key={th.id}
                          onClick={() => updateSettings({ themeMode: th.id as ThemeMode })}
                          className={cn(
                            'p-3 rounded-xl border text-center transition-all',
                            isSelected
                              ? 'bg-[#182235] text-white border-[#182235] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          <p className="text-xs font-bold">{th.label}</p>
                          <p className="text-[9px] text-[#7A8599] mt-0.5">{th.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* UI Density */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] block mb-1.5">
                    Display Density
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'standard', label: 'Standard Spacious', desc: 'Comfortable spacing for mouse and touch screens' },
                      { id: 'compact', label: 'Tactical Compact', desc: 'Maximizes visible telemetry per display square inch' },
                    ].map((d) => {
                      const isSelected = settings.uiDensity === d.id;
                      return (
                        <button
                          key={d.id}
                          onClick={() => updateSettings({ uiDensity: d.id as UiDensity })}
                          className={cn(
                            'p-2.5 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-[#FBF2E4] border-[#B5482E] text-[#1E2A3B] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:border-[#D8D0C0]'
                          )}
                        >
                          <p className="text-xs font-semibold text-[#1E2A3B]">{d.label}</p>
                          <p className="text-[10px] text-[#7A8599]">{d.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Effects Switches */}
                <div className="bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl divide-y divide-[#E8E2D4]">
                  <div className="p-3 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-[#1E2A3B]">Glassmorphism &amp; Glow Filters</p>
                      <p className="text-[10px] text-[#7A8599]">Translucent navigation headers and backdrop blurs</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.glassmorphismEffects ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                      )}
                    >
                      <span
                        className={cn(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                          settings.glassmorphismEffects ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>

                  <div className="p-3 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-[#1E2A3B]">Reduced Motion Mode</p>
                      <p className="text-[10px] text-[#7A8599]">Disable animations for slower devices or accessibility</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ reducedMotion: !settings.reducedMotion })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.reducedMotion ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                      )}
                    >
                      <span
                        className={cn(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                          settings.reducedMotion ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                </div>
              </motion.div>
            )}

            {/* 5. NOTIFICATIONS */}
            {(activeSection === 'all' || activeSection === 'notifications') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center">
                      <Bell className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Notifications &amp; Alerts Delivery
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Control where critical alerts reach you</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    ALERTS
                  </span>
                </div>

                {/* In-app toasts */}
                <div className="bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl divide-y divide-[#E8E2D4]">
                  <div className="p-3 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-[#1E2A3B]">In-app toast notifications</p>
                      <p className="text-[10px] text-[#7A8599]">Show a banner inside the dashboard for new events</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ notifyInApp: !settings.notifyInApp })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.notifyInApp ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                      )}
                    >
                      <span
                        className={cn(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                          settings.notifyInApp ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>

                  {/* Email toggle */}
                  <div className="p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-semibold text-[#1E2A3B] flex items-center gap-1.5">
                          <Mail className="w-3.5 h-3.5" />
                          Email notifications
                        </p>
                        {/* TODO(backend): POST /api/notifications/subscribe { channel: 'email', address } */}
                        <p className="text-[10px] text-amber-600 font-mono">⚠ Requires backend email delivery endpoint (not yet live)</p>
                      </div>
                      <button
                        onClick={() => updateSettings({ notifyEmail: !settings.notifyEmail })}
                        className={cn(
                          'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                          settings.notifyEmail ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                        )}
                      >
                        <span
                          className={cn(
                            'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                            settings.notifyEmail ? 'translate-x-4' : 'translate-x-0'
                          )}
                        />
                      </button>
                    </div>
                    {settings.notifyEmail && (
                      <input
                        type="email"
                        placeholder="your@email.gov.in"
                        value={settings.notifyEmailAddress}
                        onChange={(e) => updateSettings({ notifyEmailAddress: e.target.value })}
                        className="w-full px-3 py-1.5 text-xs rounded-lg border border-[#E8E2D4] bg-white text-[#1E2A3B] placeholder-[#A0AABB] focus:outline-none focus:border-[#B5482E]"
                      />
                    )}
                  </div>

                  {/* SMS toggle */}
                  <div className="p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-semibold text-[#1E2A3B] flex items-center gap-1.5">
                          <Phone className="w-3.5 h-3.5" />
                          SMS / WhatsApp alerts
                        </p>
                        {/* TODO(backend): POST /api/notifications/subscribe { channel: 'sms', phone } via Twilio / MSG91 */}
                        <p className="text-[10px] text-amber-600 font-mono">⚠ Requires backend SMS gateway (not yet live)</p>
                      </div>
                      <button
                        onClick={() => updateSettings({ notifyPhoneEnabled: !settings.notifyPhoneEnabled })}
                        className={cn(
                          'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                          settings.notifyPhoneEnabled ? 'bg-[#B5482E]' : 'bg-[#D8D0C0]'
                        )}
                      >
                        <span
                          className={cn(
                            'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                            settings.notifyPhoneEnabled ? 'translate-x-4' : 'translate-x-0'
                          )}
                        />
                      </button>
                    </div>
                    {settings.notifyPhoneEnabled && (
                      <input
                        type="tel"
                        placeholder="+91 98765 43210"
                        value={settings.notifyPhone}
                        onChange={(e) => updateSettings({ notifyPhone: e.target.value })}
                        className="w-full px-3 py-1.5 text-xs rounded-lg border border-[#E8E2D4] bg-white text-[#1E2A3B] placeholder-[#A0AABB] focus:outline-none focus:border-[#B5482E]"
                      />
                    )}
                  </div>
                </div>
              </motion.div>
            )}

            {/* 6. AREA OF RESPONSIBILITY */}
            {(activeSection === 'all' || activeSection === 'aor') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center">
                      <MapPin className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Area of Responsibility (AOR)
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Scope dashboard alerts to a specific state</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    AOR FILTER
                  </span>
                </div>

                <p className="text-[11px] text-[#7A8599]">
                  When a state is selected, only events, alerts, and reports from that state appear in the live feed
                  and alerts sidebar. Map view remains all-India.
                </p>

                <div className="grid grid-cols-3 sm:grid-cols-4 gap-1.5 text-xs font-medium">
                  {[
                    { code: null, label: 'All India' },
                    { code: 'AP', label: 'Andhra Pradesh' },
                    { code: 'AR', label: 'Arunachal' },
                    { code: 'AS', label: 'Assam' },
                    { code: 'BR', label: 'Bihar' },
                    { code: 'CG', label: 'Chhattisgarh' },
                    { code: 'GA', label: 'Goa' },
                    { code: 'GJ', label: 'Gujarat' },
                    { code: 'HR', label: 'Haryana' },
                    { code: 'HP', label: 'Himachal' },
                    { code: 'JH', label: 'Jharkhand' },
                    { code: 'KA', label: 'Karnataka' },
                    { code: 'KL', label: 'Kerala' },
                    { code: 'MP', label: 'Madhya Pradesh' },
                    { code: 'MH', label: 'Maharashtra' },
                    { code: 'MN', label: 'Manipur' },
                    { code: 'ML', label: 'Meghalaya' },
                    { code: 'MZ', label: 'Mizoram' },
                    { code: 'NL', label: 'Nagaland' },
                    { code: 'OD', label: 'Odisha' },
                    { code: 'PB', label: 'Punjab' },
                    { code: 'RJ', label: 'Rajasthan' },
                    { code: 'SK', label: 'Sikkim' },
                    { code: 'TN', label: 'Tamil Nadu' },
                    { code: 'TS', label: 'Telangana' },
                    { code: 'TR', label: 'Tripura' },
                    { code: 'UP', label: 'Uttar Pradesh' },
                    { code: 'UK', label: 'Uttarakhand' },
                    { code: 'WB', label: 'West Bengal' },
                  ].map((s) => {
                    const isSelected = settings.aorState === s.code;
                    return (
                      <button
                        key={s.code ?? 'all'}
                        onClick={() => updateSettings({ aorState: s.code })}
                        className={cn(
                          'py-2 px-2 rounded-xl border text-center transition-all',
                          isSelected
                            ? 'bg-[#182235] text-white border-[#182235] font-bold shadow-sm'
                            : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                        )}
                      >
                        {s.label}
                      </button>
                    );
                  })}
                </div>

                {settings.aorState && (
                  <div className="p-2.5 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-2 text-xs text-amber-700">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span>
                      AOR filter is active ({settings.aorState}). Events outside this state are hidden from the live feed.
                      {/* TODO(backend): GET /api/events?state={settings.aorState} — backend filter endpoint needed */}
                      <span className="block font-mono mt-0.5 text-amber-500">Note: backend state-filter endpoint not yet implemented; filter is UI-only.</span>
                    </span>
                  </div>
                )}
              </motion.div>
            )}

            {/* 7. SESSION SECURITY */}
            {(activeSection === 'all' || activeSection === 'security') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center">
                      <Lock className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Session &amp; Access Security
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Idle lock and password management</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    SECURITY
                  </span>
                </div>

                {/* Idle lock timer */}
                <div>
                  <label className="text-xs font-semibold text-[#1E2A3B] flex items-center gap-1.5 mb-1.5">
                    <Timer className="w-3.5 h-3.5 text-[#B5482E]" />
                    Auto-lock after idle
                  </label>
                  <p className="text-[10px] text-[#7A8599] mb-2">
                    Show a lock screen after the selected period of inactivity. Requires a click to resume.
                  </p>
                  <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                    {([
                      { id: 0, label: 'Disabled' },
                      { id: 5, label: '5 min' },
                      { id: 15, label: '15 min' },
                      { id: 30, label: '30 min' },
                    ] as { id: IdleLockMinutes; label: string }[]).map((opt) => {
                      const isSelected = settings.idleLockMinutes === opt.id;
                      return (
                        <button
                          key={opt.id}
                          onClick={() => updateSettings({ idleLockMinutes: opt.id })}
                          className={cn(
                            'py-2 px-1 text-center rounded-xl border transition-all',
                            isSelected
                              ? 'bg-[#182235] text-white font-bold border-[#182235] shadow-sm'
                              : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                          )}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Change password */}
                <div className="p-3.5 bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl">
                  <p className="text-xs font-semibold text-[#1E2A3B] flex items-center gap-1.5 mb-0.5">
                    <EyeOff className="w-3.5 h-3.5" />
                    Change Password
                  </p>
                  {/* TODO(backend): POST /api/auth/change-password { currentPassword, newPassword } */}
                  <p className="text-[10px] text-amber-600 font-mono mb-2">
                    ⚠ Password change requires a backend authentication endpoint (not yet live).
                  </p>
                  <p className="text-[10px] text-[#7A8599]">
                    Contact your INDRA system administrator to reset credentials.
                  </p>
                </div>
              </motion.div>
            )}

            {/* 8 (was 5). FIELD STATION & DATA SOURCE */}
            {(activeSection === 'all' || activeSection === 'network') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Wifi className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Network &amp; Data Source
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Where the dashboard&apos;s data comes from</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    NETWORK
                  </span>
                </div>

                {/* Removed 22 Sep: a live-or-mock source switch that nothing read. */}
                <div className="p-3 bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl">
                  <p className="text-xs font-semibold text-[#1E2A3B]">Data source</p>
                  <p className="text-[10px] text-[#7A8599] mt-0.5">
                    Every panel reads the live INDRA API and WebSocket. There is no mock mode: an
                    empty database shows as empty, and an unreachable backend says so.
                  </p>
                </div>
              </motion.div>
            )}

            {/* 6. SYSTEM BACKUP, DIAGNOSTICS & RESET */}
            {(activeSection === 'all' || activeSection === 'backup') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-[#FDFAF5] rounded-xl border border-[#E8E2D4] p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[#E8E2D4]">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-[#F0EBE0] text-[#B5482E] border border-[#E8E2D4] flex items-center justify-center font-bold">
                      <Shield className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-[#1E2A3B]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                        Backup, Diagnostics &amp; Recovery
                      </h2>
                      <p className="text-[11px] text-[#7A8599]">Configuration JSON exports and factory reset</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#F0EBE0] text-[#4A5568] font-semibold border border-[#E8E2D4]">
                    DIAGNOSTICS
                  </span>
                </div>

                {/* Live dependency checks from /healthz. */}
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-[#1E2A3B] block">
                    Backend health (/healthz)
                  </span>
                  {healthError ? (
                    <p className="text-xs text-[#8C2F26] font-semibold">{healthError}</p>
                  ) : !health ? (
                    <p className="text-xs text-[#7A8599]">Checking…</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      {Object.entries(health.checks).map(([name, check]) => (
                        <div key={name} className="p-2.5 rounded-xl bg-[#F0EBE0]/70 border border-[#E8E2D4]">
                          <span className="text-[10px] text-[#7A8599] block">{name}</span>
                          <span className={cn('font-bold', check.status === 'up' ? 'text-[#4C7A5B]' : 'text-[#8C2F26]')}>
                            {check.status === 'up' ? 'UP' : 'DOWN'}
                            {check.latency_ms != null ? ` • ${check.latency_ms} ms` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Export / Import */}
                <div className="p-4 bg-[#F0EBE0]/70 border border-[#E8E2D4] rounded-xl space-y-2.5">
                  <p className="text-xs font-semibold text-[#1E2A3B]">Configuration JSON Profile</p>
                  <p className="text-[11px] text-[#7A8599]">
                    Save these preferences to a file, or load a file saved from another browser.
                  </p>
                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={handleExportJson}
                      className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#182235] hover:bg-[#111827] text-white text-xs font-semibold font-mono transition-all shadow-sm"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Export JSON
                    </button>
                    <label className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#FDFAF5] hover:bg-[#F0EBE0] border border-[#E8E2D4] text-[#1E2A3B] text-xs font-semibold font-mono cursor-pointer transition-colors shadow-sm">
                      <Upload className="w-3.5 h-3.5" />
                      Import JSON
                      <input
                        type="file"
                        accept=".json"
                        onChange={handleImportJson}
                        className="hidden"
                      />
                    </label>
                  </div>
                </div>

                {/* Factory Reset */}
                <div className="p-4 bg-[#FBF2E4] border border-[#E8C0B5] rounded-xl space-y-2">
                  <div className="flex items-center gap-2 text-[#8C2F26] font-bold text-xs">
                    <AlertTriangle className="w-4 h-4" />
                    RESET TO FACTORY DEFAULTS
                  </div>
                  <p className="text-[11px] text-[#4A5568]">
                    Restores the default for every preference on this page, in this browser.
                  </p>
                  <div className="pt-1">
                    {!showResetConfirm ? (
                      <button
                        onClick={() => setShowResetConfirm(true)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#8C2F26] hover:bg-[#70241C] text-white text-xs font-semibold font-mono transition-colors shadow-sm"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Reset All Settings
                      </button>
                    ) : (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => {
                            resetSettings();
                            setShowResetConfirm(false);
                            showToast('All settings reset to defaults');
                          }}
                          className="px-3 py-1.5 rounded-lg bg-[#8C2F26] hover:bg-[#70241C] text-white text-xs font-bold font-mono shadow-sm"
                        >
                          Confirm Reset
                        </button>
                        <button
                          onClick={() => setShowResetConfirm(false)}
                          className="px-3 py-1.5 rounded-lg bg-[#FDFAF5] border border-[#E8E2D4] text-[#1E2A3B] text-xs font-medium hover:bg-[#F0EBE0]"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
