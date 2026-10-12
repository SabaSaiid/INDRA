/**
 * INDRA Theme Registry
 * Central declarative registry for all five interface themes.
 */

export type ThemeId = 'dark' | 'light' | 'high_contrast' | 'monsoon' | 'night_watch';

export interface ThemeDefinition {
  id: ThemeId;
  label: string;
  description: string;
  colorScheme: 'light' | 'dark';
  defaultBasemap: 'satellite' | 'dark' | 'topo' | 'street';
  swatches: {
    rail: string;
    surface: string;
    brand: string;
    critical: string;
  };
}

export const THEME_REGISTRY: Record<ThemeId, ThemeDefinition> = {
  dark: {
    id: 'dark',
    label: 'Dark Ops',
    description: 'Storm-slate command rail with warm cartographic ground',
    colorScheme: 'light', // Content area is warm parchment ground
    defaultBasemap: 'satellite',
    swatches: {
      rail: '#182235',
      surface: '#F7F3EA',
      brand: '#B5482E',
      critical: '#8C2F26',
    },
  },
  light: {
    id: 'light',
    label: 'Light Parchment',
    description: 'Clean day parchment with soft rail and warm ground',
    colorScheme: 'light',
    defaultBasemap: 'topo',
    swatches: {
      rail: '#F0EBE0',
      surface: '#F7F3EA',
      brand: '#B5482E',
      critical: '#8C2F26',
    },
  },
  high_contrast: {
    id: 'high_contrast',
    label: 'Contrast',
    description: 'Sunlight glare field HUD with maximum edge definition',
    colorScheme: 'dark',
    defaultBasemap: 'street',
    swatches: {
      rail: '#000000',
      surface: '#0A0A0A',
      brand: '#FACC15',
      critical: '#EF4444',
    },
  },
  monsoon: {
    id: 'monsoon',
    label: 'Monsoon',
    description: 'Cool, airy daytime briefing with maritime teal accent',
    colorScheme: 'light',
    defaultBasemap: 'street',
    swatches: {
      rail: '#DDE7EA',
      surface: '#F7FAFB',
      brand: '#0B5C6B',
      critical: '#B42318',
    },
  },
  night_watch: {
    id: 'night_watch',
    label: 'Night Watch',
    description: 'Low-glare graphite night shift; hue strictly reserved for severity',
    colorScheme: 'dark',
    defaultBasemap: 'dark',
    swatches: {
      rail: '#101113',
      surface: '#141518',
      brand: '#E6E0D4',
      critical: '#FF6B5E',
    },
  },
};

export const DEFAULT_THEME_ID: ThemeId = 'dark';

export function isValidThemeId(id: string | null | undefined): id is ThemeId {
  return typeof id === 'string' && id in THEME_REGISTRY;
}

export function normalizeThemeId(id: string | null | undefined): ThemeId {
  return isValidThemeId(id) ? id : DEFAULT_THEME_ID;
}
