'use client';
// frontend/src/lib/i18n/useTranslation.ts
// The primary hook used by ALL React components to get translated strings.
// Usage:
//   const { t, language, setLanguage } = useTranslation();
//   t('nav.dashboard')           → "डैशबोर्ड"  (when language = 'hi')
//   t.hazard('URBAN_FLOOD')      → "शहरी बाढ़"
//   t.severity('CRITICAL')       → "अत्यधिक गंभीर"
//   t.status('AUTO_VERIFIED')    → "स्वतः सत्यापित"

import { useLanguageContext } from './LanguageContext';
import { translations } from './index';
import { en } from './locales/en';

function normalizeSeverity(raw?: string | null): string {
  if (!raw) return 'LOW';
  const u = raw.toUpperCase().trim();
  if (u === 'CRITICAL' || u === 'RED' || u === 'EXTREME') return 'CRITICAL';
  if (u === 'HIGH' || u === 'SEVERE' || u === 'ORANGE') return 'HIGH';
  if (u === 'MODERATE' || u === 'YELLOW') return 'MODERATE';
  if (u === 'LOW' || u === 'MINOR' || u === 'GREEN') return 'LOW';
  if (u === 'ADVISORY') return 'ADVISORY';
  return 'LOW';
}

function normalizeStatus(raw?: string | null): string {
  if (!raw) return 'QUARANTINED';
  const clean = raw.toUpperCase().replace(/[\s-]+/g, '_').trim();
  if (clean === 'AUTO_VERIFIED' || clean === 'AUTO_PUBLISHED' || clean === 'VERIFIED') return 'AUTO_VERIFIED';
  if (clean === 'PENDING_HUMAN_REVIEW' || clean === 'PENDING_REVIEW' || clean === 'UNDER_REVIEW') return 'PENDING_HUMAN_REVIEW';
  if (clean === 'QUARANTINED') return 'QUARANTINED';
  if (clean === 'HUMAN_APPROVED' || clean === 'APPROVED') return 'HUMAN_APPROVED';
  if (clean === 'HUMAN_REJECTED' || clean === 'REJECTED') return 'HUMAN_REJECTED';
  return 'QUARANTINED';
}

function normalizeHazard(raw?: string | null): string {
  if (!raw) return 'UNKNOWN';
  const clean = raw.toUpperCase().replace(/[\s-]+/g, '_').trim();
  if (clean in en.hazards) return clean;
  const lower = raw.toLowerCase();
  if (lower.includes('rain') || lower.includes('precipitation')) return 'HEAVY_RAIN';
  if (lower.includes('urban') || lower.includes('flood') || lower.includes('inundat') || lower.includes('waterlog')) return 'URBAN_FLOOD';
  if (lower.includes('thunder') || lower.includes('storm')) return 'THUNDERSTORM';
  if (lower.includes('cyclone') || lower.includes('gale') || lower.includes('wind')) return 'CYCLONE';
  if (lower.includes('heat')) return 'HEATWAVE';
  if (lower.includes('cold')) return 'COLDWAVE';
  if (lower.includes('dust')) return 'DUST_STORM';
  if (lower.includes('fog')) return 'FOG';
  if (lower.includes('landslide') || lower.includes('debris')) return 'LANDSLIDE';
  if (lower.includes('avalanche')) return 'AVALANCHE';
  if (lower.includes('earthquake') || lower.includes('tremor')) return 'EARTHQUAKE';
  if (lower.includes('tsunami')) return 'TSUNAMI';
  if (lower.includes('drought')) return 'DROUGHT';
  if (lower.includes('lightning')) return 'LIGHTNING';
  return 'UNKNOWN';
}

export function useTranslation() {
  const { language, setLanguage } = useLanguageContext();
  const dict = translations[language] ?? en;

  /** Type-safe dot-path lookup with English fallback */
  function t(keyPath: string): string {
    const keys = keyPath.split('.');

    // Try active language dict
    let result: unknown = dict;
    for (const k of keys) {
      result = (result as Record<string, unknown>)?.[k];
      if (result === undefined) break;
    }
    if (typeof result === 'string') return result;

    // Fallback: English
    let fallback: unknown = en;
    for (const k of keys) {
      fallback = (fallback as Record<string, unknown>)?.[k];
      if (fallback === undefined) break;
    }
    return typeof fallback === 'string' ? fallback : keyPath;
  }

  /** Hazard enum → localized string */
  t.hazard = (hazardType?: string | null) =>
    t(`hazards.${normalizeHazard(hazardType)}`);

  /** Severity enum → localized string */
  t.severity = (severityLevel?: string | null) =>
    t(`severity.${normalizeSeverity(severityLevel)}`);

  /** Review status enum → localized string */
  t.status = (reviewStatus?: string | null) =>
    t(`status.${normalizeStatus(reviewStatus)}`);

  return { t, language, setLanguage };
}

