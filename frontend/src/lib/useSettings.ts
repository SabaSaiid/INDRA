'use client';

import { useState, useEffect, useCallback } from 'react';

export const SETTINGS_STORAGE_KEY = 'indra_platform_settings';

export type BasemapPreset = 'satellite' | 'dark' | 'topo' | 'street';
export type ProjectionPreset = 'globe' | 'mercator';
export type SirenPattern = 'siren_continuous' | 'warble_fast' | 'pulsed_beacon' | 'chime_two_tone';
export type TempUnit = 'celsius' | 'fahrenheit';
export type WindUnit = 'kmh' | 'knots' | 'ms';
export type RainUnit = 'mm' | 'inches';
export type PressureUnit = 'hpa' | 'mbar' | 'inhg';
export type CoordFormat = 'dd' | 'dms' | 'mgrs';
export type TimezoneMode = 'ist' | 'utc';
export type ThemeMode = 'dark' | 'light' | 'high_contrast';
export type UiDensity = 'compact' | 'standard';
export type SeverityThreshold = 'ALL' | 'MODERATE_PLUS' | 'HIGH_PLUS' | 'CRITICAL_ONLY';
export type RefreshInterval = 5 | 15 | 30 | 60 | 0; // 0 = manual

export interface IndraSettings {
  // 1. Tactical Geospatial & Map
  mapProjection: ProjectionPreset;
  defaultBasemap: BasemapPreset;
  globeAutoRotate: boolean;
  globeRotationSpeed: number; // 0.5 to 3
  showDopplerOverlay: boolean;
  showCycloneVectors: boolean;
  showRiverBasins: boolean;
  showNdrfUnits: boolean;
  highFpsMode: boolean;

  // 2. Alerts, Siren Audio & Notifications
  audioAlertsEnabled: boolean;
  alertVolume: number; // 0.0 to 1.0
  sirenPattern: SirenPattern;
  minSeverityThreshold: SeverityThreshold;
  emergencyBroadcastPush: boolean;
  liveFeedToastEnabled: boolean;
  autoRefreshInterval: RefreshInterval;

  // 3. Telemetry Units & Formats
  tempUnit: TempUnit;
  windUnit: WindUnit;
  rainUnit: RainUnit;
  pressureUnit: PressureUnit;
  coordFormat: CoordFormat;
  timezone: TimezoneMode;

  // 4. Command HUD & Appearance
  themeMode: ThemeMode;
  uiDensity: UiDensity;
  glassmorphismEffects: boolean;
  reducedMotion: boolean;

  // 5. Network & Field Station Mode
  lowBandwidthDataSaver: boolean;
  offlineTileCaching: boolean;
  apiDataSource: 'live' | 'mock';

  // Metadata
  lastSavedAt: string;
}

export const DEFAULT_SETTINGS: IndraSettings = {
  // Map
  mapProjection: 'globe',
  defaultBasemap: 'satellite',
  globeAutoRotate: false,
  globeRotationSpeed: 1,
  showDopplerOverlay: true,
  showCycloneVectors: true,
  showRiverBasins: true,
  showNdrfUnits: true,
  highFpsMode: true,

  // Alerts & Audio
  audioAlertsEnabled: true,
  alertVolume: 0.75,
  sirenPattern: 'warble_fast',
  minSeverityThreshold: 'ALL',
  emergencyBroadcastPush: true,
  liveFeedToastEnabled: true,
  autoRefreshInterval: 15,

  // Units
  tempUnit: 'celsius',
  windUnit: 'kmh',
  rainUnit: 'mm',
  pressureUnit: 'hpa',
  coordFormat: 'dd',
  timezone: 'ist',

  // HUD
  themeMode: 'dark',
  uiDensity: 'standard',
  glassmorphismEffects: true,
  reducedMotion: false,

  // Network & Field
  lowBandwidthDataSaver: false,
  offlineTileCaching: true,
  apiDataSource: 'live',

  lastSavedAt: new Date().toISOString(),
};

// ==============================================================================
// Web Audio API Synthesizer (Zero-latency in-browser sirens & tactical chimes)
// ==============================================================================
let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  try {
    const AudioContextClass =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!audioCtx && AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  } catch {
    return null;
  }
}

/**
 * Synthesizes an emergency audible alert tone in the browser without external assets
 */
export function playAlertSound(pattern: SirenPattern = 'warble_fast', volume = 0.7) {
  const ctx = getAudioContext();
  if (!ctx) return;

  const now = ctx.currentTime;
  const masterGain = ctx.createGain();
  masterGain.gain.setValueAtTime(Math.max(0.01, Math.min(volume, 1)), now);
  masterGain.connect(ctx.destination);

  if (pattern === 'siren_continuous') {
    // Continuous rising & falling siren (440Hz -> 880Hz)
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(440, now);
    osc.frequency.linearRampToValueAtTime(880, now + 0.4);
    osc.frequency.linearRampToValueAtTime(440, now + 0.8);
    osc.frequency.linearRampToValueAtTime(880, now + 1.2);
    osc.frequency.linearRampToValueAtTime(440, now + 1.6);

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 1.7);

    osc.connect(gain);
    gain.connect(masterGain);
    osc.start(now);
    osc.stop(now + 1.7);
  } else if (pattern === 'warble_fast') {
    // Fast tactical emergency warble (Flash Flood / Critical Cyclone warning)
    const osc = ctx.createOscillator();
    osc.type = 'square';
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();

    lfo.frequency.setValueAtTime(8, now); // 8 Hz warble rate
    lfoGain.gain.setValueAtTime(150, now);
    lfo.connect(lfoGain);

    osc.frequency.setValueAtTime(750, now);
    lfoGain.connect(osc.frequency);

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 1.1);

    osc.connect(gain);
    gain.connect(masterGain);

    lfo.start(now);
    osc.start(now);
    lfo.stop(now + 1.1);
    osc.stop(now + 1.1);
  } else if (pattern === 'pulsed_beacon') {
    // 3 rapid tactical beeps (military/NDRF style alert)
    [0, 0.22, 0.44].forEach((offset) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(987.77, now + offset); // B5 note

      gain.gain.setValueAtTime(0.35, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.15);

      osc.connect(gain);
      gain.connect(masterGain);

      osc.start(now + offset);
      osc.stop(now + offset + 0.16);
    });
  } else {
    // chime_two_tone: Pleasant operational two-tone notification
    const notes = [
      { freq: 587.33, start: 0, dur: 0.2 }, // D5
      { freq: 880.0, start: 0.18, dur: 0.4 }, // A5
    ];
    notes.forEach((n) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(n.freq, now + n.start);

      gain.gain.setValueAtTime(0.3, now + n.start);
      gain.gain.exponentialRampToValueAtTime(0.001, now + n.start + n.dur);

      osc.connect(gain);
      gain.connect(masterGain);

      osc.start(now + n.start);
      osc.stop(now + n.start + n.dur);
    });
  }
}

// ==============================================================================
// Unit Formatting & Conversion Utilities
// ==============================================================================
export function formatTemperature(celsius: number, unit: TempUnit = 'celsius'): string {
  if (unit === 'fahrenheit') {
    const f = (celsius * 9) / 5 + 32;
    return `${f.toFixed(1)}°F`;
  }
  return `${celsius.toFixed(1)}°C`;
}

export function formatWindSpeed(kmh: number, unit: WindUnit = 'kmh'): string {
  if (unit === 'knots') {
    return `${(kmh * 0.539957).toFixed(0)} kt`;
  }
  if (unit === 'ms') {
    return `${(kmh / 3.6).toFixed(1)} m/s`;
  }
  return `${kmh.toFixed(0)} km/h`;
}

export function formatRainfall(mm: number, unit: RainUnit = 'mm'): string {
  if (unit === 'inches') {
    return `${(mm / 25.4).toFixed(2)} in`;
  }
  return `${mm.toFixed(1)} mm`;
}

export function formatCoordinates(lat: number, lng: number, format: CoordFormat = 'dd'): string {
  if (format === 'dms') {
    const latDir = lat >= 0 ? 'N' : 'S';
    const lngDir = lng >= 0 ? 'E' : 'W';
    const latAbs = Math.abs(lat);
    const lngAbs = Math.abs(lng);
    const latDeg = Math.floor(latAbs);
    const latMin = Math.floor((latAbs - latDeg) * 60);
    const latSec = Math.round(((latAbs - latDeg) * 60 - latMin) * 60);
    const lngDeg = Math.floor(lngAbs);
    const lngMin = Math.floor((lngAbs - lngDeg) * 60);
    const lngSec = Math.round(((lngAbs - lngDeg) * 60 - lngMin) * 60);
    return `${latDeg}°${latMin}'${latSec}"${latDir}, ${lngDeg}°${lngMin}'${lngSec}"${lngDir}`;
  }
  if (format === 'mgrs') {
    // Tactical grid approximate format for disaster ops
    const zone = Math.floor((lng + 180) / 6) + 1;
    return `${zone}R ${Math.abs(Math.round(lat * 1000)).toString().slice(0, 5)} ${Math.abs(Math.round(lng * 1000)).toString().slice(0, 5)}`;
  }
  return `${lat.toFixed(4)}° N, ${lng.toFixed(4)}° E`;
}

// ==============================================================================
// useSettings Hook with Cross-Tab Reactivity
// ==============================================================================
export function useSettings() {
  const [settings, setSettingsState] = useState<IndraSettings>(() => {
    if (typeof window === 'undefined') return DEFAULT_SETTINGS;
    try {
      const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (stored) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) };
      }
    } catch {
      // Fallback
    }
    return DEFAULT_SETTINGS;
  });

  // Sync to localStorage and broadcast event
  const updateSettings = useCallback(
    (newSettings: Partial<IndraSettings> | ((prev: IndraSettings) => Partial<IndraSettings>)) => {
      setSettingsState((prev) => {
        const patch = typeof newSettings === 'function' ? newSettings(prev) : newSettings;
        const merged: IndraSettings = {
          ...prev,
          ...patch,
          lastSavedAt: new Date().toISOString(),
        };

        try {
          localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(merged));
          window.dispatchEvent(new CustomEvent('indra-settings-change', { detail: merged }));
        } catch {
          // Quota or security error
        }

        return merged;
      });
    },
    []
  );

  const resetSettings = useCallback(() => {
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(DEFAULT_SETTINGS));
      window.dispatchEvent(new CustomEvent('indra-settings-change', { detail: DEFAULT_SETTINGS }));
    } catch {
      // ignore
    }
    setSettingsState(DEFAULT_SETTINGS);
  }, []);

  // Listen for changes from other tabs or components
  useEffect(() => {
    const handleCustomChange = (e: Event) => {
      const detail = (e as CustomEvent<IndraSettings>).detail;
      if (detail) {
        setSettingsState(detail);
      }
    };

    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === SETTINGS_STORAGE_KEY && e.newValue) {
        try {
          setSettingsState(JSON.parse(e.newValue));
        } catch {
          // ignore
        }
      }
    };

    window.addEventListener('indra-settings-change', handleCustomChange);
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('indra-settings-change', handleCustomChange);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  // Play test alarm wrapper
  const testAlarm = useCallback(
    (pattern?: SirenPattern) => {
      playAlertSound(pattern || settings.sirenPattern, settings.alertVolume);
    },
    [settings.sirenPattern, settings.alertVolume]
  );

  return {
    settings,
    updateSettings,
    resetSettings,
    testAlarm,
  };
}
