'use client';

/**
 * IdleLockOverlay
 *
 * Shows a full-screen lock overlay after the period specified in
 * settings.idleLockMinutes of inactivity. A single click / key-press
 * unlocks the session. No backend is involved; this is a UI-only guard
 * that prevents casual shoulder-surfing when the operator steps away.
 *
 * TODO(backend): A real session lock would call POST /api/auth/lock and
 * require re-authentication (password or OTP) to unlock.
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Lock, ShieldAlert } from 'lucide-react';
import { useSettings } from '@/lib/useSettings';

export default function IdleLockOverlay() {
  const { settings } = useSettings();
  const [locked, setLocked] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetTimer = useCallback(() => {
    if (settings.idleLockMinutes === 0) return; // disabled
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setLocked(true);
    }, settings.idleLockMinutes * 60 * 1000);
  }, [settings.idleLockMinutes]);

  // Start/restart timer whenever the setting changes or on mount
  useEffect(() => {
    if (settings.idleLockMinutes === 0) {
      setLocked(false);
      if (timerRef.current) clearTimeout(timerRef.current);
      return;
    }
    resetTimer();
    window.addEventListener('pointermove', resetTimer);
    window.addEventListener('pointerdown', resetTimer);
    window.addEventListener('keydown', resetTimer);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      window.removeEventListener('pointermove', resetTimer);
      window.removeEventListener('pointerdown', resetTimer);
      window.removeEventListener('keydown', resetTimer);
    };
  }, [settings.idleLockMinutes, resetTimer]);

  const unlock = () => {
    setLocked(false);
    resetTimer();
  };

  return (
    <AnimatePresence>
      {locked && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.35 }}
          className="fixed inset-0 z-[9999] flex flex-col items-center justify-center"
          style={{ background: 'rgba(10, 15, 30, 0.97)', backdropFilter: 'blur(12px)' }}
          onClick={unlock}
          onKeyDown={(e) => e.key === 'Enter' && unlock()}
          role="dialog"
          aria-modal="true"
          aria-label="Session locked"
          tabIndex={0}
        >
          <motion.div
            initial={{ scale: 0.85, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            transition={{ delay: 0.1, type: 'spring', damping: 20 }}
            className="flex flex-col items-center gap-5 select-none"
          >
            <div className="w-20 h-20 rounded-2xl bg-[#B5482E]/20 border border-[#B5482E]/40 flex items-center justify-center shadow-[0_0_40px_rgba(181,72,46,0.3)]">
              <Lock className="w-10 h-10 text-[#F97316]" />
            </div>

            <div className="text-center space-y-1">
              <p
                className="text-2xl font-bold text-white tracking-tight"
                style={{ fontFamily: 'Fraunces, Georgia, serif' }}
              >
                Session Locked
              </p>
              <p className="text-sm text-slate-400">
                Idle for {settings.idleLockMinutes} min — click anywhere to resume
              </p>
            </div>

            <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/[0.06] border border-white/10">
              <ShieldAlert className="w-4 h-4 text-[#F97316]" />
              <span className="text-xs font-mono text-slate-300">INDRA · SIH26069</span>
            </div>

            <p className="text-[11px] text-slate-600 font-mono mt-2">
              {/* TODO(backend): POST /api/auth/lock — require re-auth to unlock */}
              UI-only lock · no backend authentication
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
