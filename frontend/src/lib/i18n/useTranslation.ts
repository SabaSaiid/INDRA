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
    t(`hazards.${hazardType ?? 'UNKNOWN'}`);

  /** Severity enum → localized string */
  t.severity = (severityLevel?: string | null) =>
    t(`severity.${severityLevel ?? 'LOW'}`);

  /** Review status enum → localized string */
  t.status = (reviewStatus?: string | null) =>
    t(`status.${reviewStatus ?? 'QUARANTINED'}`);

  return { t, language, setLanguage };
}
