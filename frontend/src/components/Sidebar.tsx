'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import {
  navItems,
  navSections,
  dutyStatusConfig,
  type NavItem,
  type DutyStatus,
} from '@/lib/mock-data';
import { useOperatorProfile } from '@/lib/useOperatorProfile';
import {
  CloudLightning,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  X,
  ExternalLink,
  Sparkles,
  Settings,
} from 'lucide-react';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

// Status badge per section header (counts only, high-contrast tactical styling)
const sectionActionableBadges: Record<string, { label: string; variant: 'live' | 'alert' | 'neutral' }> = {
  tactical: { label: '18 active', variant: 'live' },
  intelligence: { label: '4 crit', variant: 'alert' },
  command: { label: 'on duty', variant: 'neutral' },
};

export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const pathname = usePathname();
  const { profile } = useOperatorProfile();

  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const saved: Record<string, boolean> = {};
      ['tactical', 'intelligence', 'command'].forEach((id) => {
        saved[id] = localStorage.getItem(`indra_nav_section_${id}`) === 'true';
      });
      setCollapsedSections(saved);
    } catch {
      // ignore storage errors
    }
  }, []);

  const toggleSection = (sectionId: string) => {
    setCollapsedSections((prev) => {
      const nextVal = !prev[sectionId];
      try {
        localStorage.setItem(`indra_nav_section_${sectionId}`, String(nextVal));
      } catch {
        // ignore storage errors
      }
      return { ...prev, [sectionId]: nextVal };
    });
  };

  const isItemActive = (item: NavItem) => {
    if (item.href === '/') return pathname === '/';
    return pathname.startsWith(item.href);
  };

  const activeStatusCfg =
    dutyStatusConfig[profile.duty_status as DutyStatus] ||
    dutyStatusConfig.ON_DUTY;

  // ── Nav item renderer ───────────────────────────────────────────────────────
  const renderNavItem = (item: NavItem, isMobile = false) => {
    const isActive = isItemActive(item);
    const Icon = item.icon;
    const isCollapsedState = collapsed && !isMobile;

    return (
      <div key={item.id} className="relative group">
        <Link
          href={item.href}
          onClick={isMobile ? onMobileClose : undefined}
          title={item.label}
          className={cn(
            'relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 outline-none select-none',
            isCollapsedState ? 'justify-center px-2' : 'justify-between',
            isActive
              ? 'text-white bg-white/[0.12] border border-white/[0.15] shadow-sm'
              : 'text-slate-300 hover:text-white hover:bg-white/[0.08]'
          )}
          aria-current={isActive ? 'page' : undefined}
        >
          {/* Terracotta active spine with glow */}
          {isActive && (
            <motion.div
              layoutId={isMobile ? 'mobile-sidebar-active-bar' : 'sidebar-active-bar'}
              className="absolute left-0 top-1.5 bottom-1.5 w-[3.5px] rounded-r-full bg-[#E05D38] shadow-[0_0_10px_rgba(224,93,56,0.65)]"
              transition={{ type: 'spring', stiffness: 350, damping: 30 }}
            />
          )}

          {/* Icon + label */}
          <div className="flex items-center gap-3 min-w-0 z-10">
            <div className="relative flex-shrink-0">
              <Icon
                className={cn(
                  'w-5 h-5 transition-transform duration-200 group-hover:scale-105',
                  isActive
                    ? 'text-white drop-shadow-[0_0_6px_rgba(255,255,255,0.4)]'
                    : 'text-slate-400 group-hover:text-white'
                )}
              />
              {/* Collapsed micro-badge dot */}
              {isCollapsedState && item.badge && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full ring-2 ring-[#182235]',
                    item.badge.variant === 'live' && 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]',
                    item.badge.variant === 'critical' && 'bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.8)]',
                    item.badge.variant === 'warning' && 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.8)]',
                    item.badge.variant === 'neutral' && 'bg-slate-400'
                  )}
                />
              )}
            </div>

            {!isCollapsedState && (
              <span
                title={item.label}
                className={cn(
                  'truncate block text-[13.5px]',
                  isActive ? 'font-semibold text-white' : 'font-medium text-slate-200 group-hover:text-white'
                )}
              >
                {item.label}
              </span>
            )}
          </div>

          {/* Trailing — badge or shortcut */}
          {!isCollapsedState && (
            <div className="flex items-center gap-1.5 flex-shrink-0 z-10 ml-auto pl-1">
              {item.badge ? (
                <span
                  className={cn(
                    'text-[10px] font-semibold px-2 py-0.5 rounded leading-none border transition-colors',
                    item.badge.variant === 'live'
                      && 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_8px_rgba(16,185,129,0.2)]',
                    item.badge.variant === 'critical'
                      && 'bg-rose-500/25 text-rose-200 border-rose-500/50 shadow-[0_0_8px_rgba(244,63,94,0.3)] animate-pulse',
                    item.badge.variant === 'warning'
                      && 'bg-amber-500/20 text-amber-300 border-amber-500/40',
                    item.badge.variant === 'neutral'
                      && 'bg-slate-700/60 text-slate-300 border-slate-600/50'
                  )}
                >
                  {item.badge.text}
                </span>
              ) : item.shortcut ? (
                <kbd
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-400 bg-white/[0.06] border border-white/10 group-hover:text-slate-200 group-hover:border-white/20 transition-all"
                >
                  {item.shortcut}
                </kbd>
              ) : null}
            </div>
          )}
        </Link>

        {/* Floating tooltip in collapsed mode */}
        {isCollapsedState && (
          <div
            className={cn(
              'absolute left-full top-1/2 -translate-y-1/2 ml-3 z-50 pointer-events-none',
              'transition-all duration-150 origin-left',
              'opacity-0 scale-95 -translate-x-1',
              'group-hover:opacity-100 group-hover:scale-100 group-hover:translate-x-0'
            )}
          >
            <div className="bg-slate-900/95 backdrop-blur-md text-white border border-slate-700/80 rounded-xl p-3 shadow-2xl min-w-[210px] max-w-[260px] relative">
              <div className="absolute -left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 bg-slate-900 border-l border-b border-slate-700/80 transform rotate-45" />

              <div className="relative z-10 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-xs text-white">
                    {item.label}
                  </span>
                  {item.shortcut && (
                    <span className="text-[10px] font-mono text-slate-300 px-1.5 py-0.5 rounded bg-white/10 border border-white/15">
                      {item.shortcut}
                    </span>
                  )}
                </div>

                {item.description && (
                  <p className="text-[11px] leading-snug text-slate-300">
                    {item.description}
                  </p>
                )}

                {item.badge && (
                  <div className="pt-1.5 border-t border-slate-800 flex items-center justify-between text-[10px]">
                    <span className="text-slate-400 font-medium">STATUS</span>
                    <span
                      className={cn(
                        'font-semibold px-1.5 py-0.5 rounded text-[9px]',
                        item.badge.variant === 'live' && 'bg-emerald-500/20 text-emerald-300',
                        item.badge.variant === 'critical' && 'bg-rose-500/25 text-rose-300',
                        item.badge.variant === 'warning' && 'bg-amber-500/20 text-amber-300',
                        item.badge.variant === 'neutral' && 'bg-slate-700 text-slate-300'
                      )}
                    >
                      {item.badge.text}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  // ── Sidebar body ────────────────────────────────────────────────────────────
  const sidebarBody = (isMobile = false) => {
    const isCollapsedState = collapsed && !isMobile;

    return (
      <div className="flex flex-col h-full select-none">
        {/* Brand header — aligns with topbar h-16 */}
        <div
          className={cn(
            'flex items-center justify-between px-3.5 h-16 border-b border-white/10 flex-shrink-0',
            isCollapsedState && 'justify-center px-2'
          )}
        >
          <Link href="/" className="flex items-center gap-3 group min-w-0">
            {/* Brand mark — glowing terracotta lightning */}
            <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 bg-[#B5482E]/25 border border-[#B5482E]/50 shadow-[0_0_12px_rgba(181,72,46,0.35)] group-hover:scale-105 group-hover:border-[#B5482E]/80 transition-all duration-200">
              <CloudLightning className="w-5 h-5 text-[#F97316]" />
            </div>

            <AnimatePresence mode="wait">
              {!isCollapsedState && (
                <motion.div
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: 'auto' }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden whitespace-nowrap min-w-0"
                >
                  <div className="flex items-center gap-2">
                    <h1
                      className="text-white font-bold text-base tracking-wide"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      INDRA
                    </h1>
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/10 text-slate-300 border border-white/15">
                      v1.2
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)] animate-pulse inline-block" />
                    <p className="text-[10px] font-medium text-emerald-400">
                      Grid live
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Link>

          {/* Collapse toggle */}
          {!isMobile && (
            <button
              onClick={onToggle}
              className={cn(
                'flex items-center justify-center rounded-md transition-colors p-1.5',
                'text-slate-400 hover:text-white hover:bg-white/10',
                'border border-white/15',
                isCollapsedState ? 'hidden' : 'block'
              )}
              title="Collapse sidebar ( [ or ⌘B )"
              aria-label="Collapse sidebar"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Collapsed expand button */}
        {isCollapsedState && !isMobile && (
          <div className="pt-2 pb-1 px-2 flex justify-center flex-shrink-0">
            <button
              onClick={onToggle}
              className="p-1.5 rounded-md transition-colors border border-white/15 text-slate-400 hover:text-white hover:bg-white/10"
              title="Expand sidebar"
              aria-label="Expand sidebar"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Quick command button */}
        {!isCollapsedState && (
          <div className="px-3 pt-3 pb-1 flex-shrink-0">
            <button
              onClick={() => {
                const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
                if (searchInput) searchInput.focus();
              }}
              className="w-full flex items-center justify-between px-3 py-2 rounded-lg transition-all group border border-white/15 bg-white/[0.07] hover:bg-white/[0.12] hover:border-white/30 text-slate-300 hover:text-white shadow-sm"
            >
              <span className="flex items-center gap-2 text-[11.5px] font-medium">
                <Sparkles className="w-3.5 h-3.5 text-[#F97316] group-hover:scale-110 transition-transform" />
                Quick command…
              </span>
              <kbd className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/10 border border-white/20 text-slate-300">
                ⌘K
              </kbd>
            </button>
          </div>
        )}

        {/* Navigation */}
        <div
          className={cn(
            'min-h-0 flex-1 px-3 py-2 space-y-3',
            isCollapsedState
              ? 'overflow-visible'
              : 'overflow-y-auto overflow-x-hidden'
          )}
          style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.15) transparent' }}
        >
          {navSections.map((section) => {
            const sectionItems = navItems.filter(
              (item) => item.section === section.id
            );
            if (sectionItems.length === 0) return null;

            const isSectionCollapsed = !!collapsedSections[section.id];
            const badgeCfg = sectionActionableBadges[section.id];

            return (
              <div key={section.id} className="space-y-1">
                {/* Section header */}
                {!isCollapsedState ? (
                  <button
                    onClick={() => toggleSection(section.id)}
                    className="w-full px-2 pt-2.5 pb-1 flex items-center justify-between text-[11px] font-semibold tracking-wider uppercase text-slate-400 hover:text-slate-200 transition-colors group/sec text-left"
                    title={isSectionCollapsed ? `Expand ${section.label}` : `Collapse ${section.label}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <ChevronDown
                        className={cn(
                          'w-3.5 h-3.5 transition-transform duration-200 text-slate-400 group-hover/sec:text-slate-200',
                          isSectionCollapsed && '-rotate-90'
                        )}
                      />
                      <span className="transition-colors">
                        {section.label}
                      </span>
                    </div>
                    {badgeCfg && (
                      <span
                        className={cn(
                          'text-[9px] font-semibold font-mono px-1.5 py-0.5 rounded border leading-none',
                          badgeCfg.variant === 'live' && 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
                          badgeCfg.variant === 'alert' && 'bg-rose-500/20 text-rose-300 border-rose-500/40',
                          badgeCfg.variant === 'neutral' && 'bg-slate-700/50 text-slate-300 border-slate-600/50'
                        )}
                      >
                        {badgeCfg.label}
                      </span>
                    )}
                  </button>
                ) : (
                  <div className="h-px mx-2 my-2 bg-white/10" />
                )}

                <AnimatePresence initial={false}>
                  {(!isSectionCollapsed || isCollapsedState) && (
                    <motion.div
                      initial={isCollapsedState ? false : { opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.18 }}
                      className="space-y-1 overflow-hidden"
                    >
                      {sectionItems.map((item) => renderNavItem(item, isMobile))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>

        {/* Footer — operator identity */}
        <div
          className={cn(
            'p-3 border-t border-white/10 mt-auto flex-shrink-0 bg-black/25',
            isCollapsedState && 'px-2'
          )}
        >
          {/* Sector label */}
          {!isCollapsedState && (
            <div className="flex items-center justify-between px-1 mb-1.5">
              <span className="text-[10px] font-semibold tracking-wider uppercase text-slate-400">
                Operator
              </span>
              <span
                className="text-[10px] font-mono font-bold text-[#F97316] bg-[#B5482E]/15 border border-[#B5482E]/30 px-1.5 py-0.2 rounded"
                suppressHydrationWarning
              >
                {profile.callsign}
              </span>
            </div>
          )}

          {/* Profile card */}
          <div className="relative group">
            <Link
              href="/profile"
              onClick={isMobile ? onMobileClose : undefined}
              className={cn(
                'flex items-center gap-3 p-2 rounded-lg transition-all duration-200 outline-none border border-white/10 bg-white/[0.05] hover:bg-white/[0.10] hover:border-white/20',
                isCollapsedState && 'justify-center p-1.5'
              )}
            >
              {/* Avatar with duty dot */}
              <div className="relative flex-shrink-0">
                <div
                  className="w-8 h-8 rounded-md text-white font-bold text-xs flex items-center justify-center bg-[#B5482E]/40 border border-[#B5482E]/50 shadow-sm"
                  suppressHydrationWarning
                >
                  {profile.avatar_initials}
                </div>
                <span
                  className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-[#182235]"
                  style={{ backgroundColor: activeStatusCfg.dot }}
                />
              </div>

              {/* Name (expanded) */}
              {!isCollapsedState && (
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <p
                      className="text-xs font-semibold text-white truncate"
                      title={profile.full_name}
                      suppressHydrationWarning
                    >
                      {profile.full_name}
                    </p>
                    <ExternalLink className="w-3 h-3 flex-shrink-0 ml-1 text-slate-400 group-hover:text-white transition-colors" />
                  </div>
                  <div className="flex items-center gap-1.5 text-[10.5px] text-slate-400 truncate">
                    <span className="truncate" suppressHydrationWarning>
                      {profile.team_name ? profile.team_name.split('—')[0].trim() : profile.agency}
                    </span>
                  </div>
                </div>
              )}
            </Link>

            {/* Collapsed operator tooltip */}
            {isCollapsedState && (
              <div
                className={cn(
                  'absolute left-full bottom-0 ml-3 z-50 pointer-events-none',
                  'transition-all duration-150 origin-left',
                  'opacity-0 scale-95 -translate-x-1 group-hover:opacity-100 group-hover:scale-100 group-hover:translate-x-0'
                )}
              >
                <div className="bg-slate-900/95 backdrop-blur-md text-white border border-slate-700/80 rounded-xl p-3 shadow-2xl min-w-[210px] relative">
                  <div className="absolute -left-1.5 bottom-3 w-3 h-3 bg-slate-900 border-l border-b border-slate-700/80 transform rotate-45" />
                  <div className="relative z-10 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-xs text-white" suppressHydrationWarning>
                        {profile.full_name}
                      </span>
                      <span
                        className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                        suppressHydrationWarning
                      >
                        {profile.duty_status.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="text-[10px] font-mono text-[#F97316] font-bold" suppressHydrationWarning>
                      {profile.callsign}
                    </p>
                    <p className="text-[10px] text-slate-300" suppressHydrationWarning>
                      {profile.team_name}
                    </p>
                    <div className="pt-1.5 border-t border-slate-800 text-[10px] text-slate-300 font-medium flex items-center gap-1">
                      <span>Open operator dossier</span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Status bar */}
          {!isCollapsedState && (
            <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center justify-between text-[10.5px] font-medium text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.8)] animate-pulse" />
                <span className="text-amber-300 font-medium">Sector active</span>
              </span>
              <Link
                href="/settings"
                onClick={isMobile ? onMobileClose : undefined}
                className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
                title="Platform Settings (⌘,)"
              >
                <Settings className="w-3.5 h-3.5 hover:rotate-45 transition-transform" />
                <span>Settings</span>
              </Link>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      {/* Desktop sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 72 : 280 }}
        transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
        className={cn(
          'fixed left-0 top-0 h-screen z-40',
          'hidden md:flex flex-col',
          'border-r'
        )}
        style={{
          background: 'linear-gradient(180deg, #182235 0%, #111827 100%)',
          borderColor: 'rgba(255, 255, 255, 0.10)',
        }}
      >
        {sidebarBody(false)}
      </motion.aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 md:hidden bg-black/60 backdrop-blur-sm"
              onClick={onMobileClose}
            />
            <motion.aside
              initial={{ x: -290 }}
              animate={{ x: 0 }}
              exit={{ x: -290 }}
              transition={{ type: 'spring', stiffness: 320, damping: 32 }}
              className="fixed left-0 top-0 h-screen w-[290px] z-50 md:hidden border-r"
              style={{
                background: 'linear-gradient(180deg, #182235 0%, #111827 100%)',
                borderColor: 'rgba(255, 255, 255, 0.10)',
              }}
            >
              <button
                onClick={onMobileClose}
                className="absolute right-3 top-4 w-8 h-8 rounded-lg border border-white/15 bg-white/10 flex items-center justify-center text-slate-300 hover:text-white transition-colors"
                aria-label="Close menu"
              >
                <X className="w-4 h-4" />
              </button>
              {sidebarBody(true)}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
