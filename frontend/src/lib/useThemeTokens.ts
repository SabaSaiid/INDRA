'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSettings, type ThemeMode } from './useSettings';
import { THEME_REGISTRY, normalizeThemeId, type ThemeId } from './theme-registry';

/**
 * Reads a CSS custom property from document.documentElement.
 * Handles space-separated RGB channels ("181 72 46") and formats as rgb(...).
 */
export function readCssToken(name: string, fallback = '#000000'): string {
  if (typeof window === 'undefined') return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  if (raw.includes(' ') && !raw.includes(',')) {
    return `rgb(${raw.split(/\s+/).join(', ')})`;
  }
  return raw;
}

export interface ResolvedThemeTokens {
  themeId: ThemeId;
  surfaceBg: string;
  surface: string;
  surfaceRaised: string;
  surfaceRail: string;
  border: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  brand: string;
  brandContrast: string;
  severity: {
    critical: string;
    high: string;
    moderate: string;
    advisory: string;
    low: string;
    unrated: string;
  };
  status: {
    verified: string;
    pending: string;
    quarantined: string;
  };
  hazard: Record<string, string>;
}

export function getResolvedThemeTokens(): ResolvedThemeTokens {
  if (typeof window === 'undefined') {
    return {
      themeId: 'dark',
      surfaceBg: '#F7F3EA',
      surface: '#FDFAF5',
      surfaceRaised: '#FFFFFF',
      surfaceRail: '#182235',
      border: '#E8E2D4',
      text: '#1E2A3B',
      textSecondary: '#4A5568',
      textMuted: '#7A8599',
      brand: '#B5482E',
      brandContrast: '#FFFFFF',
      severity: {
        critical: '#8C2F26',
        high: '#B8873A',
        moderate: '#4A6670',
        advisory: '#6B7280',
        low: '#6B7280',
        unrated: '#9CA3AF',
      },
      status: {
        verified: '#4C7A5B',
        pending: '#B8873A',
        quarantined: '#6B7280',
      },
      hazard: {
        rainfall: '#3E6B89',
        flood: '#2B727D',
        thunderstorm: '#525482',
        fog: '#5E6C7A',
        wind: '#3A6E6A',
        heatwave: '#8E4A6E',
        dust_storm: '#766A53',
      },
    };
  }

  const rawTheme = document.documentElement.getAttribute('data-theme');
  const themeId = normalizeThemeId(rawTheme);
  const isDarkScheme = THEME_REGISTRY[themeId]?.colorScheme === 'dark';

  const critical = readCssToken('--severity-critical', '#8C2F26');
  const high = readCssToken('--severity-high', '#B8873A');
  const moderate = readCssToken('--severity-moderate', '#4A6670');
  const low = readCssToken('--severity-low', '#6B7280');

  return {
    themeId,
    surfaceBg: readCssToken('--surface-bg', '#F7F3EA'),
    surface: readCssToken('--surface', '#FDFAF5'),
    surfaceRaised: readCssToken('--surface-raised', '#FFFFFF'),
    surfaceRail: readCssToken('--surface-rail', '#182235'),
    border: readCssToken('--border', '#E8E2D4'),
    text: readCssToken('--text', '#1E2A3B'),
    textSecondary: readCssToken('--text-secondary', '#4A5568'),
    textMuted: readCssToken('--text-muted', '#7A8599'),
    brand: readCssToken('--brand', '#B5482E'),
    brandContrast: readCssToken('--brand-contrast', '#FFFFFF'),
    severity: {
      critical,
      high,
      moderate,
      advisory: low,
      low,
      unrated: readCssToken('--text-subtle', '#9CA3AF'),
    },
    status: {
      verified: readCssToken('--status-verified', '#4C7A5B'),
      pending: readCssToken('--status-pending', '#B8873A'),
      quarantined: readCssToken('--status-quarantined', '#6B7280'),
    },
    // Categorical Hazard Palette (Option 1: Radiant Thermal Mauve & Desert Dune Khaki)
    hazard: {
      rainfall: isDarkScheme ? '#6BA3C7' : '#3E6B89',
      flood: isDarkScheme ? '#53A7B5' : '#2B727D',
      thunderstorm: isDarkScheme ? '#888BC4' : '#525482',
      fog: isDarkScheme ? '#9CA5B2' : '#5E6C7A',
      wind: isDarkScheme ? '#78A3A5' : '#3A6E6A',
      heatwave: isDarkScheme ? '#C47D9E' : '#8E4A6E',
      dust_storm: isDarkScheme ? '#A69C80' : '#766A53',
    },
  };
}

/**
 * React hook to bridge CSS variables and active theme into JavaScript/SVG contexts (Recharts, Canvas, WebGL).
 * Re-evaluates automatically whenever indra-settings-change or storage fires.
 */
export function useThemeTokens(): ResolvedThemeTokens {
  const { settings } = useSettings();
  const [tokens, setTokens] = useState<ResolvedThemeTokens>(getResolvedThemeTokens);

  const updateTokens = useCallback(() => {
    setTokens(getResolvedThemeTokens());
  }, []);

  useEffect(() => {
    updateTokens();

    const handleSettingsChange = () => {
      // Small tick to ensure DOM attribute and computed styles have applied
      requestAnimationFrame(updateTokens);
    };

    window.addEventListener('indra-settings-change', handleSettingsChange);
    window.addEventListener('storage', handleSettingsChange);

    return () => {
      window.removeEventListener('indra-settings-change', handleSettingsChange);
      window.removeEventListener('storage', handleSettingsChange);
    };
  }, [settings.themeMode, updateTokens]);

  return tokens;
}
