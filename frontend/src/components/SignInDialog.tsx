'use client';

import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, LogIn, Loader2, AlertTriangle } from 'lucide-react';
import { signIn, type Session } from '@/lib/auth';

interface Props {
  open: boolean;
  onClose: () => void;
  onSignedIn?: (session: Session) => void;
}

/**
 * Username and password for an operator account in the backend. The password
 * lives in this form's state until the request is sent, and is cleared when
 * the dialog closes.
 */
export default function SignInDialog({ open, onClose, onSignedIn }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  // Callers pass an inline onClose; a ref keeps a parent re-render from
  // re-running the open effect and wiping the error just shown.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) {
      setPassword('');
      return;
    }
    setError(null);
    usernameRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const session = await signIn(username.trim(), password);
      setPassword('');
      onSignedIn?.(session);
      onClose();
    } catch (err) {
      setPassword('');
      setError(err instanceof Error ? err.message : 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center p-4"
        onClick={onClose}
      >
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby="sign-in-title"
          initial={{ scale: 0.95, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.95, opacity: 0, y: 20 }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className="relative w-full max-w-sm bg-[#F7F3EA] rounded-2xl border border-[#E8E2D4] shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-5 py-4 border-b border-[#E8E2D4] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-[#26314A] flex items-center justify-center">
                <LogIn className="w-4 h-4 text-[#F7F3EA]" />
              </div>
              <div>
                <h2 id="sign-in-title" className="text-sm font-bold text-[#3C2415]">
                  Operator sign-in
                </h2>
                <p className="text-[10px] text-[#8C7A6B]">An account held by this INDRA backend</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[#E8E2D4] transition-colors"
              aria-label="Close sign-in"
            >
              <X className="w-4 h-4 text-[#8C7A6B]" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3.5">
            <div className="space-y-1.5">
              <label htmlFor="sign-in-username" className="text-xs font-semibold text-[#3C2415]">
                Username
              </label>
              <input
                id="sign-in-username"
                ref={usernameRef}
                type="text"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="sign-in-password" className="text-xs font-semibold text-[#3C2415]">
                Password
              </label>
              <input
                id="sign-in-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
              />
            </div>

            {error && (
              <p
                role="alert"
                className="flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs bg-red-50 text-red-800 border border-red-200"
              >
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                {error}
              </p>
            )}

            <div className="pt-1 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-[#6B5E53] hover:bg-[#E8E2D4] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy || !username.trim() || !password}
                className="px-4 py-2 rounded-lg bg-[#26314A] text-white text-xs font-semibold hover:bg-[#1B2436] transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <LogIn className="w-3.5 h-3.5" />}
                {busy ? 'Signing in…' : 'Sign in'}
              </button>
            </div>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
