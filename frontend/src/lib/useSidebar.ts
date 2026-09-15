'use client';

import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'indra_sidebar_collapsed';

export function useSidebar() {
  const [collapsed, setCollapsedState] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        return stored === 'true';
      }
      return window.innerWidth < 1024;
    } catch {
      return false;
    }
  });

  const [mobileOpen, setMobileOpen] = useState(false);

  // Set collapsed with localStorage sync & event dispatch
  const setCollapsed = useCallback((value: boolean | ((prev: boolean) => boolean)) => {
    setCollapsedState((prev) => {
      const next = typeof value === 'function' ? value(prev) : value;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
        window.dispatchEvent(new CustomEvent('indra-sidebar-change', { detail: next }));
      } catch {
        // ignore quota/security errors
      }
      return next;
    });
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, [setCollapsed]);

  // Sync across windows or components
  useEffect(() => {
    const handleCustomEvent = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail;
      if (typeof detail === 'boolean') {
        setCollapsedState(detail);
      }
    };

    const handleStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue !== null) {
        setCollapsedState(e.newValue === 'true');
      }
    };

    window.addEventListener('indra-sidebar-change', handleCustomEvent);
    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener('indra-sidebar-change', handleCustomEvent);
      window.removeEventListener('storage', handleStorage);
    };
  }, []);

  // Keyboard shortcut listener: '[' or Cmd+B / Ctrl+B
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }

      // Check for '[' or Cmd+B / Ctrl+B
      if (e.key === '[' || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b')) {
        e.preventDefault();
        toggle();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggle]);

  return {
    collapsed,
    setCollapsed,
    toggle,
    mobileOpen,
    setMobileOpen,
    openMobile: () => setMobileOpen(true),
    closeMobile: () => setMobileOpen(false),
  };
}
