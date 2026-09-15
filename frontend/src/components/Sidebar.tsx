'use client';

import React, { useState } from 'react';
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
} from 'lucide-react';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const sectionActionableBadges: Record<string, { label: string; variant: 'live' | 'critical' | 'neutral' }> = {
  tactical: { label: '18 ACTIVE', variant: 'live' },
  intelligence: { label: '4 CRIT', variant: 'critical' },
  command: { label: 'ON DUTY', variant: 'neutral' },
};

export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const pathname = usePathname();
  const { profile } = useOperatorProfile();

  // Collapsible section state initialized from localStorage
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => {
    if (typeof window === 'undefined') return {};
    try {
      const saved: Record<string, boolean> = {};
      ['tactical', 'intelligence', 'command'].forEach((id) => {
        saved[id] = localStorage.getItem(`indra_nav_section_${id}`) === 'true';
      });
      return saved;
    } catch {
      return {};
    }
  });

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

  // Active status matching (exact match for root '/', prefix for others)
  const isItemActive = (item: NavItem) => {
    if (item.href === '/') {
      return pathname === '/';
    }
    return pathname.startsWith(item.href);
  };

  const activeStatusCfg =
    dutyStatusConfig[profile.duty_status as DutyStatus] ||
    dutyStatusConfig.ON_DUTY;

  // Render a navigation item (used in both desktop and mobile drawer)
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
            'relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 outline-none',
            isCollapsedState ? 'justify-center px-2' : 'justify-between',
            isActive
              ? 'bg-gradient-to-r from-blue-600/25 via-blue-500/15 to-transparent text-white border border-blue-500/30 shadow-[0_0_15px_rgba(37,99,235,0.15)]'
              : 'text-slate-400 hover:text-slate-100 hover:bg-slate-850/60 border border-transparent'
          )}
          aria-current={isActive ? 'page' : undefined}
        >
          {/* Active indicator bar on the left */}
          {isActive && (
            <motion.div
              layoutId={isMobile ? 'mobile-sidebar-active-bar' : 'sidebar-active-bar'}
              className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-cyan-400 shadow-[0_0_8px_#38bdf8]"
              transition={{ type: 'spring', stiffness: 350, damping: 30 }}
            />
          )}

          {/* Left section: Icon + Label */}
          <div className="flex items-center gap-3 min-w-0 z-10">
            <div className="relative flex-shrink-0">
              <Icon
                className={cn(
                  'w-5 h-5 transition-transform duration-200 group-hover:scale-110',
                  isActive ? 'text-cyan-400' : 'text-slate-400 group-hover:text-slate-200'
                )}
              />

              {/* Collapsed mode micro-badge dot */}
              {isCollapsedState && item.badge && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 w-2 h-2 rounded-full ring-2 ring-slate-950',
                    item.badge.variant === 'live' && 'bg-emerald-400 animate-pulse',
                    item.badge.variant === 'critical' && 'bg-rose-500 animate-pulse',
                    item.badge.variant === 'warning' && 'bg-amber-400',
                    item.badge.variant === 'neutral' && 'bg-slate-400'
                  )}
                />
              )}
            </div>

            {/* Label (hidden in collapsed mode) — with robust truncation */}
            {!isCollapsedState && (
              <span
                title={item.label}
                className="truncate block text-[13px] font-medium tracking-wide"
              >
                {item.label}
              </span>
            )}
          </div>

          {/* Right section (Expanded only): EXACTLY ONE Trailing Element */}
          {!isCollapsedState && (
            <div className="flex items-center gap-1.5 flex-shrink-0 z-10 ml-auto pl-1">
              {item.badge ? (
                /* Priority 1: Status Badge */
                <span
                  className={cn(
                    'text-[10px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 leading-none shadow-sm',
                    item.badge.variant === 'live' &&
                      'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40',
                    item.badge.variant === 'critical' &&
                      'bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse',
                    item.badge.variant === 'warning' &&
                      'bg-amber-500/20 text-amber-300 border border-amber-500/40',
                    item.badge.variant === 'neutral' &&
                      'bg-slate-800 text-slate-400 border border-slate-700'
                  )}
                >
                  {item.badge.variant === 'live' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping inline-block" />
                  )}
                  {item.badge.text}
                </span>
              ) : item.shortcut ? (
                /* Priority 2: Dimmed Shortcut on Row Hover */
                <span className="text-[10px] font-mono text-slate-500 bg-slate-900/80 px-1.5 py-0.5 rounded border border-slate-800/80 opacity-50 group-hover:opacity-100 group-hover:text-slate-300 transition-opacity">
                  {item.shortcut}
                </span>
              ) : null}
            </div>
          )}
        </Link>

        {/* Floating tactical tooltip in collapsed mode */}
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
                    <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/70 border border-cyan-800/60 px-1.5 py-0.5 rounded">
                      {item.shortcut}
                    </span>
                  )}
                </div>

                {item.description && (
                  <p className="text-[11px] text-slate-400 leading-snug">
                    {item.description}
                  </p>
                )}

                {item.badge && (
                  <div className="pt-1 border-t border-slate-800 flex items-center justify-between text-[10px]">
                    <span className="text-slate-500 font-mono">STATUS</span>
                    <span
                      className={cn(
                        'font-semibold px-2 py-0.5 rounded-full flex items-center gap-1',
                        item.badge.variant === 'live' &&
                          'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40',
                        item.badge.variant === 'critical' &&
                          'bg-rose-500/20 text-rose-300 border border-rose-500/40',
                        item.badge.variant === 'warning' &&
                          'bg-amber-500/20 text-amber-300 border border-amber-500/40',
                        item.badge.variant === 'neutral' &&
                          'bg-slate-800 text-slate-400'
                      )}
                    >
                      {item.badge.variant === 'live' && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                      )}
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

  // Reusable Sidebar content body
  const sidebarBody = (isMobile = false) => {
    const isCollapsedState = collapsed && !isMobile;

    return (
      <div className="flex flex-col h-full select-none">
        {/* Brand Header — Aligned tightly with Topbar (h-16) */}
        <div
          className={cn(
            'flex items-center justify-between px-3.5 h-16 border-b border-slate-850/80 flex-shrink-0',
            isCollapsedState && 'justify-center px-2'
          )}
        >
          <Link href="/" className="flex items-center gap-3 group min-w-0">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 via-blue-500 to-indigo-700 flex items-center justify-center flex-shrink-0 shadow-[0_0_20px_rgba(37,99,235,0.4)] border border-blue-400/30 group-hover:scale-105 transition-transform duration-200">
              <CloudLightning className="w-4.5 h-4.5 text-white animate-pulse" />
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
                    <h1 className="text-white font-black text-base tracking-wider font-mono">
                      INDRA
                    </h1>
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                      v1.2
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping inline-block" />
                    <p className="text-emerald-400 font-mono text-[9px] font-semibold tracking-wide">
                      IMD GRID: ONLINE
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Link>

          {/* Anchored Sidebar Collapse Toggle (Desktop Header) */}
          {!isMobile && (
            <button
              onClick={onToggle}
              className={cn(
                'flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-850 border border-slate-800/80 transition-colors p-1.5',
                isCollapsedState ? 'hidden' : 'block'
              )}
              title="Collapse sidebar ( [ or ⌘B )"
              aria-label="Collapse sidebar"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Collapsed Expand Toggle Anchor */}
        {isCollapsedState && !isMobile && (
          <div className="pt-2 pb-1 px-2 flex justify-center flex-shrink-0">
            <button
              onClick={onToggle}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-850 border border-slate-800 transition-colors"
              title="Expand sidebar ( [ or ⌘B )"
              aria-label="Expand sidebar"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Quick Command shortcut trigger button */}
        {!isCollapsedState && (
          <div className="px-3 pt-2.5 pb-1 flex-shrink-0">
            <button
              onClick={() => {
                const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
                if (searchInput) searchInput.focus();
              }}
              className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-slate-900/80 hover:bg-slate-850 border border-slate-800 text-slate-400 hover:text-slate-200 text-xs transition-colors group"
            >
              <span className="flex items-center gap-2 font-mono text-[11px]">
                <Sparkles className="w-3.5 h-3.5 text-blue-400" />
                Quick Command...
              </span>
              <kbd className="text-[10px] font-mono bg-slate-800/80 px-1.5 py-0.5 rounded border border-slate-700 text-slate-400 group-hover:text-slate-300">
                ⌘K
              </kbd>
            </button>
          </div>
        )}

        {/* Grouped Navigation — Independent Scrollable Region */}
        <div
          className={cn(
            'min-h-0 flex-1 px-3 py-2 space-y-3',
            isCollapsedState
              ? 'overflow-visible'
              : 'overflow-y-auto overflow-x-hidden scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent'
          )}
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
                {/* Section Header with Collapsible Toggle & Actionable Badges */}
                {!isCollapsedState ? (
                  <button
                    onClick={() => toggleSection(section.id)}
                    className="w-full px-2 pt-2 pb-1 flex items-center justify-between text-[10px] font-mono tracking-widest text-slate-500 uppercase font-semibold hover:text-slate-300 transition-colors group/sec text-left"
                    title={isSectionCollapsed ? `Expand ${section.label}` : `Collapse ${section.label}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <ChevronDown
                        className={cn(
                          'w-3 h-3 text-slate-500 transition-transform duration-200 group-hover/sec:text-slate-300',
                          isSectionCollapsed && '-rotate-90'
                        )}
                      />
                      <span>{section.label}</span>
                    </div>
                    {badgeCfg && (
                      <span
                        className={cn(
                          'text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded-full border leading-none',
                          badgeCfg.variant === 'live' &&
                            'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
                          badgeCfg.variant === 'critical' &&
                            'bg-rose-500/15 text-rose-400 border-rose-500/30 animate-pulse',
                          badgeCfg.variant === 'neutral' &&
                            'bg-slate-800 text-slate-400 border-slate-700'
                        )}
                      >
                        {badgeCfg.label}
                      </span>
                    )}
                  </button>
                ) : (
                  <div className="h-[1px] bg-slate-800/70 mx-2 my-2" />
                )}

                {/* Section Items */}
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

        {/* Tactical Footer: Operator Identity & Readiness */}
        <div
          className={cn(
            'p-3 border-t border-slate-850/85 bg-slate-950/60 mt-auto flex-shrink-0',
            isCollapsedState && 'px-2'
          )}
        >
          {/* Sector Command Context Label */}
          {!isCollapsedState && (
            <div className="flex items-center justify-between px-1 mb-1.5">
              <span className="text-[9px] font-mono font-semibold tracking-wider text-slate-500 uppercase">
                Sector Command
              </span>
              <span className="text-[9px] font-mono text-cyan-400">
                {profile.callsign}
              </span>
            </div>
          )}

          {/* Operator Profile Card */}
          <div className="relative group">
            <Link
              href="/profile"
              onClick={isMobile ? onMobileClose : undefined}
              className={cn(
                'flex items-center gap-3 p-2 rounded-xl transition-all duration-200 outline-none',
                'bg-slate-900/60 hover:bg-slate-850 border border-slate-800/80 hover:border-slate-700',
                isCollapsedState && 'justify-center p-1.5'
              )}
            >
              {/* Operator Avatar with Duty Dot */}
              <div className="relative flex-shrink-0">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-700 via-indigo-600 to-cyan-600 text-white font-bold text-xs flex items-center justify-center shadow-md">
                  {profile.avatar_initials}
                </div>
                <span
                  className={cn(
                    'absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-slate-950',
                    activeStatusCfg.dot
                  )}
                />
              </div>

              {/* Operator Info (Expanded) */}
              {!isCollapsedState && (
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-white truncate" title={profile.full_name}>
                      {profile.full_name}
                    </p>
                    <ExternalLink className="w-3 h-3 text-slate-500 group-hover:text-blue-400 transition-colors shrink-0 ml-1" />
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-400 truncate">
                    <span className="truncate">
                      {profile.team_name ? profile.team_name.split('—')[0].trim() : profile.agency}
                    </span>
                  </div>
                </div>
              )}
            </Link>

            {/* Collapsed Operator Tooltip */}
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
                      <span className="font-semibold text-xs text-white">
                        {profile.full_name}
                      </span>
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        {profile.duty_status.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="text-[10px] font-mono text-cyan-400">
                      Callsign: {profile.callsign}
                    </p>
                    <p className="text-[10px] text-slate-400">
                      {profile.team_name}
                    </p>
                    <div className="pt-1.5 border-t border-slate-800 text-[10px] text-blue-400 font-medium flex items-center gap-1">
                      <span>Click to open operator dossier</span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Operational Status Bar — Sober Disaster-Ops Phrasing */}
          {!isCollapsedState && (
            <div className="mt-2.5 pt-2 border-t border-slate-850 flex items-center justify-between text-[10px] font-mono text-slate-400">
              <span className="flex items-center gap-1.5 text-amber-400">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                Sector Status: Active
              </span>
              <span className="text-slate-500">IMD • NDRF</span>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      {/* Desktop Persistent Tactical Sidebar (280px expanded for ample breathing room) */}
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 72 : 280 }}
        transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
        className={cn(
          'fixed left-0 top-0 h-screen z-40',
          'hidden md:flex flex-col',
          'bg-slate-950/95 backdrop-blur-xl border-r border-slate-850 shadow-[4px_0_24px_rgba(0,0,0,0.45)]'
        )}
      >
        {/* Subtle Right Edge Illumination Accent */}
        <div className="pointer-events-none absolute inset-y-0 right-0 w-[1px] bg-gradient-to-b from-blue-500/0 via-blue-500/25 to-blue-500/0" />

        {sidebarBody(false)}
      </motion.aside>

      {/* Mobile Slide-in Drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden"
              onClick={onMobileClose}
            />
            <motion.aside
              initial={{ x: -290 }}
              animate={{ x: 0 }}
              exit={{ x: -290 }}
              transition={{ type: 'spring', stiffness: 320, damping: 32 }}
              className="fixed left-0 top-0 h-screen w-[290px] z-50 md:hidden bg-slate-950 border-r border-slate-800 shadow-2xl"
            >
              <button
                onClick={onMobileClose}
                className="absolute right-3 top-4 w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400 hover:text-white transition-colors"
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
