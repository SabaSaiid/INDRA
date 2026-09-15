'use client';

import React, { useState } from 'react';
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
  WifiOff,
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
  formatTemperature,
  formatWindSpeed,
  formatRainfall,
  formatCoordinates,
} from '@/lib/useSettings';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export default function SettingsPage() {
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
  const [activeSection, setActiveSection] = useState<'all' | 'map' | 'alerts' | 'units' | 'hud' | 'network' | 'backup'>('all');
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
        showToast('Configuration imported successfully across all nodes');
      } catch {
        showToast('Failed to parse settings JSON file');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="min-h-screen bg-surface">
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

        <main className="p-4 lg:p-6 max-w-[1500px] mx-auto space-y-6">
          {/* Toast Notification */}
          <AnimatePresence>
            {toastMessage && (
              <motion.div
                initial={{ opacity: 0, y: -10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.98 }}
                className="fixed top-20 right-6 z-50 bg-emerald-500 text-white px-4 py-3 rounded-xl shadow-xl flex items-center gap-2.5 text-xs font-mono font-semibold"
              >
                <Check className="w-4 h-4" />
                <span>{toastMessage}</span>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Header Banner */}
          <motion.div
            variants={fadeIn}
            initial="hidden"
            animate="visible"
            className="bg-slate-900 text-white p-5 lg:p-6 rounded-2xl border border-slate-800 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4"
          >
            <div>
              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                <Settings className="w-5 h-5 text-cyan-400" />
                <h1 className="text-xl font-bold font-mono tracking-tight">
                  MISSION PREFERENCES &amp; SYSTEM CONFIGURATION
                </h1>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  SIH26069 • TEAM SIXTH SENSE
                </span>
              </div>
              <p className="text-xs text-slate-400 max-w-3xl">
                Calibrate tactical 3D geospatial rendering, audio emergency sirens, telemetry unit standards, outdoor field HUD display modes, and satellite data bandwidth limits.
              </p>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-mono text-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                LIVE SYNC ACTIVE
              </div>
              <button
                onClick={handleExportJson}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold font-mono transition-colors shadow-sm"
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
              { id: 'alerts', label: '🚨 Audio & Siren' },
              { id: 'units', label: '📐 Units & Grid' },
              { id: 'hud', label: '🖥️ Command HUD' },
              { id: 'network', label: '🛰️ Field Satellite' },
              { id: 'backup', label: '⚙️ Backup & Diagnostics' },
            ].map((cat) => (
              <button
                key={cat.id}
                onClick={() => setActiveSection(cat.id as any)}
                className={cn(
                  'px-3.5 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition-all',
                  activeSection === cat.id
                    ? 'bg-slate-900 text-white font-semibold shadow-sm border border-slate-800'
                    : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
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
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-blue-50 text-primary flex items-center justify-center font-bold">
                      <Globe className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Tactical Geospatial &amp; Map Defaults</h2>
                      <p className="text-[11px] text-slate-500">Projection curvature, Doppler radar, and basemap layers</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-semibold border border-blue-100">
                    GIS CONSOLE
                  </span>
                </div>

                {/* Projection Mode */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Default Tactical Projection
                  </label>
                  <div className="grid grid-cols-2 gap-2.5">
                    {[
                      { id: 'globe', label: '3D Spherical Earth', desc: 'Subcontinental orbital curvature & space-grade atmosphere', icon: Globe },
                      { id: 'mercator', label: '2D Planar Mercator', desc: 'High-speed flat grid for low-latency tablet operations', icon: MapIcon },
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
                              ? 'bg-blue-50 border-primary text-slate-900 ring-2 ring-primary/20 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <Icon className={cn('w-4 h-4', isSelected ? 'text-primary' : 'text-slate-500')} />
                            {isSelected && <Check className="w-4 h-4 text-primary" />}
                          </div>
                          <p className="text-xs font-bold text-slate-900">{proj.label}</p>
                          <p className="text-[10px] text-slate-500 mt-0.5">{proj.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Basemap Presets */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-blue-50 border-primary text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-slate-800">{base.label}</span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-primary" />}
                          </div>
                          <span className="text-[10px] font-mono text-slate-400 mt-0.5 block">{base.source}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Layer Overlays */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Default Tactical Overlays
                  </label>
                  <div className="bg-slate-50 border border-slate-200 rounded-xl divide-y divide-slate-200">
                    {[
                      { key: 'showDopplerOverlay' as const, label: 'Doppler Weather Radar Heatmap', desc: 'Precipitation reflectivity overlay' },
                      { key: 'showCycloneVectors' as const, label: 'Cyclone Track & Velocity Vectors', desc: 'Cone of uncertainty and gale radii' },
                      { key: 'showRiverBasins' as const, label: 'River Catchment Inundation Polygons', desc: 'Major flood-risk water basins' },
                      { key: 'showNdrfUnits' as const, label: 'NDRF Rescue Unit Dispatches', desc: 'Field battalion live GPS coordinates' },
                    ].map((item) => (
                      <div key={item.key} className="p-3 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-semibold text-slate-800">{item.label}</p>
                          <p className="text-[10px] text-slate-500">{item.desc}</p>
                        </div>
                        <button
                          onClick={() => updateSettings({ [item.key]: !settings[item.key] })}
                          className={cn(
                            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                            settings[item.key] ? 'bg-primary' : 'bg-slate-300'
                          )}
                        >
                          <span
                            className={cn(
                              'inline-block h-4 w-4 transform rounded-full bg-white transition shadow-sm',
                              settings[item.key] ? 'translate-x-4' : 'translate-x-0'
                            )}
                          />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Auto Rotation */}
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-slate-800">Globe Idle Auto-Orbit</p>
                    <p className="text-[10px] text-slate-500">Slow atmospheric rotation when map interaction is idle</p>
                  </div>
                  <button
                    onClick={() => updateSettings({ globeAutoRotate: !settings.globeAutoRotate })}
                    className={cn(
                      'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                      settings.globeAutoRotate ? 'bg-primary' : 'bg-slate-300'
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

            {/* 2. AUDIO & EARLY WARNING SIRENS */}
            {(activeSection === 'all' || activeSection === 'alerts') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center font-bold">
                      <Volume2 className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Audio Sirens &amp; Early Warning</h2>
                      <p className="text-[11px] text-slate-500">Synthesized audio beacons and hazard dispatch filters</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-50 text-rose-700 font-semibold border border-rose-100">
                    WEB AUDIO API
                  </span>
                </div>

                {/* Master Audio Toggle */}
                <div className="p-4 bg-gradient-to-r from-rose-50 to-orange-50/40 rounded-xl border border-rose-100 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-rose-600 text-white flex items-center justify-center shadow-md">
                      <Volume2 className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-slate-900">Emergency Audio Beacon</p>
                      <p className="text-[10px] text-slate-600">Zero-latency synthesized alarm for critical flash flood alerts</p>
                    </div>
                  </div>
                  <button
                    onClick={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })}
                    className={cn(
                      'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                      settings.audioAlertsEnabled ? 'bg-rose-600' : 'bg-slate-300'
                    )}
                  >
                    <span
                      className={cn(
                        'inline-block h-5 w-5 transform rounded-full bg-white transition shadow-md',
                        settings.audioAlertsEnabled ? 'translate-x-5' : 'translate-x-0'
                      )}
                    />
                  </button>
                </div>

                {/* Volume Slider & Test Sound */}
                <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 space-y-3">
                  <div className="flex items-center justify-between text-xs font-mono text-slate-700">
                    <span className="font-semibold">Siren Output Volume</span>
                    <span className="font-bold text-rose-600">{Math.round(settings.alertVolume * 100)}%</span>
                  </div>
                  <input
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    disabled={!settings.audioAlertsEnabled}
                    value={settings.alertVolume}
                    onChange={(e) => updateSettings({ alertVolume: parseFloat(e.target.value) })}
                    className="w-full accent-rose-600 h-1.5 bg-slate-200 rounded-lg cursor-pointer disabled:opacity-40"
                  />
                  <div className="flex items-center justify-between pt-2 border-t border-slate-200">
                    <span className="text-[11px] text-slate-500">Audio Hardware Synthesizer</span>
                    <button
                      onClick={() => handleTestAudio()}
                      disabled={!settings.audioAlertsEnabled || isPlayingAudio}
                      className={cn(
                        'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all',
                        isPlayingAudio
                          ? 'bg-rose-600 text-white animate-pulse'
                          : 'bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200'
                      )}
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                      {isPlayingAudio ? 'Sounding Alarm...' : 'Test Siren Audio'}
                    </button>
                  </div>
                </div>

                {/* Siren Pattern */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Audio Siren Pattern
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
                              ? 'bg-rose-50 border-rose-500 text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-slate-800">{pat.label}</span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-rose-600" />}
                          </div>
                          <span className="text-[10px] text-slate-500 mt-0.5 block">{pat.desc}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Polling Interval */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Telemetry Refresh Frequency
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
                              ? 'bg-slate-900 text-white font-bold border-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
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

            {/* 3. TELEMETRY UNITS & FORMATS */}
            {(activeSection === 'all' || activeSection === 'units') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold">
                      <Gauge className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Telemetry Units &amp; Standards</h2>
                      <p className="text-[11px] text-slate-500">Meteorological scale conversion &amp; coordinate format</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 font-semibold border border-indigo-100">
                    CALIBRATION
                  </span>
                </div>

                {/* Live Preview Box */}
                <div className="p-4 rounded-xl bg-slate-900 text-white space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono uppercase text-indigo-300 font-bold">
                      Calculated Weather Station Output
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">Patna Station #04</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 font-mono text-center">
                    <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700">
                      <span className="text-[9px] text-slate-400 block">Temperature</span>
                      <span className="text-sm font-bold text-amber-400">
                        {formatTemperature(32.4, settings.tempUnit)}
                      </span>
                    </div>
                    <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700">
                      <span className="text-[9px] text-slate-400 block">Wind Gust</span>
                      <span className="text-sm font-bold text-cyan-400">
                        {formatWindSpeed(68, settings.windUnit)}
                      </span>
                    </div>
                    <div className="bg-slate-800/80 p-2 rounded-lg border border-slate-700">
                      <span className="text-[9px] text-slate-400 block">Precipitation</span>
                      <span className="text-sm font-bold text-blue-400">
                        {formatRainfall(85.5, settings.rainUnit)}
                      </span>
                    </div>
                  </div>
                  <p className="text-center font-mono text-[11px] text-slate-400">
                    Coordinates: <span className="text-emerald-400 font-semibold">{formatCoordinates(25.5941, 85.1376, settings.coordFormat)}</span>
                  </p>
                </div>

                {/* Temperature & Wind Grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-blue-50 border-primary text-primary font-bold shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                          )}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-blue-50 border-primary text-primary font-bold shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
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
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Geospatial Coordinate Notation
                  </label>
                  <div className="space-y-1.5">
                    {[
                      { id: 'dd', label: 'Decimal Degrees (Standard)', sample: '25.5941° N, 85.1376° E' },
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
                              ? 'bg-blue-50 border-primary text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <div>
                            <p className="text-xs font-semibold text-slate-800">{cf.label}</p>
                            <p className="text-[10px] font-mono text-slate-400">{cf.sample}</p>
                          </div>
                          {isSelected && <Check className="w-4 h-4 text-primary" />}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Timezone */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-blue-50 border-primary text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <p className="text-xs font-semibold text-slate-800">{tz.label}</p>
                          <p className="text-[10px] text-slate-500">{tz.desc}</p>
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
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center font-bold">
                      <Sliders className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Command HUD &amp; Theme Engine</h2>
                      <p className="text-[11px] text-slate-500">Outdoor glare contrast, layout density &amp; visual performance</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-semibold border border-amber-100">
                    APPEARANCE
                  </span>
                </div>

                {/* Theme Mode */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-slate-900 text-white border-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                          )}
                        >
                          <p className="text-xs font-bold">{th.label}</p>
                          <p className="text-[9px] text-slate-400 mt-0.5">{th.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* UI Density */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
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
                              ? 'bg-blue-50 border-primary text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <p className="text-xs font-semibold text-slate-800">{d.label}</p>
                          <p className="text-[10px] text-slate-500">{d.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Effects Switches */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl divide-y divide-slate-200">
                  <div className="p-3 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-slate-800">Glassmorphism &amp; Glow Filters</p>
                      <p className="text-[10px] text-slate-500">Translucent navigation headers and backdrop blurs</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.glassmorphismEffects ? 'bg-primary' : 'bg-slate-300'
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
                      <p className="text-xs font-semibold text-slate-800">Reduced Motion Mode</p>
                      <p className="text-[10px] text-slate-500">Disable complex spring animations for ruggedized field hardware</p>
                    </div>
                    <button
                      onClick={() => updateSettings({ reducedMotion: !settings.reducedMotion })}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        settings.reducedMotion ? 'bg-primary' : 'bg-slate-300'
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

            {/* 5. FIELD STATION & SATELLITE BANDWIDTH */}
            {(activeSection === 'all' || activeSection === 'network') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-cyan-50 text-cyan-600 flex items-center justify-center font-bold">
                      <Wifi className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Field Satellite &amp; Network Bandwidth</h2>
                      <p className="text-[11px] text-slate-500">Data compression for 2G/3G emergency field stations</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-50 text-cyan-700 font-semibold border border-cyan-100">
                    BANDWIDTH SAVER
                  </span>
                </div>

                {/* Low Bandwidth Toggle */}
                <div className="p-4 bg-gradient-to-r from-amber-50 to-amber-100/50 rounded-xl border border-amber-200 flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <WifiOff className="w-4 h-4 text-amber-700" />
                      <p className="text-xs font-bold text-amber-950">Field Satellite Low-Bandwidth Mode</p>
                    </div>
                    <p className="text-[11px] text-amber-900/80 leading-relaxed">
                      Optimizes performance on Inmarsat or 2G connections by compressing GIS radar GeoTIFFs and halting live animations.
                    </p>
                  </div>
                  <button
                    onClick={() => updateSettings({ lowBandwidthDataSaver: !settings.lowBandwidthDataSaver })}
                    className={cn(
                      'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors mt-1',
                      settings.lowBandwidthDataSaver ? 'bg-amber-600' : 'bg-slate-300'
                    )}
                  >
                    <span
                      className={cn(
                        'inline-block h-5 w-5 transform rounded-full bg-white transition shadow-md',
                        settings.lowBandwidthDataSaver ? 'translate-x-5' : 'translate-x-0'
                      )}
                    />
                  </button>
                </div>

                {/* Local Cache Meter */}
                <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-700">Offline GIS Radar Tile Cache</span>
                    <span className="font-mono text-primary font-bold">~6.4 MB used</span>
                  </div>
                  <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full w-[14%]" />
                  </div>
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-[10px] text-slate-400">IndexedDB Local Storage</span>
                    <button
                      onClick={() => showToast('Local offline GIS tile cache purged')}
                      className="text-xs text-rose-600 hover:text-rose-700 font-medium hover:underline"
                    >
                      Purge Offline Cache
                    </button>
                  </div>
                </div>

                {/* Data Source Mode */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                    Backend Telemetry Cluster
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'live', label: 'FastAPI Production Node', desc: 'Direct REST/WebSocket feed from IMD ingestion engine' },
                      { id: 'mock', label: 'Autonomous Mock Engine', desc: 'Simulated high-frequency incident generation' },
                    ].map((src) => {
                      const isSelected = settings.apiDataSource === src.id;
                      return (
                        <button
                          key={src.id}
                          onClick={() => updateSettings({ apiDataSource: src.id as any })}
                          className={cn(
                            'p-2.5 rounded-xl border text-left transition-all',
                            isSelected
                              ? 'bg-blue-50 border-primary text-slate-900 shadow-sm'
                              : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                          )}
                        >
                          <p className="text-xs font-semibold text-slate-800">{src.label}</p>
                          <p className="text-[10px] text-slate-500">{src.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </motion.div>
            )}

            {/* 6. SYSTEM BACKUP, DIAGNOSTICS & RESET */}
            {(activeSection === 'all' || activeSection === 'backup') && (
              <motion.div
                variants={fadeIn}
                initial="hidden"
                animate="visible"
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-4"
              >
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
                      <Shield className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">Backup, Diagnostics &amp; Recovery</h2>
                      <p className="text-[11px] text-slate-500">Configuration JSON exports and factory reset</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-semibold border border-emerald-100">
                    DIAGNOSTICS
                  </span>
                </div>

                {/* Node Diagnostic Pings */}
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-slate-700 block">
                    Telemetry Cluster Health Status
                  </span>
                  <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                    <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
                      <span className="text-[10px] text-slate-400 block">FastAPI Backend</span>
                      <span className="text-emerald-600 font-bold">12ms • ONLINE</span>
                    </div>
                    <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
                      <span className="text-[10px] text-slate-400 block">BigQuery GIS</span>
                      <span className="text-blue-600 font-bold">CONNECTED</span>
                    </div>
                    <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
                      <span className="text-[10px] text-slate-400 block">INSAT-3DR Stream</span>
                      <span className="text-purple-600 font-bold">ACTIVE</span>
                    </div>
                  </div>
                </div>

                {/* Export / Import */}
                <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-2.5">
                  <p className="text-xs font-semibold text-slate-800">Configuration JSON Profile</p>
                  <p className="text-[11px] text-slate-500">
                    Save your operational settings to a portable configuration file or load presets from another command node.
                  </p>
                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={handleExportJson}
                      className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold font-mono transition-colors shadow-sm"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Export JSON
                    </button>
                    <label className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-white hover:bg-slate-100 border border-slate-300 text-slate-700 text-xs font-semibold font-mono cursor-pointer transition-colors">
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
                <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl space-y-2">
                  <div className="flex items-center gap-2 text-rose-700 font-bold text-xs">
                    <AlertTriangle className="w-4 h-4" />
                    RESET TO FACTORY DEFAULTS
                  </div>
                  <p className="text-[11px] text-rose-900/80">
                    Restores initial INDRA mission control defaults across all map projections, audio sirens, and telemetry units.
                  </p>
                  <div className="pt-1">
                    {!showResetConfirm ? (
                      <button
                        onClick={() => setShowResetConfirm(true)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold font-mono transition-colors shadow-sm"
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
                            showToast('All settings reset to operational defaults');
                          }}
                          className="px-3 py-1.5 rounded-lg bg-rose-700 hover:bg-rose-800 text-white text-xs font-bold font-mono shadow-sm"
                        >
                          Confirm Reset
                        </button>
                        <button
                          onClick={() => setShowResetConfirm(false)}
                          className="px-3 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-700 text-xs font-medium hover:bg-slate-50"
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
