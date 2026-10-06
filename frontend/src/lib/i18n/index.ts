// frontend/src/lib/i18n/index.ts
// Central barrel — imports all 12 locale dictionaries and exports the
// unified translations map used by useTranslation.ts

import type { SupportedLanguage, TranslationDict } from './types';
import { en } from './locales/en';
import { hi } from './locales/hi';
import { bn } from './locales/bn';
import { te } from './locales/te';
import { ta } from './locales/ta';
import { mr } from './locales/mr';
import { or } from './locales/or';
import { gu } from './locales/gu';
import { kn } from './locales/kn';
import { ml } from './locales/ml';
import { pa } from './locales/pa';
import { as } from './locales/as';
import { ur } from './locales/ur';

export const translations: Record<SupportedLanguage, TranslationDict> = {
  en, hi, bn, te, ta, mr, or, gu, kn, ml, pa, as, ur,
};

// Re-export everything so consumers only need to import from '@/lib/i18n'
export { en };
export type { SupportedLanguage, TranslationDict };
export { SUPPORTED_LANGUAGES } from './types';
export { LanguageProvider, useLanguageContext } from './LanguageContext';
export { useTranslation } from './useTranslation';
