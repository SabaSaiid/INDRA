'use client';
// frontend/src/lib/i18n/LanguageContext.tsx
// React Context that provides the active language and setter to the entire app.
// Wrap RootLayout's <body> with <LanguageProvider>.

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { SupportedLanguage } from './types';

const LANG_STORAGE_KEY = 'indra_user_language';
const DEFAULT_LANGUAGE: SupportedLanguage = 'en';

interface LanguageContextValue {
  language: SupportedLanguage;
  setLanguage: (lang: SupportedLanguage) => void;
}

export const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<SupportedLanguage>(DEFAULT_LANGUAGE);

  // Hydrate from localStorage on mount (client-only)
  useEffect(() => {
    try {
      const stored = localStorage.getItem(LANG_STORAGE_KEY) as SupportedLanguage | null;
      if (stored) setLanguageState(stored);
    } catch {
      // localStorage not available (SSR / privacy mode)
    }
  }, []);

  const setLanguage = useCallback((lang: SupportedLanguage) => {
    setLanguageState(lang);
    try {
      localStorage.setItem(LANG_STORAGE_KEY, lang);
      // Cross-tab sync
      window.dispatchEvent(new CustomEvent('indra-language-change', { detail: lang }));
    } catch {
      // ignore
    }
  }, []);

  // Cross-tab sync listener
  useEffect(() => {
    const handleChange = (e: Event) => {
      const lang = (e as CustomEvent<SupportedLanguage>).detail;
      if (lang) setLanguageState(lang);
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === LANG_STORAGE_KEY && e.newValue) {
        setLanguageState(e.newValue as SupportedLanguage);
      }
    };
    window.addEventListener('indra-language-change', handleChange);
    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener('indra-language-change', handleChange);
      window.removeEventListener('storage', handleStorage);
    };
  }, []);

  return (
    <LanguageContext.Provider value={{ language, setLanguage }}>
      {children}
    </LanguageContext.Provider>
  );
}

/** Internal hook — use `useTranslation` in components instead. */
export function useLanguageContext() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguageContext must be used within a LanguageProvider');
  return ctx;
}
