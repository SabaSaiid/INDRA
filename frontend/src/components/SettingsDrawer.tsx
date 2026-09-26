'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import {
  X,
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

type TabKey = 'map' | 'alerts' | 'units' | 'hud' | 'network' | 'system';

export default function SettingsDrawer({ isOpen, onClose }: SettingsDrawerProps) {
  const { t, language: currentLang, setLanguage: changeLang } = useTranslation();
  const { settings, updateSettings, resetSettings, testAlarm } = useSettings();
  const [activeTab, setActiveTab] = useState<TabKey>('map');
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // Close on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
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
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `indra_settings_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast('Configuration exported as JSON');
  };

  const handleImportJson = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsed = JSON.parse(event.target?.result as string);
        updateSettings(parsed);
        showToast('Configuration imported successfully');
      } catch {
        showToast('Failed to parse settings JSON file');
      }
    };
    reader.readAsText(file);
  };

  const tabs: { key: TabKey; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { key: 'map', label: 'Tactical Map', icon: Globe },
    { key: 'alerts', label: 'Audio & Siren', icon: Volume2 },
    { key: 'units', label: 'Units & Grid', icon: Gauge },
    { key: 'hud', label: 'Command HUD', icon: Sliders },
    { key: 'network', label: 'Field Network', icon: Wifi },
    { key: 'system', label: 'Backup & Reset', icon: Shield },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
          />

          {/* Slide-over Drawer — Tactical Command Dark Theme */}
          <motion.aside
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            style={{
              background: 'linear-gradient(180deg, #182235 0%, #111827 100%)',
              borderColor: 'rgba(255, 255, 255, 0.10)',
            }}
            className="fixed right-0 top-0 h-screen w-full sm:w-[480px] lg:w-[520px] text-slate-100 z-50 border-l flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="p-4 sm:p-5 border-b border-white/10 bg-black/30 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#B5482E]/25 border border-[#B5482E]/50 flex items-center justify-center text-[#F97316]">
                  <Settings className="w-4 h-4 animate-spin-slow" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2
                      className="text-sm font-bold tracking-wide text-white uppercase"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      Platform Settings
                    </h2>
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                      SYNC ACTIVE
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    Tactical HUD Calibration • SIH26069
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="hidden sm:inline-block text-[10px] font-mono text-slate-400 bg-white/[0.06] px-2 py-0.5 rounded border border-white/10">
                  ESC
                </span>
                <button
                  onClick={onClose}
                  className="w-8 h-8 rounded-lg bg-white/[0.06] border border-white/10 flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
                  aria-label="Close settings drawer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Navigation Tabs Bar */}
            <div className="flex items-center gap-1 px-3 py-2 border-b border-white/10 bg-black/20 overflow-x-auto no-scrollbar shrink-0">
              {tabs.map((t) => {
                const Icon = t.icon;
                const isActive = activeTab === t.key;
                return (
                  <button
                    key={t.key}
                    onClick={() => setActiveTab(t.key)}
                    className={cn(
                      'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
                      isActive
                        ? 'bg-white/[0.12] text-white font-semibold border border-white/15 shadow-sm'
                        : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{t.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Toast Notification */}
            <AnimatePresence>
              {toastMsg && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="bg-emerald-500/20 text-emerald-300 border-b border-emerald-500/30 px-4 py-2 text-xs font-mono flex items-center gap-2"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>{toastMsg}</span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Drawer Body Scroll Area */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-5 custom-scrollbar">
              {/* TAB 1: TACTICAL MAP */}
              {activeTab === 'map' && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2 flex items-center gap-2">
                      <Globe className="w-4 h-4 text-[#F97316]" />
                      Default Map Projection
                    </h3>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'globe', label: '3D Spherical Globe', desc: 'True curvature & subcontinental orbit', icon: Globe },
                        { id: 'mercator', label: '2D Tactical Flat Map', desc: 'Standard planar projection grid', icon: MapIcon },
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
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-[0_0_12px_rgba(181,72,46,0.25)]'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white hover:bg-white/[0.08]'
                            )}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <Icon className={cn('w-4 h-4', isSelected ? 'text-[#F97316]' : 'text-slate-400')} />
                              {isSelected && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                            </div>
                            <p className="text-xs font-semibold text-white">{proj.label}</p>
                            <p className="text-[10px] text-slate-400 leading-tight mt-0.5">{proj.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-[#F97316]" />
                      Default Basemap Style
                    </h3>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'satellite', label: 'Satellite Imagery', badge: 'ESRI HIGH-RES' },
                        { id: 'dark', label: 'Dark Tactical HUD', badge: 'CARTO DARK' },
                        { id: 'topo', label: 'Topographic Contours', badge: 'TERRAIN HYBRID' },
                        { id: 'street', label: 'Clean Street Vector', badge: 'OPENSTREETMAP' },
                      ].map((base) => {
                        const isSelected = settings.defaultBasemap === base.id;
                        return (
                          <button
                            key={base.id}
                            onClick={() => updateSettings({ defaultBasemap: base.id as BasemapPreset })}
                            className={cn(
                              'p-2.5 rounded-xl border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-[0_0_12px_rgba(181,72,46,0.25)]'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white hover:bg-white/[0.08]'
                            )}
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium text-white">{base.label}</span>
                              {isSelected && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                            </div>
                            <span className="text-[9px] font-mono text-slate-400 mt-1 block">{base.badge}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* The four overlay toggles that sat here (Doppler radar, cyclone
                      vectors, river basins, NDRF GPS) drew nothing and had no feed. */}
                  <div className="p-3 rounded-xl bg-white/[0.04] border border-white/10">
                    <p className="text-xs font-semibold text-white">Map layers</p>
                    <p className="text-[10px] text-slate-400 leading-tight mt-0.5">
                      INDRA events, SACHET warnings and unfused citizen reports. Toggle them on the map.
                    </p>
                  </div>

                  {/* Globe Auto-Rotation */}
                  <div className="p-3 rounded-xl bg-white/[0.04] border border-white/10 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-white">Globe Ambient Orbit</p>
                      <p className="text-[10px] text-slate-400">Slow auto-rotation when tactical map is idle</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ globeAutoRotate: !settings.globeAutoRotate })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.globeAutoRotate ? 'bg-[#B5482E]' : 'bg-slate-700'
                      )}
                    >
                      <span
                        className={cn(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition',
                          settings.globeAutoRotate ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 2: ALERTS & SIREN AUDIO */}
              {activeTab === 'alerts' && (
                <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-gradient-to-br from-[#B5482E]/15 to-white/[0.02] border border-[#B5482E]/30">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2.5">
                        <Volume2 className="w-5 h-5 text-[#F97316]" />
                        <div>
                          <h4 className="text-xs font-bold text-white uppercase font-mono">
                            Emergency Siren Audio
                          </h4>
                          <p className="text-[10px] text-slate-400">
                            Synthesized tone for critical flash flood &amp; cyclone events
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })}
                        className={cn(
                          'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                          settings.audioAlertsEnabled ? 'bg-[#B5482E]' : 'bg-slate-700'
                        )}
                      >
                        <span
                          className={cn(
                            'inline-block h-4 w-4 transform rounded-full bg-white transition',
                            settings.audioAlertsEnabled ? 'translate-x-4' : 'translate-x-0'
                          )}
                        />
                      </button>
                    </div>

                    {/* Volume Slider */}
                    <div className="space-y-1.5 mt-2">
                      <div className="flex items-center justify-between text-[11px] font-mono text-slate-300">
                        <span>Audio Siren Volume</span>
                        <span className="font-bold text-[#F97316]">{Math.round(settings.alertVolume * 100)}%</span>
                      </div>
                      <input
                        type="range"
                        min="0.1"
                        max="1.0"
                        step="0.05"
                        disabled={!settings.audioAlertsEnabled}
                        value={settings.alertVolume}
                        onChange={(e) => updateSettings({ alertVolume: parseFloat(e.target.value) })}
                        className="w-full accent-[#E05D38] h-1.5 bg-slate-800 rounded-lg cursor-pointer disabled:opacity-40"
                      />
                    </div>

                    {/* Test Audio Button */}
                    <div className="mt-4 flex items-center justify-between pt-3 border-t border-white/10">
                      <span className="text-[11px] text-slate-400 font-mono">Synthesizer Test</span>
                      <button
                        onClick={() => handleTestAudio()}
                        disabled={!settings.audioAlertsEnabled || isPlayingAudio}
                        className={cn(
                          'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all',
                          isPlayingAudio
                            ? 'bg-[#B5482E] text-white animate-pulse'
                            : 'bg-[#B5482E]/20 hover:bg-[#B5482E]/35 text-white border border-[#B5482E]/50'
                        )}
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                        {isPlayingAudio ? 'Sounding Siren...' : 'Test Siren Audio'}
                      </button>
                    </div>
                  </div>

                  {/* Siren Sound Pattern */}
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2">
                      Siren Pattern Style
                    </h3>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'warble_fast', label: 'Tactical Warble', desc: 'Rapid 8Hz emergency sweep' },
                        { id: 'siren_continuous', label: 'Continuous Siren', desc: 'Civil defense dual-pitch' },
                        { id: 'pulsed_beacon', label: 'Pulsed Beacon', desc: '3-stage military audio beep' },
                        { id: 'chime_two_tone', label: 'Operational Chime', desc: 'Gentle notification ping' },
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
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-[0_0_12px_rgba(181,72,46,0.25)]'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white hover:bg-white/[0.08]'
                            )}
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium text-white">{pat.label}</span>
                              {isSelected && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                            </div>
                            <span className="text-[10px] text-slate-400 mt-0.5 block">{pat.desc}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Severity Threshold */}
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2">
                      Audio Notification Threshold
                    </h3>
                    <div className="grid grid-cols-2 gap-1.5">
                      {[
                        { id: 'ALL', label: 'All Incidents', desc: 'Low, Moderate & Critical' },
                        { id: 'MODERATE_PLUS', label: 'Moderate & Above', desc: 'Exclude minor warnings' },
                        { id: 'HIGH_PLUS', label: 'High & Critical', desc: 'Severe hazard bulletins' },
                        { id: 'CRITICAL_ONLY', label: 'Critical Only', desc: 'Immediate flash floods/cyclones' },
                      ].map((sev) => {
                        const isSelected = settings.minSeverityThreshold === sev.id;
                        return (
                          <button
                            key={sev.id}
                            onClick={() => updateSettings({ minSeverityThreshold: sev.id as any })}
                            className={cn(
                              'p-2 rounded-xl border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white hover:bg-white/[0.08]'
                            )}
                          >
                            <p className="text-xs font-medium text-white">{sev.label}</p>
                            <p className="text-[9px] text-slate-400">{sev.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Auto-Refresh Rate */}
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2">
                      Telemetry Polling Interval
                    </h3>
                    <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                      {[
                        { id: 5, label: '5s Live' },
                        { id: 15, label: '15s Normal' },
                        { id: 30, label: '30s Relaxed' },
                        { id: 0, label: 'Manual' },
                      ].map((rate) => {
                        const isSelected = settings.autoRefreshInterval === rate.id;
                        return (
                          <button
                            key={rate.id}
                            onClick={() => updateSettings({ autoRefreshInterval: rate.id as RefreshInterval })}
                            className={cn(
                              'py-2 px-1 text-center rounded-lg border transition-all',
                              isSelected
                                ? 'bg-[#B5482E] text-white border-[#B5482E] font-bold shadow-sm'
                                : 'bg-white/[0.04] border-white/10 text-slate-400 hover:text-white hover:bg-white/[0.08]'
                            )}
                          >
                            {rate.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: UNITS & GRID */}
              {activeTab === 'units' && (
                <div className="space-y-4">
                  {/* Live Conversion Preview Card */}
                  <div className="p-3.5 rounded-xl bg-white/[0.05] border border-white/10">
                    <p className="text-[10px] font-mono uppercase text-[#F97316] font-bold mb-2">
                      Live Telemetry Output Sample
                    </p>
                    <div className="grid grid-cols-3 gap-2 font-mono text-center">
                      <div className="bg-black/30 p-2 rounded-lg border border-white/10">
                        <span className="text-[9px] text-slate-400 block">Temperature</span>
                        <span className="text-sm font-bold text-amber-400">
                          {formatTemperature(32.4, settings.tempUnit)}
                        </span>
                      </div>
                      <div className="bg-black/30 p-2 rounded-lg border border-white/10">
                        <span className="text-[9px] text-slate-400 block">Wind Velocity</span>
                        <span className="text-sm font-bold text-sky-400">
                          {formatWindSpeed(68, settings.windUnit)}
                        </span>
                      </div>
                      <div className="bg-black/30 p-2 rounded-lg border border-white/10">
                        <span className="text-[9px] text-slate-400 block">Precipitation</span>
                        <span className="text-sm font-bold text-blue-400">
                          {formatRainfall(85.5, settings.rainUnit)}
                        </span>
                      </div>
                    </div>
                    <div className="mt-2 text-center text-[10px] font-mono text-slate-400">
                      Coordinates: <span className="text-emerald-400 font-semibold">{formatCoordinates(25.5941, 85.1376, settings.coordFormat)}</span>
                    </div>
                  </div>

                  {/* Temperature Unit */}
                  <div>
                    <h4 className="text-xs font-mono font-bold text-slate-400 uppercase mb-2">
                      Temperature Unit
                    </h4>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'celsius', label: 'Celsius (°C)', desc: 'Standard IMD meteorological unit' },
                        { id: 'fahrenheit', label: 'Fahrenheit (°F)', desc: 'Imperial scale' },
                      ].map((u) => {
                        const isSelected = settings.tempUnit === u.id;
                        return (
                          <button
                            key={u.id}
                            onClick={() => updateSettings({ tempUnit: u.id as TempUnit })}
                            className={cn(
                              'p-2.5 rounded-xl border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-sm'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs font-semibold text-white">{u.label}</p>
                            <p className="text-[10px] text-slate-400">{u.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Wind Velocity */}
                  <div>
                    <h4 className="text-xs font-mono font-bold text-slate-400 uppercase mb-2">
                      Wind Speed Unit
                    </h4>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { id: 'kmh', label: 'km/h', desc: 'Civil / Highway' },
                        { id: 'knots', label: 'Knots (kt)', desc: 'Maritime / Coast Guard' },
                        { id: 'ms', label: 'm/s', desc: 'Scientific SI' },
                      ].map((u) => {
                        const isSelected = settings.windUnit === u.id;
                        return (
                          <button
                            key={u.id}
                            onClick={() => updateSettings({ windUnit: u.id as WindUnit })}
                            className={cn(
                              'p-2 rounded-xl border text-center transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/25 border-[#B5482E] text-white font-semibold'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs font-mono">{u.label}</p>
                            <p className="text-[9px] text-slate-500">{u.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Coordinates Format */}
                  <div>
                    <h4 className="text-xs font-mono font-bold text-slate-400 uppercase mb-2">
                      Geographic Coordinate System
                    </h4>
                    <div className="space-y-1.5">
                      {[
                        { id: 'dd', label: 'Decimal Degrees', sample: '25.5941° N, 85.1376° E' },
                        { id: 'dms', label: 'Degrees Minutes Seconds (DMS)', sample: '25°35\'38"N, 85°08\'15"E' },
                        { id: 'mgrs', label: 'Military Grid Reference (MGRS)', sample: '45R 25594 85137' },
                      ].map((cf) => {
                        const isSelected = settings.coordFormat === cf.id;
                        return (
                          <button
                            key={cf.id}
                            onClick={() => updateSettings({ coordFormat: cf.id as CoordFormat })}
                            className={cn(
                              'w-full p-2.5 rounded-xl border text-left flex items-center justify-between transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-sm'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <div>
                              <p className="text-xs font-medium text-white">{cf.label}</p>
                              <p className="text-[10px] font-mono text-slate-400">{cf.sample}</p>
                            </div>
                            {isSelected && <Check className="w-4 h-4 text-[#F97316]" />}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Timezone */}
                  <div>
                    <h4 className="text-xs font-mono font-bold text-slate-400 uppercase mb-2">
                      Operational Timezone
                    </h4>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'ist', label: 'Indian Standard (IST)', desc: 'UTC +05:30 (New Delhi)' },
                        { id: 'utc', label: 'UTC Zulu Time', desc: 'UTC +00:00 (Aviation/Global)' },
                      ].map((tz) => {
                        const isSelected = settings.timezone === tz.id;
                        return (
                          <button
                            key={tz.id}
                            onClick={() => updateSettings({ timezone: tz.id as TimezoneMode })}
                            className={cn(
                              'p-2.5 rounded-xl border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs font-semibold text-white">{tz.label}</p>
                            <p className="text-[10px] text-slate-400">{tz.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: COMMAND HUD */}
              {activeTab === 'hud' && (
                <div className="space-y-4">
                  {/* Interface Language */}
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2 flex items-center gap-1.5">
                      <Globe className="w-3 h-3 text-[#F97316]" />
                      Interface Language / भाषा
                    </h3>
                    <div className="grid grid-cols-3 gap-1.5 max-h-44 overflow-y-auto pr-1 custom-scrollbar">
                      {Object.entries(SUPPORTED_LANGUAGES).map(([code, meta]) => {
                        const isSelected = currentLang === code;
                        return (
                          <button
                            key={code}
                            onClick={() => changeLang(code as any)}
                            className={cn(
                              'p-2 rounded-lg border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/25 border-[#B5482E] text-white font-semibold'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs truncate" style={{ fontFamily: meta.fontFamily }}>{meta.nativeName}</p>
                            <p className="text-[9px] text-slate-400 truncate">{meta.name}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2">
                      HUD Interface Mode
                    </h3>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { id: 'dark', label: 'Dark Tactical', desc: 'Ops Command' },
                        { id: 'light', label: 'Clean Light', desc: 'High Ambient' },
                        { id: 'high_contrast', label: 'High Contrast', desc: 'Field Glare HUD' },
                      ].map((m) => {
                        const isSelected = settings.themeMode === m.id;
                        return (
                          <button
                            key={m.id}
                            onClick={() => updateSettings({ themeMode: m.id as ThemeMode })}
                            className={cn(
                              'p-2.5 rounded-xl border text-center transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/25 border-[#B5482E] text-white font-semibold'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs font-semibold">{m.label}</p>
                            <p className="text-[9px] text-slate-400 mt-0.5">{m.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* UI Density */}
                  <div>
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400 mb-2">
                      Display Density
                    </h3>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { id: 'standard', label: 'Standard Spacious', desc: 'Comfortable touch and desktop spacing' },
                        { id: 'compact', label: 'Tactical Compact', desc: 'High-density telemetry metrics per screen' },
                      ].map((d) => {
                        const isSelected = settings.uiDensity === d.id;
                        return (
                          <button
                            key={d.id}
                            onClick={() => updateSettings({ uiDensity: d.id as any })}
                            className={cn(
                              'p-2.5 rounded-xl border text-left transition-all',
                              isSelected
                                ? 'bg-[#B5482E]/20 border-[#B5482E] text-white shadow-sm'
                                : 'bg-white/[0.04] border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
                            )}
                          >
                            <p className="text-xs font-semibold text-white">{d.label}</p>
                            <p className="text-[10px] text-slate-400">{d.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Visual Effects */}
                  <div className="space-y-2">
                    <h3 className="text-xs font-bold font-mono tracking-wider uppercase text-slate-400">
                      Performance &amp; Visual Effects
                    </h3>
                    <div className="bg-white/[0.04] border border-white/10 rounded-xl divide-y divide-white/10">
                      <div className="p-3 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-semibold text-white">Glassmorphism &amp; Glow Filters</p>
                          <p className="text-[10px] text-slate-400">Translucent cards and backdrop blurs</p>
                        </div>
                        <button
                          onClick={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })}
                          className={cn(
                            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                            settings.glassmorphismEffects ? 'bg-[#B5482E]' : 'bg-slate-700'
                          )}
                        >
                          <span
                            className={cn(
                              'inline-block h-4 w-4 transform rounded-full bg-white transition',
                              settings.glassmorphismEffects ? 'translate-x-4' : 'translate-x-0'
                            )}
                          />
                        </button>
                      </div>

                      <div className="p-3 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-semibold text-white">Reduced Motion Mode</p>
                          <p className="text-[10px] text-slate-400">Disable heavy spring transitions on low-spec devices</p>
                        </div>
                        <button
                          onClick={() => updateSettings({ reducedMotion: !settings.reducedMotion })}
                          className={cn(
                            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                            settings.reducedMotion ? 'bg-[#B5482E]' : 'bg-slate-700'
                          )}
                        >
                          <span
                            className={cn(
                              'inline-block h-4 w-4 transform rounded-full bg-white transition',
                              settings.reducedMotion ? 'translate-x-4' : 'translate-x-0'
                            )}
                          />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 5: FIELD NETWORK & DATA SAVER */}
              {activeTab === 'network' && (
                <div className="space-y-4">
                  {/* A "satellite data saver", a "~6.4 MB" tile-cache meter with a
                      purge button, and a live-vs-simulated source switch used to sit
                      here. None of them was read by anything. */}
                  <div className="p-3 rounded-xl bg-white/[0.04] border border-white/10">
                    <p className="text-xs font-semibold text-white">Data source</p>
                    <p className="text-[10px] text-slate-400 leading-tight mt-0.5">
                      Every panel reads the live INDRA API and WebSocket. There is no simulated mode.
                    </p>
                  </div>
                </div>
              )}

              {/* TAB 6: BACKUP & SYSTEM */}
              {activeTab === 'system' && (
                <div className="space-y-4">
                  {/* Export / Import JSON */}
                  <div className="p-4 rounded-xl bg-white/[0.04] border border-white/10 space-y-3">
                    <h4 className="text-xs font-bold text-white uppercase font-mono">
                      Operator Preferences Backup
                    </h4>
                    <p className="text-xs text-slate-400">
                      Export your configured GIS presets, alert thresholds, and units into a JSON configuration file.
                    </p>
                    <div className="flex items-center gap-2 pt-1">
                      <button
                        onClick={handleExportJson}
                        className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#B5482E] hover:bg-[#A03D25] text-white text-xs font-semibold font-mono transition-all shadow-sm"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Export Config (JSON)
                      </button>

                      <label className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-white/[0.08] hover:bg-white/[0.12] border border-white/15 text-slate-200 text-xs font-semibold font-mono cursor-pointer transition-all shadow-sm">
                        <Upload className="w-3.5 h-3.5" />
                        Import Config
                        <input
                          type="file"
                          accept=".json"
                          onChange={handleImportJson}
                          className="hidden"
                        />
                      </label>
                    </div>
                  </div>

                  {/* Reset to Factory Defaults */}
                  <div className="p-4 rounded-xl bg-[#8C2F26]/15 border border-[#8C2F26]/30 space-y-2">
                    <div className="flex items-center gap-2 text-rose-400 text-xs font-bold font-mono">
                      <AlertTriangle className="w-4 h-4" />
                      FACTORY DEFAULTS RESET
                    </div>
                    <p className="text-xs text-slate-400">
                      Reverts all GIS basemaps, audio alarms, measurement units, and telemetry rates to the initial INDRA specification.
                    </p>
                    <button
                      onClick={() => {
                        resetSettings();
                        showToast('All settings reset to factory defaults');
                      }}
                      className="mt-2 flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#8C2F26]/30 hover:bg-[#8C2F26]/60 text-rose-200 border border-[#8C2F26]/50 text-xs font-mono font-semibold transition-colors shadow-sm"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      Reset to Defaults
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Footer Quick Action */}
            <div className="p-3 border-t border-white/10 bg-black/30 flex items-center justify-between text-xs shrink-0">
              <span className="text-[11px] text-slate-400 font-mono">
                Auto-saved to local memory
              </span>
              <Link
                href="/settings"
                onClick={onClose}
                className="flex items-center gap-1.5 text-[#F97316] hover:text-[#FFA07A] font-medium transition-colors"
              >
                <span>Open Full Page Settings</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </Link>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
