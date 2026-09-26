'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import {
  X,
  Settings,
  Globe,
  Map as MapIcon,
  Volume2,
  VolumeX,
  Volume1,
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
  Search,
  Copy,
  Activity,
  Compass,
  Zap,
  Clock,
  Radio,
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

export type TabKey = 'general' | 'map' | 'alerts' | 'units' | 'hud' | 'notifications' | 'security' | 'network' | 'system';

interface TabItem {
  key: TabKey;
  label: string;
  shortLabel: string;
  icon: React.ComponentType<{ className?: string }>;
  hotkey: string;
}

const TAB_GROUPS: { groupLabel: string; tabs: TabItem[] }[] = [
  {
    groupLabel: 'Core',
    tabs: [
      { key: 'general', label: 'General Settings', shortLabel: 'General', icon: Sliders, hotkey: '1' },
    ],
  },
  {
    groupLabel: 'GIS & Environment',
    tabs: [
      { key: 'map', label: 'Map & GIS', shortLabel: 'Map', icon: Globe, hotkey: '2' },
      { key: 'alerts', label: 'Audio Alarms', shortLabel: 'Audio', icon: Volume2, hotkey: '3' },
      { key: 'units', label: 'Units & Metrics', shortLabel: 'Units', icon: Gauge, hotkey: '4' },
      { key: 'hud', label: 'HUD & Style', shortLabel: 'Style', icon: Layers, hotkey: '5' },
    ],
  },
  {
    groupLabel: 'Ops & Comms',
    tabs: [
      { key: 'notifications', label: 'Alert Delivery', shortLabel: 'Alerts', icon: Bell, hotkey: '6' },
      { key: 'security', label: 'Security & Access', shortLabel: 'Access', icon: Lock, hotkey: '7' },
      { key: 'network', label: 'Live Network', shortLabel: 'Net', icon: Wifi, hotkey: '8' },
    ],
  },
  {
    groupLabel: 'System',
    tabs: [
      { key: 'system', label: 'Backup & Reset', shortLabel: 'Backup', icon: Shield, hotkey: '9' },
    ],
  },
];

const ALL_TABS: TabKey[] = ['general', 'map', 'alerts', 'units', 'hud', 'notifications', 'security', 'network', 'system'];

interface SearchableSetting {
  id: string;
  tab: TabKey;
  label: string;
  desc: string;
  category: string;
  keywords: string[];
}

const SEARCHABLE_CATALOG: SearchableSetting[] = [
  { id: 'station-profile', tab: 'general', label: 'Station Identification & Node', desc: 'INDRA National Node-01 HQ New Delhi operational status', category: 'General', keywords: ['general', 'station', 'node', 'indra', 'hq', 'profile', 'delhi', 'operational'] },
  { id: 'general-lang', tab: 'general', label: 'Interface Language / भाषा', desc: 'Select from 11 Indian regional languages and English', category: 'General', keywords: ['language', 'hindi', 'bengali', 'tamil', 'marathi', 'telugu', 'gujarati', 'urdu', 'kannada', 'malayalam', 'i18n', 'translate'] },
  { id: 'general-theme', tab: 'general', label: 'Interface Theme', desc: 'Dark Tactical Ops, Light Parchment, High Contrast', category: 'General', keywords: ['theme', 'dark', 'light', 'high contrast', 'contrast', 'color'] },
  { id: 'general-refresh', tab: 'general', label: 'Telemetry Polling Rate', desc: '5s, 15s, 30s or manual refresh rate', category: 'General', keywords: ['refresh', 'rate', 'poll', 'interval', 'speed', 'seconds'] },
  { id: 'general-timezone', tab: 'general', label: 'Station Timezone Mode', desc: 'Indian Standard Time (IST UTC+5:30) vs UTC Zulu', category: 'General', keywords: ['timezone', 'ist', 'utc', 'zulu', 'time', 'clock', 'new delhi'] },
  { id: 'general-audio', tab: 'general', label: 'Master Emergency Siren', desc: 'Synthesizer warning tones for high-threat events', category: 'General', keywords: ['sound', 'audio', 'siren', 'alarm', 'tone'] },
  { id: 'projection', tab: 'map', label: 'Default Map Projection', desc: '3D Spherical Globe vs 2D Flat Mercator', category: 'GIS & Map', keywords: ['3d', 'globe', 'mercator', 'projection', '2d', 'map'] },
  { id: 'basemap', tab: 'map', label: 'Basemap Style', desc: 'Satellite, Dark Tactical, Topographic, Street Vector', category: 'GIS & Map', keywords: ['esri', 'satellite', 'dark', 'carto', 'topo', 'terrain', 'vector', 'street'] },
  { id: 'globe-orbit', tab: 'map', label: 'Globe Ambient Orbit', desc: 'Slow auto-rotation when idle', category: 'GIS & Map', keywords: ['rotate', 'spin', 'orbit', 'idle', 'ambient'] },
  { id: 'audio-enable', tab: 'alerts', label: 'Emergency Siren Synthesizer', desc: 'Synthesized warning tones for high-threat events', category: 'Audio & Alarms', keywords: ['sound', 'audio', 'siren', 'alarm', 'synthesizer', 'tone'] },
  { id: 'alert-volume', tab: 'alerts', label: 'Alert Volume & Decibel Level', desc: 'Volume level from quiet ops desk to 90dB maximum emergency warning', category: 'Audio & Alarms', keywords: ['volume', 'decibel', 'db', 'loud', 'quiet', 'sound'] },
  { id: 'siren-pattern', tab: 'alerts', label: 'Siren Pitch Pattern', desc: 'Tactical Warble, Continuous Siren, Pulsed Beacon, Operational Chime', category: 'Audio & Alarms', keywords: ['warble', 'continuous', 'beacon', 'chime', 'pitch', 'frequency'] },
  { id: 'alert-threshold', tab: 'alerts', label: 'Minimum Severity Threshold', desc: 'All Incidents, Moderate+, High+, Critical Only', category: 'Audio & Alarms', keywords: ['severity', 'threshold', 'critical', 'high', 'moderate', 'filter'] },
  { id: 'temp-unit', tab: 'units', label: 'Temperature Scale', desc: 'Celsius (°C - IMD standard) vs Fahrenheit (°F)', category: 'Units & Metrics', keywords: ['temp', 'celsius', 'fahrenheit', 'imd', 'degrees', 'weather'] },
  { id: 'wind-unit', tab: 'units', label: 'Wind Velocity Unit', desc: 'km/h (Civilian), Knots (Maritime), m/s (Scientific)', category: 'Units & Metrics', keywords: ['wind', 'speed', 'velocity', 'knots', 'kmh', 'ms', 'cyclone'] },
  { id: 'rain-unit', tab: 'units', label: 'Rainfall Measurement', desc: 'Millimeters (mm) vs Inches (in)', category: 'Units & Metrics', keywords: ['rain', 'rainfall', 'precipitation', 'mm', 'inches', 'monsoon'] },
  { id: 'coord-format', tab: 'units', label: 'Coordinate Reference Format', desc: 'Decimal Degrees (DD), Degrees Minutes Seconds (DMS), Military Grid (MGRS)', category: 'Units & Metrics', keywords: ['coord', 'coordinates', 'dd', 'dms', 'mgrs', 'military', 'grid', 'gps', 'lat', 'lon'] },
  { id: 'ui-density', tab: 'hud', label: 'Display Density', desc: 'Standard comfortable spacing vs Compact high-density data matrix', category: 'HUD & Style', keywords: ['density', 'compact', 'standard', 'spacing', 'padding'] },
  { id: 'glassmorphism', tab: 'hud', label: 'Glassmorphism & Backdrop Blur', desc: 'Translucent frosted glass cards and glow highlights', category: 'HUD & Style', keywords: ['glass', 'blur', 'glow', 'translucent', 'backdrop'] },
  { id: 'reduced-motion', tab: 'hud', label: 'Reduced Motion', desc: 'Disable heavy animations for low-spec field terminals', category: 'HUD & Style', keywords: ['motion', 'animation', 'performance', 'speed', 'gpu'] },
  { id: 'notify-inapp', tab: 'notifications', label: 'In-App Incident Banners', desc: 'Live HUD alerts and alert ticker on new hazards', category: 'Alert Delivery', keywords: ['notification', 'in-app', 'banner', 'ticker', 'popup'] },
  { id: 'notify-email', tab: 'notifications', label: 'Emergency Email Alerts', desc: 'Send disaster bulletins to operational email', category: 'Alert Delivery', keywords: ['email', 'mail', 'dispatch', 'bulletin'] },
  { id: 'notify-phone', tab: 'notifications', label: 'SMS & WhatsApp Broadcast', desc: 'Priority SMS gateway notification for field personnel', category: 'Alert Delivery', keywords: ['sms', 'whatsapp', 'phone', 'mobile', 'text'] },
  { id: 'idle-lock', tab: 'security', label: 'Inactivity Screen Lock', desc: 'Lock the tactical terminal after 5, 15, or 30 minutes of idle time', category: 'Security & Access', keywords: ['lock', 'idle', 'timeout', 'inactivity', 'screensaver', 'security'] },
  { id: 'mgrs-unlock', tab: 'security', label: 'Military Grid Reference (MGRS)', desc: 'Grant authorization to use NATO/MGRS coordinate targeting in HUD', category: 'Security & Access', keywords: ['mgrs', 'military', 'nato', 'security', 'grid', 'classification'] },
  { id: 'network-status', tab: 'network', label: 'Live Backend & WebSocket Telemetry', desc: 'Real-time WebSocket data stream status and node connectivity', category: 'Live Network', keywords: ['network', 'websocket', 'stream', 'api', 'backend', 'status'] },
  { id: 'export-config', tab: 'system', label: 'Export Preferences JSON', desc: 'Backup active GIS presets, audio volumes, and HUD layouts', category: 'Backup & System', keywords: ['export', 'json', 'backup', 'download', 'save'] },
  { id: 'import-config', tab: 'system', label: 'Import Preferences JSON', desc: 'Restore configuration from an exported INDRA JSON profile', category: 'Backup & System', keywords: ['import', 'restore', 'upload', 'load'] },
  { id: 'factory-reset', tab: 'system', label: 'Factory Defaults Reset', desc: 'Revert all tactical settings back to factory specifications', category: 'Backup & System', keywords: ['reset', 'factory', 'default', 'wipe', 'revert'] },
];

// ── Animation Variants ────────────────────────────────────────────────────────

const backdropVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.22 } },
  exit: { opacity: 0, transition: { duration: 0.18 } },
};

const panelVariants = {
  hidden: { x: '100%' },
  visible: { x: 0, transition: { type: 'spring', damping: 27, stiffness: 270, delay: 0.02 } },
  exit: { x: '100%', transition: { type: 'spring', damping: 30, stiffness: 300 } },
};

const navRailVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.025, delayChildren: 0.08 } },
};

const navItemVariants = {
  hidden: { opacity: 0, x: -6 },
  visible: { opacity: 1, x: 0, transition: { type: 'spring', stiffness: 320, damping: 24 } },
};

// ── Tab Transition Component ──────────────────────────────────────────────────

function TabContent({ tabKey, direction, children }: { tabKey: string; direction: number; children: React.ReactNode }) {
  return (
    <AnimatePresence mode="wait" custom={direction}>
      <motion.div
        key={tabKey}
        custom={direction}
        initial={{ y: direction * 14, opacity: 0, filter: 'blur(3px)' }}
        animate={{ y: 0, opacity: 1, filter: 'blur(0px)', transition: { type: 'spring', damping: 24, stiffness: 280 } }}
        exit={{ y: direction * -14, opacity: 0, filter: 'blur(3px)', transition: { duration: 0.12 } }}
        className="space-y-4 pb-2"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// ── Reusable Micro-Components ────────────────────────────────────────────────

function SelectCard({
  isSelected,
  onClick,
  children,
  className,
}: {
  isSelected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.button
      type="button"
      whileHover={{ y: -2, scale: 1.015 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 450, damping: 26 }}
      onClick={onClick}
      className={cn(
        'relative text-left p-2.5 rounded-xl border transition-all text-xs outline-none select-none',
        isSelected
          ? 'bg-gradient-to-br from-[#B5482E]/20 to-white/[0.04] border-[#B5482E]/80 shadow-[0_0_0_1px_rgba(181,72,46,0.6),0_4px_18px_rgba(181,72,46,0.18)]'
          : 'bg-white/[0.03] hover:bg-white/[0.07] border-white/[0.08] hover:border-white/20 text-slate-300',
        className,
      )}
    >
      {isSelected && (
        <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-[#F97316] shadow-[0_0_6px_#F97316]" />
      )}
      {children}
    </motion.button>
  );
}

function SpringToggle({
  value,
  onChange,
  size = 'sm',
}: {
  value: boolean;
  onChange: () => void;
  size?: 'sm' | 'md';
}) {
  const isSm = size === 'sm';
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={onChange}
      className={cn(
        'relative shrink-0 rounded-full transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[#F97316]/50',
        isSm ? 'h-5 w-9' : 'h-6 w-11',
      )}
      style={{ background: value ? '#B5482E' : '#2A3649' }}
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 600, damping: 32 }}
        className={cn(
          'absolute top-0.5 rounded-full bg-white shadow-md block',
          isSm ? 'h-4 w-4' : 'h-5 w-5',
        )}
        style={{ left: value ? (isSm ? 'calc(100% - 18px)' : 'calc(100% - 22px)') : '2px' }}
      />
      {value && (
        <motion.span
          initial={{ opacity: 0, scale: 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          className="absolute inset-0 rounded-full ring-2 ring-[#F97316]/40 pointer-events-none"
        />
      )}
    </button>
  );
}

function SectionHeader({
  icon: Icon,
  label,
  badge,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  badge?: string;
}) {
  return (
    <div className="mb-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-mono font-bold uppercase tracking-wider text-slate-300">
          <Icon className="w-3.5 h-3.5 text-[#F97316]" />
          <span>{label}</span>
        </div>
        {badge && (
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-400 border border-white/[0.08]">
            {badge}
          </span>
        )}
      </div>
      <div className="h-px mt-1.5 bg-gradient-to-r from-[#B5482E]/50 via-white/[0.08] to-transparent" />
    </div>
  );
}

function ToggleRow({
  label,
  desc,
  warn,
  value,
  onChange,
}: {
  label: React.ReactNode;
  desc?: string;
  warn?: string;
  value: boolean;
  onChange: () => void;
}) {
  return (
    <div className="px-3 py-2.5 flex items-center justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-white">{label}</div>
        {warn && <p className="text-[10px] text-amber-400 font-mono mt-0.5">{warn}</p>}
        {desc && <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">{desc}</p>}
      </div>
      <SpringToggle value={value} onChange={onChange} />
    </div>
  );
}

// ── Interactive Widgets ───────────────────────────────────────────────────────

function AudioWaveformVisualizer({ isPlaying }: { isPlaying: boolean }) {
  const bars = [35, 70, 95, 60, 100, 85, 40, 90, 65, 80, 50, 75];
  return (
    <div className="flex items-center gap-1 h-6 px-2.5 bg-black/40 rounded-lg border border-white/10">
      {bars.map((h, i) => (
        <motion.span
          key={i}
          className="w-1 rounded-full bg-gradient-to-t from-[#B5482E] to-[#F97316]"
          animate={
            isPlaying
              ? {
                  height: [`${Math.max(20, h * 0.3)}%`, `${h}%`, `${Math.max(20, h * 0.4)}%`],
                  opacity: [0.6, 1, 0.7],
                }
              : { height: '22%', opacity: 0.35 }
          }
          transition={{
            repeat: isPlaying ? Infinity : 0,
            duration: 0.35 + (i % 3) * 0.12,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  );
}

function CoordinateMatrixCard({
  format,
  mgrsUnlocked,
  onCopy,
}: {
  format: CoordFormat;
  mgrsUnlocked: boolean;
  onCopy: (text: string) => void;
}) {
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null);
  const sampleLat = 28.6139;
  const sampleLon = 77.2090;

  const dd = formatCoordinates(sampleLat, sampleLon, 'dd');
  const dms = formatCoordinates(sampleLat, sampleLon, 'dms');
  const mgrs = formatCoordinates(sampleLat, sampleLon, 'mgrs');

  const handleCopy = (text: string, fmtKey: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedFormat(fmtKey);
    onCopy(text);
    setTimeout(() => setCopiedFormat(null), 2000);
  };

  return (
    <div className="p-3 rounded-xl bg-black/30 border border-white/10 space-y-2">
      <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
        <span className="flex items-center gap-1.5 text-[#F97316] font-bold uppercase">
          <Compass className="w-3.5 h-3.5" /> Live Reference Matrix (New Delhi HQ)
        </span>
        <span className="text-[9px] text-slate-500">Tap to copy</span>
      </div>

      <div className="grid grid-cols-1 gap-1.5 text-xs font-mono">
        <button
          type="button"
          onClick={() => handleCopy(dd, 'dd')}
          className={cn(
            'flex items-center justify-between px-2.5 py-1.5 rounded-lg border transition-all text-left',
            format === 'dd'
              ? 'bg-[#B5482E]/20 border-[#B5482E]/60 text-white'
              : 'bg-white/[0.02] border-white/[0.06] text-slate-300 hover:bg-white/[0.06]',
          )}
        >
          <div className="flex items-center gap-2">
            <span className="text-[9px] px-1 rounded bg-white/10 text-slate-400 font-bold">DD</span>
            <span className="font-semibold">{dd}</span>
          </div>
          {copiedFormat === 'dd' ? (
            <span className="text-[9px] text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> Copied</span>
          ) : (
            <Copy className="w-3 h-3 text-slate-500 hover:text-white" />
          )}
        </button>

        <button
          type="button"
          onClick={() => handleCopy(dms, 'dms')}
          className={cn(
            'flex items-center justify-between px-2.5 py-1.5 rounded-lg border transition-all text-left',
            format === 'dms'
              ? 'bg-[#B5482E]/20 border-[#B5482E]/60 text-white'
              : 'bg-white/[0.02] border-white/[0.06] text-slate-300 hover:bg-white/[0.06]',
          )}
        >
          <div className="flex items-center gap-2">
            <span className="text-[9px] px-1 rounded bg-white/10 text-slate-400 font-bold">DMS</span>
            <span className="font-semibold">{dms}</span>
          </div>
          {copiedFormat === 'dms' ? (
            <span className="text-[9px] text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> Copied</span>
          ) : (
            <Copy className="w-3 h-3 text-slate-500 hover:text-white" />
          )}
        </button>

        <button
          type="button"
          onClick={() => mgrsUnlocked && handleCopy(mgrs, 'mgrs')}
          disabled={!mgrsUnlocked}
          className={cn(
            'flex items-center justify-between px-2.5 py-1.5 rounded-lg border transition-all text-left',
            !mgrsUnlocked
              ? 'opacity-40 bg-white/[0.01] border-white/[0.04] cursor-not-allowed text-slate-500'
              : format === 'mgrs'
              ? 'bg-[#B5482E]/20 border-[#B5482E]/60 text-white'
              : 'bg-white/[0.02] border-white/[0.06] text-slate-300 hover:bg-white/[0.06]',
          )}
        >
          <div className="flex items-center gap-2">
            <span className="text-[9px] px-1 rounded bg-white/10 text-slate-400 font-bold">MGRS</span>
            <span className="font-semibold">{mgrsUnlocked ? mgrs : 'LOCKED (Enable in Security)'}</span>
          </div>
          {mgrsUnlocked ? (
            copiedFormat === 'mgrs' ? (
              <span className="text-[9px] text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> Copied</span>
            ) : (
              <Copy className="w-3 h-3 text-slate-500 hover:text-white" />
            )
          ) : (
            <Lock className="w-3 h-3 text-slate-500" />
          )}
        </button>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function SettingsDrawer({ isOpen, onClose }: SettingsDrawerProps) {
  const { language: currentLang, setLanguage: changeLang } = useTranslation();
  const { settings, updateSettings, resetSettings, testAlarm } = useSettings();

  // DEFAULT TAB IS NOW 'general'
  const [activeTab, setActiveTab] = useState<TabKey>('general');
  const [direction, setDirection] = useState(1);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Rail tooltip hover state
  const [hoveredTab, setHoveredTab] = useState<TabKey | null>(null);

  // Reset confirmation safety state
  const [resetConfirming, setResetConfirming] = useState(false);

  // Live Station Clocks
  const [clocks, setClocks] = useState({ ist: '', utc: '' });

  useEffect(() => {
    const updateClocks = () => {
      const now = new Date();
      setClocks({
        ist: now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }),
        utc: now.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour12: false }) + 'Z',
      });
    };
    updateClocks();
    const interval = setInterval(updateClocks, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleTabChange = (tab: TabKey) => {
    setDirection(ALL_TABS.indexOf(tab) >= ALL_TABS.indexOf(activeTab) ? 1 : -1);
    setActiveTab(tab);
    setSearchQuery('');
  };

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === 'Escape') {
        if (searchQuery) {
          setSearchQuery('');
        } else {
          onClose();
        }
        return;
      }

      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        searchInputRef.current?.focus();
        return;
      }

      if (document.activeElement?.tagName !== 'INPUT' && e.key >= '1' && e.key <= '9') {
        const tabIdx = parseInt(e.key, 10) - 1;
        if (ALL_TABS[tabIdx]) {
          handleTabChange(ALL_TABS[tabIdx]);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, searchQuery, onClose, activeTab]);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3000);
  };

  const handleTestAudio = (pattern?: SirenPattern) => {
    setIsPlayingAudio(true);
    testAlarm(pattern);
    setTimeout(() => setIsPlayingAudio(false), 2000);
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
      try {
        updateSettings(JSON.parse(event.target?.result as string));
        showToast('Configuration imported successfully');
      } catch {
        showToast('Failed to parse settings JSON file');
      }
    };
    reader.readAsText(file);
  };

  const handleFactoryReset = () => {
    if (!resetConfirming) {
      setResetConfirming(true);
      setTimeout(() => setResetConfirming(false), 6000);
    } else {
      resetSettings();
      setResetConfirming(false);
      showToast('All settings reset to factory defaults');
    }
  };

  // Instant Search filter logic
  const searchResults = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return [];
    return SEARCHABLE_CATALOG.filter((item) =>
      item.label.toLowerCase().includes(q) ||
      item.desc.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.keywords.some((k) => k.toLowerCase().includes(q)),
    );
  }, [searchQuery]);

  // Volume calculations for visual gauge
  const volumePct = Math.round(settings.alertVolume * 100);
  const volumeDb = Math.round(45 + settings.alertVolume * 45);
  const VolumeIcon = !settings.audioAlertsEnabled || settings.alertVolume === 0
    ? VolumeX
    : settings.alertVolume < 0.5
    ? Volume1
    : Volume2;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop — Directional vignette */}
          <motion.div
            variants={backdropVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={onClose}
            className="fixed inset-0 z-50"
            style={{
              background: 'radial-gradient(ellipse 70% 100% at 100% 50%, rgba(3, 7, 18, 0.85) 0%, rgba(0, 0, 0, 0.5) 100%)',
              backdropFilter: 'blur(8px)',
            }}
          />

          {/* Panel Container — Obsidian chassis */}
          <motion.aside
            variants={panelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed right-0 top-0 h-screen z-50 flex flex-col overflow-hidden text-slate-200"
            style={{
              width: 'min(520px, 100vw)',
              background: 'linear-gradient(165deg, rgba(16, 24, 38, 0.97) 0%, rgba(10, 16, 26, 0.99) 100%)',
              borderLeft: '1px solid rgba(249, 115, 22, 0.18)',
              boxShadow: '-20px 0 60px rgba(0, 0, 0, 0.75), inset 1px 0 0 rgba(255, 255, 255, 0.05)',
            }}
          >
            {/* ── UNIFIED FULL-WIDTH HEADER ──────────────────────────── */}
            <header className="shrink-0 flex items-center justify-between px-4 py-3 border-b border-white/[0.08] bg-black/40">
              <div className="flex items-center gap-2.5 min-w-0">
                <motion.div
                  whileHover={{ rotate: 90 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 18 }}
                  className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-[#F97316] relative"
                  style={{
                    background: 'linear-gradient(135deg, rgba(181, 72, 46, 0.25), rgba(249, 115, 22, 0.1))',
                    border: '1px solid rgba(249, 115, 22, 0.4)',
                  }}
                >
                  <Settings className="w-4 h-4" />
                  <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                </motion.div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-bold tracking-wide text-white truncate" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                      INDRA Tactical Config
                    </h2>
                    <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shrink-0">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                      LIVE SYNC
                    </span>
                  </div>
                  <p className="text-[9px] text-slate-400 font-mono">NODE-01 &middot; Auto-persisted to browser</p>
                </div>
              </div>

              <div className="flex items-center gap-1.5 shrink-0">
                <span className="hidden sm:flex items-center text-[9px] font-mono text-slate-400 bg-white/[0.05] px-1.5 py-0.5 rounded border border-white/[0.08]">
                  ESC
                </span>
                <motion.button
                  whileHover={{ scale: 1.1, rotate: 90 }}
                  whileTap={{ scale: 0.9 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                  onClick={onClose}
                  className="w-8 h-8 rounded-lg bg-white/[0.05] border border-white/[0.08] flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
                  aria-label="Close configuration drawer"
                >
                  <X className="w-4 h-4" />
                </motion.button>
              </div>
            </header>

            {/* ── SEARCH & FILTER BAR ───────────────────────────────── */}
            <div className="shrink-0 px-4 py-2 border-b border-white/[0.06] bg-black/25 flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Search 30+ settings (e.g. siren, mgrs, wind, dark)... [/]"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent text-xs text-white placeholder-slate-500 focus:outline-none font-mono"
              />
              {searchQuery ? (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
                  title="Clear search"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              ) : (
                <span className="text-[9px] font-mono text-slate-500 bg-white/[0.04] px-1 py-0.2 rounded border border-white/[0.06]">
                  /
                </span>
              )}
            </div>

            {/* ── TOAST NOTIFICATION ────────────────────────────────── */}
            <AnimatePresence>
              {toastMsg && (
                <motion.div
                  key="toast"
                  initial={{ opacity: 0, y: -12, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1, transition: { type: 'spring', stiffness: 450, damping: 22 } }}
                  exit={{ opacity: 0, y: -8, scale: 0.95, transition: { duration: 0.15 } }}
                  className="shrink-0 flex items-center gap-2 px-4 py-2 bg-emerald-500/20 border-b border-emerald-500/30 text-emerald-300 text-[11px] font-mono shadow-sm"
                >
                  <Check className="w-3.5 h-3.5 shrink-0" />
                  <span>{toastMsg}</span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* ── MAIN BODY: LEFT RAIL + RIGHT CONTENT ──────────────── */}
            <div className="flex-1 flex min-h-0 overflow-hidden">

              {/* ── LEFT TACTICAL NAVIGATION RAIL ─────────────────────── */}
              <motion.nav
                variants={navRailVariants}
                initial="hidden"
                animate="visible"
                className="w-[56px] shrink-0 flex flex-col py-2 border-r border-white/[0.07] bg-black/30 relative select-none"
              >
                {TAB_GROUPS.map((group, gi) => (
                  <React.Fragment key={gi}>
                    {gi > 0 && <div className="mx-2.5 my-1.5 h-px bg-white/[0.07]" />}
                    {group.tabs.map((tab) => {
                      const Icon = tab.icon;
                      const isActive = activeTab === tab.key && !searchQuery;
                      return (
                        <div key={tab.key} className="relative">
                          <motion.button
                            variants={navItemVariants}
                            whileHover={{ scale: 1.08 }}
                            whileTap={{ scale: 0.92 }}
                            onClick={() => handleTabChange(tab.key)}
                            onMouseEnter={() => setHoveredTab(tab.key)}
                            onMouseLeave={() => setHoveredTab(null)}
                            className={cn(
                              'relative flex flex-col items-center justify-center gap-0.5 h-[48px] w-full transition-colors duration-150',
                              isActive ? 'text-[#F97316]' : 'text-slate-400 hover:text-white',
                            )}
                            title={tab.label}
                          >
                            {isActive && (
                              <motion.span
                                layoutId="nav-active-bar"
                                className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-[#F97316]"
                                transition={{ type: 'spring', stiffness: 450, damping: 30 }}
                              />
                            )}
                            {isActive && (
                              <motion.span
                                layoutId="nav-active-bg"
                                className="absolute inset-1 rounded-xl"
                                style={{ background: 'rgba(181, 72, 46, 0.16)' }}
                                transition={{ type: 'spring', stiffness: 450, damping: 30 }}
                              />
                            )}
                            <Icon className="w-4 h-4 relative z-10" />
                            <span className={cn('text-[8px] font-bold tracking-wide relative z-10', isActive ? 'text-[#F97316]' : 'text-slate-400')}>
                              {tab.shortLabel}
                            </span>
                          </motion.button>

                          {/* Floating Tooltip */}
                          <AnimatePresence>
                            {hoveredTab === tab.key && (
                              <motion.div
                                initial={{ opacity: 0, x: 4, scale: 0.92 }}
                                animate={{ opacity: 1, x: 0, scale: 1 }}
                                exit={{ opacity: 0, x: 4, scale: 0.92 }}
                                transition={{ duration: 0.12 }}
                                className="absolute left-[58px] top-1/2 -translate-y-1/2 z-50 pointer-events-none whitespace-nowrap px-2.5 py-1 rounded-md text-[10px] font-mono font-semibold bg-slate-900/95 text-white border border-white/15 shadow-xl flex items-center gap-1.5"
                              >
                                <span>{tab.label}</span>
                                <span className="text-slate-400 text-[8px] bg-white/10 px-1 rounded">[{tab.hotkey}]</span>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      );
                    })}
                  </React.Fragment>
                ))}
              </motion.nav>

              {/* ── RIGHT SCROLLABLE CONTENT AREA ────────────────────── */}
              <div className="flex-1 overflow-y-auto p-4 drawer-scroll">

                {/* SEARCH RESULTS VIEW */}
                {searchQuery.trim().length > 0 ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs font-mono text-slate-400 pb-2 border-b border-white/[0.08]">
                      <span>Found <strong className="text-[#F97316]">{searchResults.length}</strong> matching settings</span>
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="text-[10px] text-slate-400 hover:text-white underline"
                      >
                        Clear filter
                      </button>
                    </div>

                    {searchResults.length === 0 ? (
                      <div className="py-8 text-center text-slate-500 font-mono text-xs">
                        No settings found matching &ldquo;{searchQuery}&rdquo;.
                        <div className="mt-2 text-[10px] text-slate-600">Try searching for &quot;siren&quot;, &quot;coords&quot;, &quot;dark&quot;, &quot;rain&quot;, or &quot;lock&quot;.</div>
                      </div>
                    ) : (
                      searchResults.map((item) => (
                        <div
                          key={item.id}
                          className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.08] hover:border-white/20 transition-colors flex items-center justify-between gap-3"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className="text-[9px] font-mono uppercase px-1.5 py-0.2 rounded bg-[#B5482E]/20 text-[#F97316] border border-[#B5482E]/40">
                                {item.category}
                              </span>
                              <h4 className="text-xs font-semibold text-white truncate">{item.label}</h4>
                            </div>
                            <p className="text-[10px] text-slate-400 line-clamp-1">{item.desc}</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleTabChange(item.tab)}
                            className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-white/[0.06] hover:bg-[#B5482E] text-white text-[10px] font-mono font-semibold transition-all"
                          >
                            <span>Open</span>
                            <ArrowRight className="w-3 h-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                ) : (
                  <>
                    {/* ── TAB 1: GENERAL SETTINGS (DEFAULT) ─────────── */}
                    {activeTab === 'general' && (
                      <TabContent tabKey="general" direction={direction}>
                        {/* Station Profile Banner */}
                        <div className="p-3.5 rounded-xl border border-white/10 bg-white/[0.03] space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                              <h4 className="text-xs font-bold text-white uppercase font-mono tracking-wide">
                                INDRA Station Node-01
                              </h4>
                            </div>
                            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-bold">
                              OPERATIONAL
                            </span>
                          </div>
                          <p className="text-[10px] text-slate-400">
                            Disaster Early Warning & Decision Support HUD &middot; SIH 2026 Sixth Sense
                          </p>
                          <div className="grid grid-cols-2 gap-2 pt-1 border-t border-white/[0.06] text-[10px] font-mono text-slate-400">
                            <div>Station: <span className="text-white font-semibold">New Delhi HQ</span></div>
                            <div>Telemetry: <span className="text-emerald-400 font-semibold">Live Ingestion</span></div>
                          </div>
                        </div>

                        {/* Interface Language */}
                        <div>
                          <SectionHeader icon={Globe} label="Interface Language / भाषा" badge="11 Languages" />
                          <div className="grid grid-cols-3 gap-1.5 max-h-36 overflow-y-auto pr-1 drawer-scroll">
                            {Object.entries(SUPPORTED_LANGUAGES).map(([code, meta]) => {
                              const isSel = currentLang === code;
                              return (
                                <SelectCard
                                  key={code}
                                  isSelected={isSel}
                                  onClick={() => changeLang(code as any)}
                                  className="p-2"
                                >
                                  <p className="text-xs truncate font-medium" style={{ fontFamily: meta.fontFamily }}>
                                    {meta.nativeName}
                                  </p>
                                  <p className="text-[9px] text-slate-400 truncate">{meta.name}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        {/* Interface Theme */}
                        <div>
                          <SectionHeader icon={Sliders} label="Interface Theme" />
                          <div className="grid grid-cols-3 gap-2">
                            {[
                              { id: 'dark', label: 'Dark Ops', desc: 'Tactical command' },
                              { id: 'light', label: 'Light', desc: 'Day parchment' },
                              { id: 'high_contrast', label: 'Contrast', desc: 'Sunlight visibility' },
                            ].map((m) => {
                              const isSel = settings.themeMode === m.id;
                              return (
                                <SelectCard
                                  key={m.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ themeMode: m.id as ThemeMode })}
                                  className="text-center"
                                >
                                  <p className="text-xs font-semibold text-white">{m.label}</p>
                                  <p className="text-[9px] text-slate-400 mt-0.5">{m.desc}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        {/* Refresh Rate & Timezone */}
                        <div className="grid grid-cols-2 gap-2.5">
                          <div>
                            <SectionHeader icon={Zap} label="Refresh Rate" />
                            <div className="grid grid-cols-2 gap-1 font-mono">
                              {[
                                { id: 5, label: '5s Live' },
                                { id: 15, label: '15s Normal' },
                                { id: 30, label: '30s Eco' },
                                { id: 0, label: 'Manual' },
                              ].map((rate) => {
                                const isSel = settings.autoRefreshInterval === rate.id;
                                return (
                                  <motion.button
                                    key={rate.id}
                                    whileHover={{ y: -1 }}
                                    whileTap={{ scale: 0.95 }}
                                    onClick={() => updateSettings({ autoRefreshInterval: rate.id as RefreshInterval })}
                                    className={cn(
                                      'py-1.5 px-1 text-center rounded-lg border text-[10px] font-mono transition-all',
                                      isSel
                                        ? 'bg-[#B5482E] text-white border-[#B5482E] font-bold shadow-md'
                                        : 'bg-white/[0.04] border-white/10 text-slate-400 hover:text-white hover:bg-white/[0.08]',
                                    )}
                                  >
                                    {rate.label}
                                  </motion.button>
                                );
                              })}
                            </div>
                          </div>

                          <div>
                            <SectionHeader icon={Clock} label="Timezone" />
                            <div className="space-y-1">
                              {[
                                { id: 'ist', label: 'IST (+05:30)', desc: 'New Delhi HQ' },
                                { id: 'utc', label: 'UTC Zulu', desc: 'Aviation Standard' },
                              ].map((tz) => {
                                const isSel = settings.timezone === tz.id;
                                return (
                                  <SelectCard
                                    key={tz.id}
                                    isSelected={isSel}
                                    onClick={() => updateSettings({ timezone: tz.id as TimezoneMode })}
                                    className="py-1 px-2"
                                  >
                                    <p className="text-xs font-semibold text-white">{tz.label}</p>
                                    <p className="text-[9px] text-slate-400">{tz.desc}</p>
                                  </SelectCard>
                                );
                              })}
                            </div>
                          </div>
                        </div>

                        {/* Master Siren Audio Quick Toggle */}
                        <div className="p-3 rounded-xl border border-[#B5482E]/35 bg-[#B5482E]/10 flex items-center justify-between">
                          <div className="flex items-center gap-2.5">
                            <Volume2 className="w-4 h-4 text-[#F97316]" />
                            <div>
                              <p className="text-xs font-semibold text-white">Emergency Siren Audio</p>
                              <p className="text-[10px] text-slate-400">Master sound toggle for disaster alerts</p>
                            </div>
                          </div>
                          <SpringToggle
                            value={settings.audioAlertsEnabled}
                            onChange={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })}
                          />
                        </div>

                        {/* Display & Performance */}
                        <div>
                          <SectionHeader icon={Sliders} label="Display & Performance" />
                          <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06] bg-white/[0.03]">
                            <div className="px-3 py-2.5 flex items-center justify-between">
                              <div>
                                <p className="text-xs font-medium text-white">Compact Data Density</p>
                                <p className="text-[10px] text-slate-400">Tight spacing for multi-monitor operations</p>
                              </div>
                              <SpringToggle
                                value={settings.uiDensity === 'compact'}
                                onChange={() => updateSettings({ uiDensity: settings.uiDensity === 'compact' ? 'standard' : 'compact' })}
                              />
                            </div>
                            <ToggleRow
                              label="Glassmorphism & Glow"
                              desc="Frosted blur panels and edge lighting"
                              value={settings.glassmorphismEffects}
                              onChange={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })}
                            />
                            <ToggleRow
                              label="Reduced Motion"
                              desc="Optimize performance on field hardware"
                              value={settings.reducedMotion}
                              onChange={() => updateSettings({ reducedMotion: !settings.reducedMotion })}
                            />
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 2: MAP & GIS ──────────────────────────── */}
                    {activeTab === 'map' && (
                      <TabContent tabKey="map" direction={direction}>
                        <div>
                          <SectionHeader icon={Globe} label="Default Map Projection" />
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { id: 'globe', label: '3D Spherical Globe', desc: 'Curvature & true orbit', icon: Globe },
                              { id: 'mercator', label: '2D Flat Mercator', desc: 'Planar standard grid', icon: MapIcon },
                            ].map((proj) => {
                              const Icon = proj.icon;
                              const isSel = settings.mapProjection === proj.id;
                              return (
                                <SelectCard
                                  key={proj.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ mapProjection: proj.id as ProjectionPreset })}
                                >
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
                              { id: 'satellite', label: 'Satellite', badge: 'ESRI HIGH-RES', desc: 'Orbital imagery' },
                              { id: 'dark', label: 'Dark Tactical', badge: 'CARTO DARK', desc: 'Night ops high contrast' },
                              { id: 'topo', label: 'Topographic', badge: 'TERRAIN HYBRID', desc: 'Elevation contours' },
                              { id: 'street', label: 'Street Vector', badge: 'OPENSTREETMAP', desc: 'Road network vector' },
                            ].map((base) => {
                              const isSel = settings.defaultBasemap === base.id;
                              return (
                                <SelectCard
                                  key={base.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ defaultBasemap: base.id as BasemapPreset })}
                                >
                                  <div className="flex items-center justify-between mb-0.5">
                                    <span className="text-xs font-semibold text-white">{base.label}</span>
                                    {isSel && <Check className="w-3.5 h-3.5 text-[#F97316]" />}
                                  </div>
                                  <p className="text-[10px] text-slate-400 leading-tight">{base.desc}</p>
                                  <span className="text-[8px] font-mono text-[#F97316]/80 mt-1 block">{base.badge}</span>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
                          <div>
                            <p className="text-xs font-semibold text-white">Globe Ambient Orbit</p>
                            <p className="text-[10px] text-slate-400">Slow rotation when inactive</p>
                          </div>
                          <SpringToggle
                            value={settings.globeAutoRotate}
                            onChange={() => updateSettings({ globeAutoRotate: !settings.globeAutoRotate })}
                          />
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 3: AUDIO ALARMS ───────────────────────── */}
                    {activeTab === 'alerts' && (
                      <TabContent tabKey="alerts" direction={direction}>
                        <div
                          className="p-4 rounded-xl border border-[#B5482E]/35 space-y-3"
                          style={{ background: 'linear-gradient(135deg, rgba(181, 72, 46, 0.14) 0%, rgba(255, 255, 255, 0.02) 100%)' }}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2.5">
                              <VolumeIcon className="w-5 h-5 text-[#F97316]" />
                              <div>
                                <h4 className="text-xs font-bold text-white uppercase font-mono">Emergency Siren</h4>
                                <p className="text-[10px] text-slate-400">Synthesizer warning for critical hazards</p>
                              </div>
                            </div>
                            <SpringToggle
                              size="md"
                              value={settings.audioAlertsEnabled}
                              onChange={() => updateSettings({ audioAlertsEnabled: !settings.audioAlertsEnabled })}
                            />
                          </div>

                          <div className="pt-2 border-t border-white/10 space-y-2">
                            <div className="flex items-center justify-between text-[11px] font-mono">
                              <span className="text-slate-300">Volume Output</span>
                              <div className="flex items-center gap-2">
                                <span className={cn('text-[10px] font-bold', volumePct > 75 ? 'text-rose-400' : 'text-slate-400')}>
                                  ~{volumeDb} dB
                                </span>
                                <span className="font-bold text-[#F97316]">{volumePct}%</span>
                              </div>
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

                            <div className="flex items-center justify-between pt-1">
                              <AudioWaveformVisualizer isPlaying={isPlayingAudio} />
                              <motion.button
                                whileHover={{ scale: 1.04 }}
                                whileTap={{ scale: 0.95 }}
                                onClick={() => handleTestAudio()}
                                disabled={!settings.audioAlertsEnabled || isPlayingAudio}
                                className={cn(
                                  'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all',
                                  isPlayingAudio
                                    ? 'bg-[#B5482E] text-white shadow-lg animate-pulse'
                                    : 'bg-[#B5482E]/25 hover:bg-[#B5482E]/40 text-white border border-[#B5482E]/60',
                                )}
                              >
                                <Play className="w-3.5 h-3.5 fill-current" />
                                {isPlayingAudio ? 'Sounding...' : 'Test Siren'}
                              </motion.button>
                            </div>
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
                                <SelectCard
                                  key={pat.id}
                                  isSelected={isSel}
                                  onClick={() => {
                                    updateSettings({ sirenPattern: pat.id as SirenPattern });
                                    if (settings.audioAlertsEnabled) handleTestAudio(pat.id as SirenPattern);
                                  }}
                                >
                                  <div className="flex items-center justify-between">
                                    <span className="text-xs font-semibold text-white">{pat.label}</span>
                                    {isSel && <Check className="w-3 h-3 text-[#F97316]" />}
                                  </div>
                                  <span className="text-[10px] text-slate-400 mt-0.5 block">{pat.desc}</span>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        <div>
                          <SectionHeader icon={AlertTriangle} label="Incident Threshold Filter" />
                          <div className="grid grid-cols-2 gap-1.5">
                            {[
                              { id: 'ALL', label: 'All Incidents', desc: 'Low, Moderate & Critical' },
                              { id: 'MODERATE_PLUS', label: 'Moderate+', desc: 'Exclude minor warnings' },
                              { id: 'HIGH_PLUS', label: 'High & Critical', desc: 'Severe hazard bulletins' },
                              { id: 'CRITICAL_ONLY', label: 'Critical Only', desc: 'Flash floods / cyclones' },
                            ].map((sev) => {
                              const isSel = settings.minSeverityThreshold === sev.id;
                              return (
                                <SelectCard
                                  key={sev.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ minSeverityThreshold: sev.id as any })}
                                >
                                  <p className="text-xs font-semibold text-white">{sev.label}</p>
                                  <p className="text-[9px] text-slate-400">{sev.desc}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 4: UNITS & METRICS ─────────────────────── */}
                    {activeTab === 'units' && (
                      <TabContent tabKey="units" direction={direction}>
                        <CoordinateMatrixCard
                          format={settings.coordFormat}
                          mgrsUnlocked={settings.advancedCoordFormats}
                          onCopy={(txt) => showToast(`Copied ${txt} to clipboard`)}
                        />

                        <div className="p-3.5 rounded-xl border border-white/10 bg-white/[0.03]">
                          <p className="text-[10px] font-mono uppercase text-[#F97316] font-bold mb-2">
                            Weather Telemetry Output Sample
                          </p>
                          <div className="grid grid-cols-3 gap-2 font-mono text-center">
                            {[
                              { label: 'Temp', value: formatTemperature(32.4, settings.tempUnit), color: 'text-amber-400' },
                              { label: 'Wind', value: formatWindSpeed(68, settings.windUnit), color: 'text-sky-400' },
                              { label: 'Rain', value: formatRainfall(85.5, settings.rainUnit), color: 'text-blue-400' },
                            ].map((item) => (
                              <div key={item.label} className="bg-black/35 p-2 rounded-lg border border-white/10">
                                <span className="text-[9px] text-slate-500 block">{item.label}</span>
                                <span className={cn('text-sm font-bold', item.color)}>{item.value}</span>
                              </div>
                            ))}
                          </div>
                        </div>

                        <div>
                          <SectionHeader icon={Gauge} label="Temperature Scale" />
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { id: 'celsius', label: 'Celsius (°C)', desc: 'IMD India standard' },
                              { id: 'fahrenheit', label: 'Fahrenheit (°F)', desc: 'Imperial standard' },
                            ].map((u) => {
                              const isSel = settings.tempUnit === u.id;
                              return (
                                <SelectCard
                                  key={u.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ tempUnit: u.id as TempUnit })}
                                >
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
                            {[
                              { id: 'kmh', label: 'km/h', desc: 'Civilian standard' },
                              { id: 'knots', label: 'Knots', desc: 'Maritime / NDMA' },
                              { id: 'ms', label: 'm/s', desc: 'Scientific model' },
                            ].map((u) => {
                              const isSel = settings.windUnit === u.id;
                              return (
                                <SelectCard
                                  key={u.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ windUnit: u.id as WindUnit })}
                                  className="text-center"
                                >
                                  <p className="text-xs font-mono font-semibold text-white">{u.label}</p>
                                  <p className="text-[9px] text-slate-500">{u.desc}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        <div>
                          <SectionHeader icon={Compass} label="Coordinates Display" />
                          <div className="space-y-1.5">
                            {[
                              { id: 'dd', label: 'Decimal Degrees (DD)', sample: '28.6139° N, 77.2090° E' },
                              { id: 'dms', label: 'Degrees Minutes Seconds (DMS)', sample: "28°36'50\"N, 77°12'32\"E" },
                              ...(settings.advancedCoordFormats ? [{ id: 'mgrs', label: 'Military Grid (MGRS)', sample: '43R BK 21456 68421' }] : []),
                            ].map((cf) => {
                              const isSel = settings.coordFormat === cf.id;
                              return (
                                <SelectCard
                                  key={cf.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ coordFormat: cf.id as CoordFormat })}
                                  className="flex items-center justify-between"
                                >
                                  <div>
                                    <p className="text-xs font-semibold text-white">{cf.label}</p>
                                    <p className="text-[10px] font-mono text-slate-400">{cf.sample}</p>
                                  </div>
                                  {isSel && <Check className="w-4 h-4 text-[#F97316] shrink-0" />}
                                </SelectCard>
                              );
                            })}
                            {!settings.advancedCoordFormats && (
                              <p className="text-[10px] text-slate-500 pl-1">Enable MGRS in Security tab to unlock NATO Military Grid.</p>
                            )}
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 5: HUD & STYLE ────────────────────────── */}
                    {activeTab === 'hud' && (
                      <TabContent tabKey="hud" direction={direction}>
                        <div>
                          <SectionHeader icon={Globe} label="Interface Language / भाषा" />
                          <div className="grid grid-cols-3 gap-1.5 max-h-44 overflow-y-auto pr-1 drawer-scroll">
                            {Object.entries(SUPPORTED_LANGUAGES).map(([code, meta]) => {
                              const isSel = currentLang === code;
                              return (
                                <SelectCard
                                  key={code}
                                  isSelected={isSel}
                                  onClick={() => changeLang(code as any)}
                                  className="p-2"
                                >
                                  <p className="text-xs truncate font-medium" style={{ fontFamily: meta.fontFamily }}>
                                    {meta.nativeName}
                                  </p>
                                  <p className="text-[9px] text-slate-400 truncate">{meta.name}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        <div>
                          <SectionHeader icon={Sliders} label="Interface Theme" />
                          <div className="grid grid-cols-3 gap-2">
                            {[
                              { id: 'dark', label: 'Dark Ops', desc: 'Command center' },
                              { id: 'light', label: 'Light', desc: 'Day parchment' },
                              { id: 'high_contrast', label: 'Contrast', desc: 'Sunlight visibility' },
                            ].map((m) => {
                              const isSel = settings.themeMode === m.id;
                              return (
                                <SelectCard
                                  key={m.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ themeMode: m.id as ThemeMode })}
                                  className="text-center"
                                >
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
                            {[
                              { id: 'standard', label: 'Standard', desc: 'Balanced spacing' },
                              { id: 'compact', label: 'Compact', desc: 'Maximum data density' },
                            ].map((d) => {
                              const isSel = settings.uiDensity === d.id;
                              return (
                                <SelectCard
                                  key={d.id}
                                  isSelected={isSel}
                                  onClick={() => updateSettings({ uiDensity: d.id as any })}
                                >
                                  <p className="text-xs font-semibold text-white">{d.label}</p>
                                  <p className="text-[10px] text-slate-400">{d.desc}</p>
                                </SelectCard>
                              );
                            })}
                          </div>
                        </div>

                        <div>
                          <SectionHeader icon={Sliders} label="Visual Effects" />
                          <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06] bg-white/[0.03]">
                            <ToggleRow
                              label="Glassmorphism & Glow"
                              desc="Frosted glass chassis and glow edges"
                              value={settings.glassmorphismEffects}
                              onChange={() => updateSettings({ glassmorphismEffects: !settings.glassmorphismEffects })}
                            />
                            <ToggleRow
                              label="Reduced Motion"
                              desc="Disable animations for low-spec field gear"
                              value={settings.reducedMotion}
                              onChange={() => updateSettings({ reducedMotion: !settings.reducedMotion })}
                            />
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 6: ALERT DELIVERY ─────────────────────── */}
                    {activeTab === 'notifications' && (
                      <TabContent tabKey="notifications" direction={direction}>
                        <div>
                          <SectionHeader icon={Bell} label="Alert Broadcast Channels" />
                          <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06] bg-white/[0.03]">
                            <ToggleRow
                              label="In-App Incident Banners"
                              desc="Live top ticker on new hazard reports"
                              value={settings.notifyInApp}
                              onChange={() => updateSettings({ notifyInApp: !settings.notifyInApp })}
                            />

                            <div className="px-3 py-2.5 space-y-2">
                              <ToggleRow
                                label={<span className="flex items-center gap-1.5"><Mail className="w-3.5 h-3.5 text-slate-400" /> Dispatch Email</span>}
                                warn="⚠️ Backend email dispatch pending integration"
                                value={settings.notifyEmail}
                                onChange={() => updateSettings({ notifyEmail: !settings.notifyEmail })}
                              />
                              <AnimatePresence>
                                {settings.notifyEmail && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="overflow-hidden"
                                  >
                                    <input
                                      type="email"
                                      placeholder="officer@ndma.gov.in"
                                      value={settings.notifyEmailAddress}
                                      onChange={(e) => updateSettings({ notifyEmailAddress: e.target.value })}
                                      className="w-full px-3 py-1.5 text-xs rounded-lg bg-white/[0.08] border border-white/20 text-white placeholder-slate-500 focus:outline-none focus:border-[#B5482E] transition-colors"
                                    />
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </div>

                            <div className="px-3 py-2.5 space-y-2">
                              <ToggleRow
                                label={<span className="flex items-center gap-1.5"><Phone className="w-3.5 h-3.5 text-slate-400" /> SMS / WhatsApp Broadcast</span>}
                                warn="⚠️ SMS gateway pending integration"
                                value={settings.notifyPhoneEnabled}
                                onChange={() => updateSettings({ notifyPhoneEnabled: !settings.notifyPhoneEnabled })}
                              />
                              <AnimatePresence>
                                {settings.notifyPhoneEnabled && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="overflow-hidden"
                                  >
                                    <input
                                      type="tel"
                                      placeholder="+91 98765 43210"
                                      value={settings.notifyPhone}
                                      onChange={(e) => updateSettings({ notifyPhone: e.target.value })}
                                      className="w-full px-3 py-1.5 text-xs rounded-lg bg-white/[0.08] border border-white/20 text-white placeholder-slate-500 focus:outline-none focus:border-[#B5482E] transition-colors"
                                    />
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </div>
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 7: SECURITY & ACCESS ──────────────────── */}
                    {activeTab === 'security' && (
                      <TabContent tabKey="security" direction={direction}>
                        <div>
                          <SectionHeader icon={Timer} label="Inactivity Lockout Timer" />
                          <p className="text-[10px] text-slate-400 mb-2.5">
                            Renders a tactical lock overlay when the terminal is idle. Click to resume.
                          </p>
                          <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
                            {(
                              [
                                { id: 0, label: 'Off' },
                                { id: 5, label: '5 min' },
                                { id: 15, label: '15 min' },
                                { id: 30, label: '30 min' },
                              ] as { id: IdleLockMinutes; label: string }[]
                            ).map((opt) => {
                              const isSel = settings.idleLockMinutes === opt.id;
                              return (
                                <motion.button
                                  key={opt.id}
                                  whileHover={{ y: -1 }}
                                  whileTap={{ scale: 0.95 }}
                                  onClick={() => updateSettings({ idleLockMinutes: opt.id })}
                                  className={cn(
                                    'py-2 px-1 text-center rounded-lg border transition-all',
                                    isSel
                                      ? 'bg-[#B5482E] text-white border-[#B5482E] font-bold shadow-md'
                                      : 'bg-white/[0.04] border-white/10 text-slate-400 hover:text-white hover:bg-white/[0.08]',
                                  )}
                                >
                                  {opt.label}
                                </motion.button>
                              );
                            })}
                          </div>
                        </div>

                        <div className="rounded-xl border border-white/[0.08] divide-y divide-white/[0.06] bg-white/[0.03]">
                          <ToggleRow
                            label="MGRS / Military Grid Targeting"
                            desc="Authorize MGRS coordinate selection in Units & HUD"
                            value={settings.advancedCoordFormats}
                            onChange={() => updateSettings({ advancedCoordFormats: !settings.advancedCoordFormats })}
                          />
                        </div>

                        <div className="p-3.5 rounded-xl border border-white/[0.08] bg-white/[0.03]">
                          <p className="text-xs font-semibold text-white flex items-center gap-1.5">
                            <Lock className="w-3.5 h-3.5 text-slate-400" /> Operator Access Key
                          </p>
                          {/* TODO(backend): POST /api/auth/change-password { currentPassword, newPassword } */}
                          <p className="text-[9px] text-amber-400 font-mono mt-0.5">⚠️ Password change requires backend authentication API</p>
                          <p className="text-[10px] text-slate-400 mt-1">Contact your INDRA node administrator to update credentials.</p>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 8: LIVE NETWORK ───────────────────────── */}
                    {activeTab === 'network' && (
                      <TabContent tabKey="network" direction={direction}>
                        <div className="p-4 rounded-xl border border-white/[0.08] bg-white/[0.03] space-y-3">
                          <div className="flex items-center gap-2">
                            <Wifi className="w-4 h-4 text-[#F97316]" />
                            <p className="text-xs font-semibold text-white">Live Data Ingestion</p>
                          </div>
                          <p className="text-[11px] text-slate-400 leading-relaxed">
                            Every HUD component connects directly to the live INDRA FastAPI backend and WebSocket engine. Simulated or mock data is permanently disabled.
                          </p>
                          <div className="p-2.5 rounded-lg bg-black/40 border border-white/10 flex items-center justify-between text-[10px] font-mono">
                            <div className="flex items-center gap-1.5 text-emerald-400">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                              WebSocket Stream Connected
                            </div>
                            <span className="text-slate-500">Latency: ~22ms</span>
                          </div>
                        </div>
                      </TabContent>
                    )}

                    {/* ── TAB 9: BACKUP & SYSTEM ────────────────────── */}
                    {activeTab === 'system' && (
                      <TabContent tabKey="system" direction={direction}>
                        <div className="p-4 rounded-xl border border-white/[0.08] bg-white/[0.03] space-y-3">
                          <div>
                            <h4 className="text-xs font-bold text-white uppercase font-mono">Preferences Profile Backup</h4>
                            <p className="text-[11px] text-slate-400 mt-0.5">
                              Export GIS basemaps, audio patterns, thresholds, and units as an INDRA profile JSON.
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <motion.button
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.97 }}
                              onClick={handleExportJson}
                              className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#B5482E] hover:bg-[#A03D25] text-white text-xs font-semibold font-mono transition-colors shadow-md"
                            >
                              <Download className="w-3.5 h-3.5" /> Export JSON
                            </motion.button>
                            <label className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-white/[0.07] hover:bg-white/[0.11] border border-white/15 text-slate-200 text-xs font-semibold font-mono cursor-pointer transition-colors shadow-sm">
                              <Upload className="w-3.5 h-3.5" /> Import
                              <input type="file" accept=".json" onChange={handleImportJson} className="hidden" />
                            </label>
                          </div>
                        </div>

                        <div className="p-4 rounded-xl border border-[#8C2F26]/40 bg-[#8C2F26]/10 space-y-2.5">
                          <div className="flex items-center gap-2 text-rose-400 text-xs font-bold font-mono">
                            <AlertTriangle className="w-4 h-4" />
                            FACTORY DEFAULTS RESET
                          </div>
                          <p className="text-xs text-slate-300">
                            Reverts all GIS basemaps, emergency audio volumes, measurement units, and telemetry rates to initial deployment standards.
                          </p>

                          {resetConfirming ? (
                            <motion.div
                              initial={{ opacity: 0, scale: 0.95 }}
                              animate={{ opacity: 1, scale: 1 }}
                              className="p-3 rounded-lg bg-rose-950/80 border border-rose-500/50 space-y-2"
                            >
                              <p className="text-[11px] text-rose-200 font-mono font-bold">
                                ⚠️ Confirm Factory Reset? All customized settings will be cleared.
                              </p>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={handleFactoryReset}
                                  className="flex-1 py-1.5 px-3 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-mono font-bold transition-colors shadow-md"
                                >
                                  Yes, Reset All
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setResetConfirming(false)}
                                  className="py-1.5 px-3 rounded-lg bg-white/10 hover:bg-white/20 text-slate-300 text-xs font-mono transition-colors"
                                >
                                  Cancel
                                </button>
                              </div>
                            </motion.div>
                          ) : (
                            <motion.button
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.97 }}
                              onClick={handleFactoryReset}
                              className="mt-1 flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#8C2F26]/40 hover:bg-[#8C2F26]/60 text-rose-200 border border-[#8C2F26]/60 text-xs font-mono font-semibold transition-colors"
                            >
                              <RotateCcw className="w-3.5 h-3.5" /> Reset to Defaults
                            </motion.button>
                          )}
                        </div>
                      </TabContent>
                    )}
                  </>
                )}

              </div>{/* end scrollable content area */}

            </div>{/* end body flex */}

            {/* ── TACTICAL FOOTER ────────────────────────────────────── */}
            <footer className="shrink-0 px-4 py-3 flex items-center justify-between border-t border-white/[0.08] bg-black/45 text-[10px] font-mono">
              <div className="flex items-center gap-3 text-slate-400">
                <span className="flex items-center gap-1 text-emerald-400 font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  IST {clocks.ist || '21:45:00'}
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-400">UTC {clocks.utc || '16:15:00Z'}</span>
              </div>

              <Link
                href="/settings"
                onClick={onClose}
                className="group flex items-center gap-1.5 font-semibold text-[#F97316] hover:text-[#FFA04A] transition-colors"
              >
                <span>Full Settings Page</span>
                <motion.span
                  className="inline-flex"
                  whileHover={{ x: 3 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                >
                  <ArrowRight className="w-3.5 h-3.5" />
                </motion.span>
              </Link>
            </footer>

          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
