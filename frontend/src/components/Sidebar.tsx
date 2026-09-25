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
  PLACEHOLDER_OPERATOR,
} from '@/lib/ui-config';
import { useOperatorProfile, AVAILABLE_OPERATOR_PERSONAS } from '@/lib/useOperatorProfile';
import {
  CloudLightning,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  X,
  Settings,
} from 'lucide-react';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const pathname = usePathname();
  const { profile: loadedProfile, selectedRole } = useOperatorProfile();
  const rawProfile = loadedProfile ?? PLACEHOLDER_OPERATOR;
  const currentPersona = AVAILABLE_OPERATOR_PERSONAS.find((p) => p.id === selectedRole) || AVAILABLE_OPERATOR_PERSONAS[0];

  const profile = {
    ...rawProfile,
    full_name: (rawProfile.full_name && rawProfile.full_name !== 'Operator unavailable' && rawProfile.full_name !== '—')
      ? (rawProfile.full_name === 'Incident Commander' ? currentPersona.name : rawProfile.full_name)
      : currentPersona.name,
    avatar_initials: (rawProfile.avatar_initials && rawProfile.avatar_initials !== '—')
      ? rawProfile.avatar_initials
      : currentPersona.avatar,
    agency: (rawProfile.agency && rawProfile.agency !== '—')
      ? (rawProfile.agency === 'SDMA_BIHAR' ? 'SEOC Bihar / NDMA' : rawProfile.agency.replace(/_/g, ' '))
      : currentPersona.agency,
    callsign: (rawProfile.callsign && rawProfile.callsign !== '—')
      ? rawProfile.callsign
      : (selectedRole === 'commander' ? 'PATNA-ACTUAL' : selectedRole === 'analyst' ? 'SIGNAL-IMD' : selectedRole === 'admin' ? 'NDMA-CONTROL' : 'GROUND-01'),
  };

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
              ? 'text-white bg-white/[0.10] border border-white/[0.14]'
              : 'text-slate-300 hover:text-white hover:bg-white/[0.06] border border-transparent'
          )}
          aria-current={isActive ? 'page' : undefined}
        >
          {/* Terracotta active spine with glow */}
          {isActive && (
            <motion.div
              layoutId={isMobile ? 'mobile-sidebar-active-bar' : 'sidebar-active-bar'}
              className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-[#E05D38] shadow-[0_0_8px_rgba(224,93,56,0.55)]"
              transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            />
          )}

          {/* Icon + label */}
          <div className="flex items-center gap-3 min-w-0 z-10">
            <div className="relative flex-shrink-0">
              <Icon
                className={cn(
                  'w-[18px] h-[18px] transition-all duration-200',
                  isActive
                    ? 'text-white'
                    : 'text-slate-400 group-hover:text-slate-200'
                )}
              />
              {/* Collapsed micro-badge dot */}
              {isCollapsedState && item.badge && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 w-2 h-2 rounded-full ring-[1.5px] ring-[#182235]',
                    item.badge.variant === 'live' && 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]',
                    item.badge.variant === 'critical' && 'bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.7)]',
                    item.badge.variant === 'warning' && 'bg-amber-400',
                    item.badge.variant === 'neutral' && 'bg-slate-400'
                  )}
                />
              )}
            </div>

            {!isCollapsedState && (
              <span
                title={item.label}
                className={cn(
                  'truncate block text-[13px]',
                  isActive ? 'font-semibold text-white' : 'font-medium text-slate-300 group-hover:text-white'
                )}
              >
                {item.label}
              </span>
            )}
          </div>

          {/* Trailing badge only — no shortcuts */}
          {!isCollapsedState && item.badge && (
            <span
              className={cn(
                'text-[10px] font-semibold px-1.5 py-0.5 rounded leading-none border flex-shrink-0 ml-auto z-10',
                item.badge.variant === 'live'
                  && 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 shadow-[0_0_6px_rgba(16,185,129,0.15)]',
                item.badge.variant === 'critical'
                  && 'bg-rose-500/20 text-rose-200 border-rose-500/40 animate-pulse',
                item.badge.variant === 'warning'
                  && 'bg-amber-500/15 text-amber-300 border-amber-500/30',
                item.badge.variant === 'neutral'
                  && 'bg-slate-700/60 text-slate-300 border-slate-600/50'
              )}
            >
              {item.badge.text}
            </span>
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
            <div className="bg-slate-900/96 backdrop-blur-md text-white border border-slate-700/70 rounded-xl p-3 shadow-2xl min-w-[200px] max-w-[250px] relative">
              <div className="absolute -left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 bg-slate-900 border-l border-b border-slate-700/70 transform rotate-45" />

              <div className="relative z-10 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-[12px] text-white">
                    {item.label}
                  </span>
                  {item.badge && (
                    <span
                      className={cn(
                        'text-[9px] font-semibold px-1.5 py-0.5 rounded border leading-none',
                        item.badge.variant === 'live' && 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
                        item.badge.variant === 'critical' && 'bg-rose-500/25 text-rose-300 border-rose-500/40',
                        item.badge.variant === 'warning' && 'bg-amber-500/20 text-amber-300 border-amber-500/30',
                        item.badge.variant === 'neutral' && 'bg-slate-700 text-slate-300 border-slate-600'
                      )}
                    >
                      {item.badge.text}
                    </span>
                  )}
                </div>

                {item.description && (
                  <p className="text-[11px] leading-snug text-slate-400">
                    {item.description}
                  </p>
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
        {/* Brand header — aligns with topbar h-14 */}
        <div
          className={cn(
            'flex items-center h-14 border-b border-white/10 flex-shrink-0',
            isCollapsedState ? 'justify-center px-2' : 'justify-between px-3.5'
          )}
        >
          <Link href="/" className="flex items-center gap-3 group min-w-0">
            {/* Brand mark — glowing terracotta lightning */}
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-[#B5482E]/20 border border-[#B5482E]/45 shadow-[0_0_10px_rgba(181,72,46,0.28)] group-hover:shadow-[0_0_16px_rgba(181,72,46,0.45)] group-hover:border-[#B5482E]/70 transition-all duration-200">
              <CloudLightning className="w-4.5 h-4.5 text-[#F97316]" />
            </div>

            <AnimatePresence mode="wait">
              {!isCollapsedState && (
                <motion.div
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: 'auto' }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.18 }}
                  className="overflow-hidden whitespace-nowrap min-w-0"
                >
                  <div className="flex items-center gap-2">
                    <h1
                      className="text-white font-bold text-[15px] tracking-wide"
                      style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                    >
                      INDRA
                    </h1>
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/10 text-slate-400 border border-white/12">
                      v1.2
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_5px_rgba(52,211,153,0.7)] animate-pulse inline-block" />
                    <p className="text-[10px] font-medium text-emerald-400/90">
                      Telemetry live
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Link>

          {/* Collapse toggle — desktop only */}
          {!isMobile && !isCollapsedState && (
            <button
              onClick={onToggle}
              className="flex items-center justify-center w-7 h-7 rounded-md transition-all duration-150 text-slate-500 hover:text-slate-200 hover:bg-white/[0.08] border border-white/10 hover:border-white/25 flex-shrink-0"
              title="Collapse sidebar ( [ or ⌘B )"
              aria-label="Collapse sidebar"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Collapsed expand button */}
        {isCollapsedState && !isMobile && (
          <div className="pt-2 pb-1 px-2 flex justify-center flex-shrink-0">
            <button
              onClick={onToggle}
              className="p-1.5 rounded-md transition-all duration-150 border border-white/12 text-slate-500 hover:text-slate-200 hover:bg-white/[0.08] hover:border-white/25"
              title="Expand sidebar"
              aria-label="Expand sidebar"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Navigation */}
        <div
          className={cn(
            'min-h-0 flex-1 px-2.5 py-2.5 space-y-3',
            isCollapsedState
              ? 'overflow-visible'
              : 'overflow-y-auto overflow-x-hidden'
          )}
          style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.12) transparent' }}
        >
          {navSections.map((section) => {
            const sectionItems = navItems.filter(
              (item) => item.section === section.id
            );
            if (sectionItems.length === 0) return null;

            const isSectionCollapsed = !!collapsedSections[section.id];

            return (
              <div key={section.id} className="space-y-0.5">
                {/* Section header */}
                {!isCollapsedState ? (
                  <button
                    onClick={() => toggleSection(section.id)}
                    className="w-full px-1.5 pt-2 pb-1 flex items-center gap-1.5 text-[10.5px] font-semibold tracking-wider uppercase text-slate-500 hover:text-slate-300 transition-colors text-left group/sec"
                    title={isSectionCollapsed ? `Expand ${section.label}` : `Collapse ${section.label}`}
                  >
                    <ChevronDown
                      className={cn(
                        'w-3 h-3 transition-transform duration-200 flex-shrink-0',
                        isSectionCollapsed && '-rotate-90'
                      )}
                    />
                    <span className="transition-colors">{section.label}</span>
                  </button>
                ) : (
                  <div className="h-px mx-1.5 my-2 bg-white/[0.08]" />
                )}

                <AnimatePresence initial={false}>
                  {(!isSectionCollapsed || isCollapsedState) && (
                    <motion.div
                      initial={isCollapsedState ? false : { opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.16, ease: 'easeOut' }}
                      className="space-y-0.5 overflow-hidden"
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
            'p-2.5 border-t border-white/[0.09] mt-auto flex-shrink-0',
            isCollapsedState && 'px-2'
          )}
          style={{ background: 'rgba(0,0,0,0.18)' }}
        >
          {/* Operator label */}
          {!isCollapsedState && (
            <div className="flex items-center justify-between px-1 mb-1.5">
              <span className="text-[10px] font-semibold tracking-wider uppercase text-slate-500">
                Operator
              </span>
              <span
                className="text-[10px] font-mono font-bold text-[#F97316] bg-[#B5482E]/12 border border-[#B5482E]/25 px-1.5 rounded"
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
                'flex items-center gap-2.5 p-2 rounded-lg transition-all duration-200 outline-none border border-white/[0.08] bg-white/[0.04] hover:bg-white/[0.09] hover:border-white/[0.18]',
                isCollapsedState && 'justify-center p-1.5'
              )}
            >
              {/* Avatar with duty dot */}
              <div className="relative flex-shrink-0">
                <div
                  className="w-8 h-8 rounded-md text-white font-bold text-xs flex items-center justify-center bg-[#B5482E]/35 border border-[#B5482E]/45"
                  suppressHydrationWarning
                >
                  {profile.avatar_initials}
                </div>
                <span
                  className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full ring-[1.5px] ring-[#182235]"
                  style={{ backgroundColor: activeStatusCfg.dot }}
                />
              </div>

              {/* Name (expanded) */}
              {!isCollapsedState && (
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-1">
                    <p
                      className="text-[12px] font-semibold text-white truncate"
                      title={profile.full_name}
                      suppressHydrationWarning
                    >
                      {profile.full_name}
                    </p>
                    <ChevronRight className="w-3 h-3 flex-shrink-0 text-slate-500 group-hover:text-slate-300 transition-colors" />
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-slate-500 truncate mt-0.5">
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
                <div className="bg-slate-900/96 backdrop-blur-md text-white border border-slate-700/70 rounded-xl p-3 shadow-2xl min-w-[200px] relative">
                  <div className="absolute -left-1.5 bottom-3 w-3 h-3 bg-slate-900 border-l border-b border-slate-700/70 transform rotate-45" />
                  <div className="relative z-10 space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-[12px] text-white" suppressHydrationWarning>
                        {profile.full_name}
                      </span>
                      <span
                        className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25"
                        suppressHydrationWarning
                      >
                        {profile.duty_status.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="text-[10px] font-mono text-[#F97316] font-bold" suppressHydrationWarning>
                      {profile.callsign}
                    </p>
                    <p className="text-[10px] text-slate-400" suppressHydrationWarning>
                      {profile.team_name}
                    </p>
                    <div className="pt-1.5 border-t border-slate-800/80 text-[10px] text-slate-400 font-medium flex items-center gap-1">
                      <span>View operator dossier</span>
                      <ChevronRight className="w-2.5 h-2.5" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Settings link — compact */}
          {!isCollapsedState && (
            <Link
              href="/settings"
              onClick={isMobile ? onMobileClose : undefined}
              className="mt-1.5 flex items-center gap-2 px-2 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 hover:text-slate-200 hover:bg-white/[0.06] transition-all duration-150"
              title="Platform Settings (⌘,)"
            >
              <Settings className="w-3.5 h-3.5 hover:rotate-45 transition-transform duration-300" />
              <span>Platform Settings</span>
            </Link>
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
        animate={{ width: collapsed ? 68 : 272 }}
        transition={{ duration: 0.22, ease: [0.25, 0.46, 0.45, 0.94] }}
        className={cn(
          'fixed left-0 top-0 h-screen z-40',
          'hidden md:flex flex-col',
          'border-r'
        )}
        style={{
          background: 'linear-gradient(180deg, #182235 0%, #111827 100%)',
          borderColor: 'rgba(255, 255, 255, 0.09)',
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
              transition={{ duration: 0.18 }}
              className="fixed inset-0 z-40 md:hidden bg-black/55 backdrop-blur-sm"
              onClick={onMobileClose}
            />
            <motion.aside
              initial={{ x: -285 }}
              animate={{ x: 0 }}
              exit={{ x: -285 }}
              transition={{ type: 'spring', stiffness: 340, damping: 34 }}
              className="fixed left-0 top-0 h-screen w-[285px] z-50 md:hidden border-r"
              style={{
                background: 'linear-gradient(180deg, #182235 0%, #111827 100%)',
                borderColor: 'rgba(255, 255, 255, 0.09)',
              }}
            >
              <button
                onClick={onMobileClose}
                className="absolute right-3 top-4 w-7 h-7 rounded-lg border border-white/12 bg-white/[0.08] flex items-center justify-center text-slate-400 hover:text-white transition-colors"
                aria-label="Close menu"
              >
                <X className="w-3.5 h-3.5" />
              </button>
              {sidebarBody(true)}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
