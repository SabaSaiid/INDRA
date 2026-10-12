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
} from '@/lib/ui-config';
import { useOperatorProfile } from '@/lib/useOperatorProfile';
import { useIndraWebSocket } from '@/lib/useIndraWebSocket';
import SignInDialog from './SignInDialog';
import {
  CloudLightning,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  X,
  Settings,
  LogIn,
  User,
} from 'lucide-react';
import { useTranslation } from '@/lib/i18n/useTranslation';

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
  const { t } = useTranslation();
  const { connected } = useIndraWebSocket();
  const { session, profile } = useOperatorProfile();
  const [signInOpen, setSignInOpen] = useState(false);

  // The profile as the backend returned it; until it arrives, the account the
  // session names. Signed out, the footer says so and offers sign-in.
  const operatorName = profile?.full_name || session?.username || '';
  const operatorUnit = profile?.team_name
    ? profile.team_name.split('—')[0].trim()
    : (profile?.agency || session?.agency || '').replace(/_/g, ' ');
  const callsign = profile?.callsign || null;

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

  // No dot for a status the profile does not carry: never a default 'On Duty'.
  const activeStatusCfg = profile ? dutyStatusConfig[profile.duty_status as DutyStatus] ?? null : null;

  // Resolve localized label for any navigation item
  const getNavItemLabel = (item: NavItem): string => {
    const navKeyMap: Record<string, string> = {
      'dashboard': 'nav.dashboard',
      'live-map': 'nav.live_map',
      'events': 'nav.incident_events',
      'alerts': 'nav.early_warnings',
      'reports': 'nav.field_reports',
      'analytics': 'nav.analytics',
      'datasets': 'nav.geospatial_feeds',
      'teams': 'nav.teams_hub',
      'profile': 'nav.operator_profile',
      'admin': 'nav.admin_command',
      'settings': 'nav.platform_settings',
    };

    const targetKey = navKeyMap[item.id] || `nav.${item.id.replace(/-/g, '_')}`;
    const translated = t(targetKey);
    if (translated && translated !== targetKey) {
      return translated;
    }

    // Secondary fallback mappings
    if (item.id === 'alerts') {
      const fb = t('nav.official_warnings');
      if (fb && fb !== 'nav.official_warnings') return fb;
    }
    if (item.id === 'teams') {
      const fb = t('nav.response_teams');
      if (fb && fb !== 'nav.response_teams') return fb;
    }
    if (item.id === 'profile') {
      const fb = t('nav.operator');
      if (fb && fb !== 'nav.operator') return fb;
    }
    if (item.id === 'admin') {
      const fb = t('nav.admin_panel');
      if (fb && fb !== 'nav.admin_panel') return fb;
    }
    if (item.id === 'settings') {
      const fb = t('nav.system_settings');
      if (fb && fb !== 'nav.system_settings') return fb;
    }

    return item.label;
  };

  // ── Nav item renderer ───────────────────────────────────────────────────────
  const renderNavItem = (item: NavItem, isMobile = false) => {
    const isActive = isItemActive(item);
    const Icon = item.icon;
    const isCollapsedState = collapsed && !isMobile;
    const navLabel = getNavItemLabel(item);
    const badgeText = item.badge
      ? (item.badge.text === 'LIVE' ? (t('kpis.live_label') || item.badge.text) : item.badge.text)
      : null;

    return (
      <div key={item.id} className="relative group">
        <Link
          href={item.href}
          onClick={isMobile ? onMobileClose : undefined}
          title={navLabel}
          className={cn(
            'relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 outline-none select-none',
            isCollapsedState ? 'justify-center px-2' : 'justify-between',
            isActive
              ? 'text-[var(--rail-text)] bg-[var(--rail-active-bg)] border border-[var(--rail-active-border)]'
              : 'text-[var(--rail-text-muted)] hover:text-[var(--rail-text)] hover:bg-[var(--rail-hover-bg)] border border-transparent'
          )}
          aria-current={isActive ? 'page' : undefined}
        >
          {/* Active spine with glow */}
          {isActive && (
            <motion.div
              layoutId={isMobile ? 'mobile-sidebar-active-bar' : 'sidebar-active-bar'}
              className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-brand shadow-[0_0_8px_rgba(var(--brand),0.55)]"
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
                    ? 'text-[var(--rail-text)]'
                    : 'text-[var(--rail-text-muted)] group-hover:text-[var(--rail-text)]'
                )}
              />
              {/* Collapsed micro-badge dot */}
              {isCollapsedState && item.badge && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 w-2 h-2 rounded-full ring-[1.5px] ring-surface-rail',
                    item.badge.variant === 'live' && 'bg-status-verified shadow-[0_0_6px_rgba(var(--status-verified),0.7)]',
                    item.badge.variant === 'critical' && 'bg-severity-critical shadow-[0_0_6px_rgba(var(--severity-critical),0.7)]',
                    item.badge.variant === 'warning' && 'bg-severity-high',
                    item.badge.variant === 'neutral' && 'bg-severity-low'
                  )}
                />
              )}
            </div>

            {!isCollapsedState && (
              <span
                title={navLabel}
                className={cn(
                  'truncate block text-[13px] leading-normal py-0.5',
                  isActive ? 'font-semibold text-[var(--rail-text)]' : 'font-medium text-[var(--rail-text-muted)] group-hover:text-[var(--rail-text)]'
                )}
              >
                {navLabel}
              </span>
            )}
          </div>

          {/* Trailing badge only — no shortcuts */}
          {!isCollapsedState && item.badge && (
            <span
              className={cn(
                'text-[10px] font-semibold px-1.5 py-0.5 rounded leading-normal border flex-shrink-0 ml-auto z-10',
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
              {badgeText}
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
                    {navLabel}
                  </span>
                  {item.badge && (
                    <span
                      className={cn(
                        'text-[9px] font-semibold px-1.5 py-0.5 rounded border leading-normal',
                        item.badge.variant === 'live' && 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
                        item.badge.variant === 'critical' && 'bg-rose-500/25 text-rose-300 border-rose-500/40',
                        item.badge.variant === 'warning' && 'bg-amber-500/20 text-amber-300 border-amber-500/30',
                        item.badge.variant === 'neutral' && 'bg-slate-700 text-slate-300 border-slate-600'
                      )}
                    >
                      {badgeText}
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
            'flex items-center h-14 border-b border-[var(--rail-border-color)] flex-shrink-0',
            isCollapsedState ? 'justify-center px-2' : 'justify-between px-3.5'
          )}
        >
          <Link href="/" className="flex items-center gap-3 group min-w-0">
            {/* Brand mark — glowing lightning */}
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-brand/20 border border-brand/45 shadow-[0_0_10px_rgba(var(--brand),0.28)] group-hover:shadow-[0_0_16px_rgba(var(--brand),0.45)] group-hover:border-brand/70 transition-all duration-200">
              <CloudLightning className="w-4.5 h-4.5 text-brand" />
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
                      className="font-bold text-[15px] tracking-wide"
                      style={{ color: 'var(--rail-text)', fontFamily: 'var(--font-display, Fraunces, Georgia, serif)' }}
                    >
                      INDRA
                    </h1>
                  </div>
                  {/* The socket's real state, not a fixed green. */}
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span
                      className={cn(
                        'w-1.5 h-1.5 rounded-full inline-block',
                        connected
                          ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)] animate-pulse'
                          : 'bg-amber-400'
                      )}
                    />
                    <p className={cn('text-[10px] font-semibold', connected ? 'text-emerald-400' : 'text-amber-400')}>
                      {connected ? 'Live' : 'Offline — reconnecting'}
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
              className="flex items-center justify-center w-7 h-7 rounded-md transition-all duration-150 text-[var(--rail-text-muted)] hover:text-[var(--rail-text)] hover:bg-[var(--rail-hover-bg)] border border-[var(--rail-border-color)] flex-shrink-0"
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
              className="p-1.5 rounded-md transition-all duration-150 border border-[var(--rail-border-color)] text-[var(--rail-text-muted)] hover:text-[var(--rail-text)] hover:bg-[var(--rail-hover-bg)]"
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
            'min-h-0 flex-1 px-2.5 py-1.5 space-y-2',
            isCollapsedState
              ? 'overflow-visible'
              : 'overflow-y-auto overflow-x-hidden'
          )}
          style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.25) transparent' }}
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
                    className="w-full px-1.5 pt-1.5 pb-0.5 flex items-center gap-1.5 text-[10.5px] font-bold tracking-wider uppercase text-[var(--rail-text-muted)] hover:text-[var(--rail-text)] transition-colors text-left group/sec"
                    title={isSectionCollapsed ? `Expand ${t(`nav.section_${section.id}`)}` : `Collapse ${t(`nav.section_${section.id}`)}`}
                  >
                    <ChevronDown
                      className={cn(
                        'w-3 h-3 transition-transform duration-200 flex-shrink-0 text-[var(--rail-text-muted)] group-hover/sec:text-[var(--rail-text)]',
                        isSectionCollapsed && '-rotate-90'
                      )}
                    />
                    <span className="transition-colors">{t(`nav.section_${section.id}`)}</span>
                  </button>
                ) : (
                  <div className="h-px mx-1.5 my-1.5 bg-white/[0.08]" />
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
            'p-2.5 border-t border-[var(--rail-border-color)] mt-auto flex-shrink-0',
            isCollapsedState && 'px-2'
          )}
          style={{ background: 'var(--rail-hover-bg)' }}
        >
          {/* Operator label */}
          {!isCollapsedState && (
            <div className="flex items-center justify-between px-1 mb-1.5">
              <span className="text-[10px] font-semibold tracking-wider uppercase text-[var(--rail-text-muted)]">
                {t('nav.operator')}
              </span>
              {callsign && (
                <span
                  className="text-[10px] font-mono font-bold text-brand bg-brand/12 border border-brand/25 px-1.5 rounded"
                  suppressHydrationWarning
                >
                  {callsign}
                </span>
              )}
            </div>
          )}

          {/* Profile card, or sign-in when there is no session */}
          <div className="relative group">
            {session ? (
              <Link
                href="/profile"
                onClick={isMobile ? onMobileClose : undefined}
                className={cn(
                  'flex items-center gap-2.5 p-2 rounded-lg transition-all duration-200 outline-none border border-[var(--rail-border-color)] bg-[var(--rail-hover-bg)] hover:bg-[var(--rail-active-bg)]',
                  isCollapsedState && 'justify-center p-1.5'
                )}
              >
                {/* Avatar with duty dot */}
                <div className="relative flex-shrink-0">
                  <div
                    className="w-8 h-8 rounded-md text-[var(--rail-text)] font-bold text-xs flex items-center justify-center bg-brand/35 border border-brand/45"
                    suppressHydrationWarning
                  >
                    {profile?.avatar_initials || <User className="w-4 h-4" />}
                  </div>
                  {activeStatusCfg && (
                    <span
                      className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full ring-[1.5px] ring-surface-rail"
                      style={{ backgroundColor: activeStatusCfg.dot }}
                    />
                  )}
                </div>

                {/* Name (expanded) */}
                {!isCollapsedState && (
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1">
                      <p
                        className="text-[12px] font-semibold text-[var(--rail-text)] truncate"
                        title={operatorName}
                        suppressHydrationWarning
                      >
                        {operatorName}
                      </p>
                      <ChevronRight className="w-3 h-3 flex-shrink-0 text-[var(--rail-text-muted)] transition-colors" />
                    </div>
                    {operatorUnit && (
                      <div className="flex items-center gap-1 text-[10px] text-[var(--rail-text-muted)] truncate mt-0.5">
                        <span className="truncate" suppressHydrationWarning>
                          {operatorUnit}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => {
                  if (isMobile) onMobileClose();
                  setSignInOpen(true);
                }}
                aria-label="Not signed in. Sign in"
                className={cn(
                  'w-full flex items-center gap-2.5 p-2 rounded-lg transition-all duration-200 outline-none border border-[var(--rail-border-color)] bg-[var(--rail-hover-bg)] hover:bg-[var(--rail-active-bg)] text-left',
                  isCollapsedState && 'justify-center p-1.5'
                )}
              >
                <div className="w-8 h-8 rounded-md text-[var(--rail-text-muted)] flex items-center justify-center bg-[var(--rail-hover-bg)] border border-[var(--rail-border-color)] flex-shrink-0">
                  <User className="w-4 h-4" />
                </div>
                {!isCollapsedState && (
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] font-semibold text-[var(--rail-text)] truncate">{t('common.session_inactive')}</p>
                    <p className="flex items-center gap-1 text-[10px] text-[var(--rail-text-muted)] font-medium mt-0.5">
                      <LogIn className="w-3 h-3 text-[var(--rail-text-muted)]" />
                      {t('common.duty_on')}
                    </p>
                  </div>
                )}
              </button>
            )}

            {/* Collapsed operator tooltip */}
            {isCollapsedState && (
              <div
                className={cn(
                  'absolute left-full bottom-0 ml-3 z-50 pointer-events-none',
                  'transition-all duration-150 origin-left',
                  'opacity-0 scale-95 -translate-x-1 group-hover:opacity-100 group-hover:scale-100 group-hover:translate-x-0'
                )}
              >
                <div className="bg-surface-raised text-text border border-border rounded-xl p-3 shadow-2xl min-w-[200px] relative">
                  <div className="absolute -left-1.5 bottom-3 w-3 h-3 bg-surface-raised border-l border-b border-border transform rotate-45" />
                  <div className="relative z-10 space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-[12px] text-text" suppressHydrationWarning>
                        {session ? operatorName : 'Not signed in'}
                      </span>
                      {profile?.duty_status && (
                        <span
                          className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-status-verified-soft text-status-verified border border-status-verified/25"
                          suppressHydrationWarning
                        >
                          {profile.duty_status.replace('_', ' ')}
                        </span>
                      )}
                    </div>
                    {callsign && (
                      <p className="text-[10px] font-mono text-brand font-bold" suppressHydrationWarning>
                        {callsign}
                      </p>
                    )}
                    {operatorUnit && (
                      <p className="text-[10px] text-text-muted" suppressHydrationWarning>
                        {operatorUnit}
                      </p>
                    )}
                    <div className="pt-1.5 border-t border-border text-[10px] text-text-muted font-medium flex items-center gap-1">
                      <span>{session ? 'View operator profile' : 'Sign in'}</span>
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
              className="mt-1.5 flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs font-semibold text-[var(--rail-text-muted)] hover:text-[var(--rail-text)] hover:bg-[var(--rail-hover-bg)] transition-all duration-150"
              title="Platform Settings (⌘,)"
            >
              <Settings className="w-3.5 h-3.5 hover:rotate-45 transition-transform duration-300" />
              <span>{t('nav.platform_settings')}</span>
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
          background: 'var(--rail-gradient, linear-gradient(180deg, #182235 0%, #111827 100%))',
          borderColor: 'var(--rail-border-color, rgba(255, 255, 255, 0.09))',
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
                background: 'var(--rail-gradient, linear-gradient(180deg, #182235 0%, #111827 100%))',
                borderColor: 'var(--rail-border-color, rgba(255, 255, 255, 0.09))',
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

      <SignInDialog open={signInOpen} onClose={() => setSignInOpen(false)} />
    </>
  );
}
