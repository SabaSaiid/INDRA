'use client';
// frontend/src/components/LanguagePicker.tsx
// Globe icon dropdown — shows the active language in its native script.
// Drop-in for Topbar.tsx between the notification cluster and profile pill.

import React, { useState, useRef, useEffect } from 'react';
import { Globe, Check } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { SUPPORTED_LANGUAGES } from '@/lib/i18n/types';
import type { SupportedLanguage } from '@/lib/i18n/types';
import { cn } from '@/lib/utils';

export default function LanguagePicker() {
  const { language, setLanguage } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Click-away close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const activeLang = SUPPORTED_LANGUAGES[language];

  return (
    <div className="relative" ref={ref}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          'flex items-center gap-1.5 h-8 px-2.5 rounded-lg text-xs font-medium transition-all',
          'border focus:outline-none focus:ring-1 focus:ring-[#B5482E]/30',
          open
            ? 'bg-[#F0EBE0] border-[#D8D0C4] text-ink'
            : 'bg-[#F0EBE0]/60 border-[#E8E2D4] text-[#7A8599] hover:text-ink hover:bg-[#F0EBE0]'
        )}
        aria-label="Select language"
        aria-expanded={open}
        title="Change interface language"
        id="language-picker-btn"
      >
        <Globe className="w-3.5 h-3.5 flex-shrink-0" />
        <span
          className="hidden sm:inline max-w-[72px] truncate leading-none"
          style={{ fontFamily: activeLang.fontFamily }}
        >
          {activeLang.nativeName}
        </span>
      </button>

      {/* Dropdown */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.97 }}
            transition={{ duration: 0.13, ease: 'easeOut' }}
            className="absolute right-0 mt-2 w-52 rounded-xl border border-[#E8E2D4] shadow-xl z-50 overflow-hidden"
            style={{ background: '#FDFAF5' }}
          >
            {/* Header */}
            <div className="px-3 py-2 border-b border-[#E8E2D4]" style={{ background: '#F7F3EA' }}>
              <p className="text-[10px] font-semibold tracking-wider uppercase text-[#7A8599] flex items-center gap-1.5">
                <Globe className="w-3 h-3" />
                Interface Language
              </p>
            </div>

            {/* Language list */}
            <div className="py-1 max-h-72 overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
              {(Object.entries(SUPPORTED_LANGUAGES) as [SupportedLanguage, typeof SUPPORTED_LANGUAGES[SupportedLanguage]][]).map(
                ([code, meta]) => {
                  const isActive = language === code;
                  return (
                    <button
                      key={code}
                      onClick={() => { setLanguage(code); setOpen(false); }}
                      className={cn(
                        'w-full flex items-center justify-between px-3 py-1.5 text-left transition-colors',
                        isActive
                          ? 'bg-[#B5482E]/8 text-[#B5482E]'
                          : 'text-[#4A5568] hover:bg-[#F0EBE0]'
                      )}
                    >
                      <div className="flex flex-col min-w-0">
                        <span
                          className={cn('text-sm leading-snug truncate', isActive && 'font-semibold')}
                          style={{ fontFamily: meta.fontFamily }}
                        >
                          {meta.nativeName}
                        </span>
                        <span className="text-[10px] text-[#7A8599] font-medium">{meta.name}</span>
                      </div>
                      {isActive && <Check className="w-3.5 h-3.5 text-[#B5482E] flex-shrink-0" />}
                    </button>
                  );
                }
              )}
            </div>

            {/* Footer note */}
            <div
              className="px-3 py-1.5 border-t border-[#E8E2D4] text-[10px] text-[#7A8599] text-center"
              style={{ background: '#F7F3EA' }}
            >
              Selection persists across sessions
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
