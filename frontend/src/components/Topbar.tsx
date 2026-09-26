'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Search,
  ChevronDown,
  Menu,
  User,
  Shield,
  Users,
  Award,
  Radio,
  Check,
  Settings,
  ShieldAlert,
  Plus,
  Lock,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import { fadeIn } from '@/lib/motion';
import {
  type DutyStatus,
  dutyStatusConfig,
  PLACEHOLDER_OPERATOR,
} from '@/lib/ui-config';
import { useOperatorProfile, AVAILABLE_OPERATOR_PERSONAS } from '@/lib/useOperatorProfile';
import SettingsDrawer from './SettingsDrawer';
import ReportSubmissionModal from './ReportSubmissionModal';
import NotificationPopover from './NotificationPopover';
import LanguagePicker from './LanguagePicker';

interface TopbarProps {
  onMobileMenuOpen: () => void;
}

export default function Topbar({ onMobileMenuOpen }: TopbarProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const {
    profile: loadedProfile,
    selectedRole,
    switchRole,
    updateDuty,
    isUpdatingStatus,
    isAuthenticated,
  } = useOperatorProfile();
  const currentProfile = loadedProfile ?? PLACEHOLDER_OPERATOR;
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Match the active role to the official persona to guarantee truthful, accurate data
  const currentPersona = AVAILABLE_OPERATOR_PERSONAS.find((p) => p.id === selectedRole) || AVAILABLE_OPERATOR_PERSONAS[0];

  const displayName = (currentProfile.full_name && currentProfile.full_name !== 'Operator unavailable' && currentProfile.full_name !== '—')
    ? (currentProfile.full_name === 'Incident Commander' ? currentPersona.name : currentProfile.full_name)
    : currentPersona.name;

  const avatarInitials = (currentProfile.avatar_initials && currentProfile.avatar_initials !== '—')
    ? currentProfile.avatar_initials
    : currentPersona.avatar;

  const agencyDisplay = (currentProfile.agency && currentProfile.agency !== '—')
    ? (currentProfile.agency === 'SDMA_BIHAR' ? 'SEOC Bihar / NDMA' : currentProfile.agency.replace(/_/g, ' '))
    : currentPersona.agency;

  const operatorIdDisplay = (currentProfile.operator_id && currentProfile.operator_id !== '—')
    ? currentProfile.operator_id
    : currentPersona.badge;

  const callsignDisplay = (currentProfile.callsign && currentProfile.callsign !== '—')
    ? currentProfile.callsign
    : (selectedRole === 'commander' ? 'PATNA-ACTUAL' : selectedRole === 'analyst' ? 'SIGNAL-IMD' : selectedRole === 'admin' ? 'NDMA-CONTROL' : 'GROUND-01');

  const roleTitleDisplay = currentPersona.label;
  const emailDisplay = currentProfile.email || `${selectedRole}.ops@sih-indra.gov.in`;

  /* Click-away close for profile dropdown */
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  /* Keyboard shortcuts: Cmd+, for settings, Cmd+K or / for search focus */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if user is typing in an input/textarea
      const target = e.target as HTMLElement | null;
      const isInput = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setSettingsOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
        if (searchInput) searchInput.focus();
      }
      if (e.key === '/' && !isInput) {
        e.preventDefault();
        const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
        if (searchInput) searchInput.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleDutyChange = async (newStatus: DutyStatus) => {
    updateDuty(newStatus);
  };

  const activeStatusCfg = dutyStatusConfig[currentProfile.duty_status as DutyStatus] || dutyStatusConfig.ON_DUTY;

  return (
    <>
      <motion.header
        variants={fadeIn}
        initial="hidden"
        animate="visible"
        className="sticky top-0 z-40 border-b border-[#E8E2D4]"
        style={{ background: 'rgba(247, 243, 234, 0.96)', backdropFilter: 'blur(16px)' }}
      >
        <div className="flex items-center justify-between h-14 px-3 sm:px-4 lg:px-6 gap-2 sm:gap-4">

          {/* Left section: Mobile menu button */}
          <div className="flex items-center md:hidden">
            <button
              onClick={onMobileMenuOpen}
              className="p-1.5 rounded-lg hover:bg-[#F0EBE0] text-ink-2 hover:text-ink transition-colors border border-transparent hover:border-[#E8E2D4]"
              aria-label="Open navigation menu"
            >
              <Menu className="w-5 h-5" />
            </button>
          </div>

          {/* Center: Adaptive Command Search */}
          <div className="flex-1 flex justify-start md:justify-center min-w-0">
            <div className="w-full max-w-xs sm:max-w-sm lg:max-w-md focus-within:max-w-lg transition-all duration-200">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#7A8599] pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search events, warnings, teams…"
                  className="w-full h-8 pl-9 pr-14 rounded-lg bg-[#F0EBE0]/80 border border-[#E8E2D4] text-xs sm:text-sm text-ink placeholder:text-[#7A8599] focus:outline-none focus:bg-[#FDFAF5] focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 transition-all shadow-inner"
                  aria-label="Search"
                />
                <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[#7A8599] bg-[#E8E2D4]/70 border border-[#D8D0C4] px-1.5 py-0.5 rounded hidden sm:inline-block select-none pointer-events-none">
                  /
                </kbd>
              </div>
            </div>
          </div>

          {/* Right section: Action CTA + Utility Cluster + Profile Pill */}
          <div className="flex items-center gap-2 sm:gap-2.5 flex-shrink-0">

            {/* Report Incident — primary emergency CTA */}
            <button
              onClick={() => setReportModalOpen(true)}
              className="flex items-center gap-1.5 h-8 px-2.5 sm:px-3 rounded-lg text-white text-xs font-semibold transition-all shadow-sm hover:shadow-md hover:brightness-105 active:scale-95 focus:outline-none focus:ring-2 focus:ring-[#B5482E]/30"
              style={{ background: 'linear-gradient(135deg, #C05030 0%, #B5482E 100%)' }}
              aria-label="Report an incident"
              id="report-incident-btn"
            >
              <ShieldAlert className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="hidden sm:inline">Report Incident</span>
              <Plus className="w-3.5 h-3.5 sm:hidden" />
            </button>

            {/* Divider */}
            <div className="hidden sm:block h-4 w-px bg-[#E8E2D4]" aria-hidden="true" />

            {/* Language Picker */}
            <LanguagePicker />

            {/* Divider */}
            <div className="hidden sm:block h-4 w-px bg-[#E8E2D4]" aria-hidden="true" />

            {/* Utility cluster: Notifications & Platform Settings */}
            <div className="flex items-center gap-0.5 bg-[#F0EBE0]/60 p-0.5 rounded-lg border border-[#E8E2D4]">
              <NotificationPopover />
              <button
                onClick={() => setSettingsOpen(true)}
                className="w-8 h-8 rounded-md flex items-center justify-center text-[#7A8599] hover:text-ink hover:bg-[#FDFAF5] transition-colors focus:outline-none focus:ring-1 focus:ring-[#B5482E]/30"
                aria-label="Platform Settings"
                title="System Settings & HUD Preferences (⌘,)"
              >
                <Settings className="w-4 h-4 transition-transform duration-300 hover:rotate-45" />
              </button>
            </div>

            {/* Profile trigger — compact circular avatar button (saves horizontal space, eliminates inaccurate text) */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setProfileOpen(!profileOpen)}
                className={cn(
                  'relative flex items-center justify-center w-8 h-8 rounded-full transition-all outline-none select-none flex-shrink-0',
                  profileOpen
                    ? 'ring-2 ring-[#B5482E] shadow-sm'
                    : 'ring-1 ring-[#D8D0C4] hover:ring-2 hover:ring-[#B5482E]/40 hover:scale-105 active:scale-95'
                )}
                aria-expanded={profileOpen}
                aria-haspopup="true"
                aria-label={`Operator profile: ${displayName} (${roleTitleDisplay})`}
                title={`${displayName} • ${roleTitleDisplay} (${activeStatusCfg.label})`}
              >
                {/* Avatar circle */}
                <div
                  className="w-full h-full rounded-full flex items-center justify-center text-[#F7F3EA] text-xs font-bold shadow-inner"
                  style={{ background: '#26314A' }}
                  suppressHydrationWarning
                >
                  {avatarInitials}
                </div>

                {/* Duty status indicator dot */}
                <span
                  className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-[#F7F3EA]"
                  style={{ backgroundColor: activeStatusCfg.dot }}
                  title={`Status: ${activeStatusCfg.label}`}
                />
              </button>

              {/* ── Reorganized Profile Dropdown ────────────────────────── */}
              <AnimatePresence>
                {profileOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: 8, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 8, scale: 0.96 }}
                    transition={{ duration: 0.15, ease: 'easeOut' }}
                    className="absolute right-0 mt-2 w-80 sm:w-[350px] rounded-xl border border-[#E8E2D4] overflow-hidden z-50 divide-y divide-[#E8E2D4] shadow-[0_12px_36px_rgba(30,42,59,0.18)] max-h-[calc(100vh-70px)] overflow-y-auto"
                    style={{ background: '#FDFAF5' }}
                  >
                    {/* ── Section 1: Identity & Security ─────────────── */}
                    <div className="p-3.5" style={{ background: '#F7F3EA' }}>
                      <div className="flex items-start gap-3">
                        <div
                          className="w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm flex-shrink-0 shadow-sm"
                          style={{ background: '#26314A', color: '#F7F3EA' }}
                        >
                          {avatarInitials}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-1">
                            <h4 className="text-sm font-semibold text-ink leading-snug truncate" suppressHydrationWarning>
                              {displayName}
                            </h4>
                            <span className="text-[10px] font-semibold text-[#B5482E] bg-[#B5482E]/10 border border-[#B5482E]/20 px-1.5 py-0.2 rounded flex-shrink-0">
                              {roleTitleDisplay}
                            </span>
                          </div>
                          <p className="text-xs text-[#7A8599] truncate mt-0.5" suppressHydrationWarning>
                            {emailDisplay}
                          </p>
                          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-[#E8E2D4] text-[#4A5568]">
                              {operatorIdDisplay}
                            </span>
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#ECEEF3] text-[#26314A]">
                              {agencyDisplay}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Callsign designation */}
                      <div className="mt-2.5 flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-lg bg-[#FDFAF5] border border-[#E8E2D4] text-[#4A5568]">
                        <span className="flex items-center gap-1.5 font-medium text-[#7A8599]">
                          <Radio className="w-3.5 h-3.5" />
                          Radio Designation
                        </span>
                        <span className="font-semibold text-ink tracking-wider font-mono">
                          {callsignDisplay}
                        </span>
                      </div>

                      {/* Auth / session status indicator */}
                      <div
                        className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-medium"
                        style={isAuthenticated
                          ? { background: 'rgba(52,211,153,0.08)', borderColor: 'rgba(52,211,153,0.25)', color: '#2D6A4F' }
                          : { background: 'rgba(122,133,153,0.08)', borderColor: 'rgba(122,133,153,0.2)', color: '#4A5568' }
                        }
                      >
                        <Lock className="w-3 h-3 flex-shrink-0" style={{ color: isAuthenticated ? '#10B981' : '#7A8599' }} />
                        <span className="flex-1 font-medium">
                          {isAuthenticated ? 'Secure Session (JWT HS256)' : 'Session inactive'}
                        </span>
                        {isAuthenticated && (
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0" />
                        )}
                      </div>
                    </div>

                    {/* ── Section 2: Duty Status Selector ────────────── */}
                    <div className="p-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] font-semibold tracking-wider uppercase text-[#7A8599]">
                          Operational Duty Status
                        </span>
                        {isUpdatingStatus && (
                          <span className="text-[10px] text-[#B5482E] animate-pulse font-medium">Syncing…</span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-1.5">
                        {(['ON_DUTY', 'STANDBY', 'DEPLOYED', 'OFF_DUTY'] as DutyStatus[]).map((st) => {
                          const cfg = dutyStatusConfig[st];
                          const isSelected = currentProfile.duty_status === st;
                          return (
                            <button
                              key={st}
                              onClick={() => handleDutyChange(st)}
                              className={cn(
                                'flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                                isSelected
                                  ? 'bg-[#26314A] text-[#F7F3EA] shadow-sm font-semibold'
                                  : 'bg-[#F3F4F6] text-[#4A5568] hover:bg-[#E8E2D4]'
                              )}
                            >
                              <span className="flex items-center gap-1.5">
                                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: isSelected ? '#F7F3EA' : cfg.dot }} />
                                {cfg.label}
                              </span>
                              {isSelected && <Check className="w-3.5 h-3.5 text-[#F7F3EA]" />}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* ── Section 3: Role Switcher (RBAC Demo) ────────── */}
                    <div className="p-3" style={{ background: '#F7F3EA' }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] font-semibold tracking-wider uppercase text-[#7A8599] flex items-center gap-1">
                          <Shield className="w-3 h-3 text-[#7A8599]" />
                          Switch Role
                        </span>
                        <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-[#FBF2E4] text-[#8A611E] border border-[#D4B87A]">
                          SIH RBAC DEMO
                        </span>
                      </div>
                      <div className="grid grid-cols-4 gap-1">
                        {[
                          { id: 'commander', label: 'Ops Lead' },
                          { id: 'analyst',   label: 'Analyst'  },
                          { id: 'admin',     label: 'Admin'    },
                          { id: 'citizen',   label: 'Citizen'  },
                        ].map((r) => {
                          const isSelected = selectedRole === r.id;
                          return (
                            <button
                              key={r.id}
                              onClick={() => switchRole(r.id)}
                              className={cn(
                                'px-2 py-1 rounded-lg text-[11px] font-medium transition-all text-center',
                                isSelected
                                  ? 'bg-[#B5482E] text-white font-semibold shadow-sm'
                                  : 'bg-[#FDFAF5] border border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                              )}
                            >
                              {r.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* ── Section 4: Navigation Links ──────────────────── */}
                    <div className="p-2 space-y-0.5">
                      <Link
                        href="/profile"
                        onClick={() => setProfileOpen(false)}
                        className="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                      >
                        <span className="flex items-center gap-2">
                          <User className="w-3.5 h-3.5 text-[#7A8599]" />
                          My Profile &amp; Dispatch Settings
                        </span>
                        <ChevronDown className="w-3 h-3 -rotate-90 text-[#B0A898]" />
                      </Link>

                      <Link
                        href="/teams"
                        onClick={() => setProfileOpen(false)}
                        className="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                      >
                        <span className="flex items-center gap-2">
                          <Users className="w-3.5 h-3.5 text-[#7A8599]" />
                          Disaster Response Units &amp; Teams
                        </span>
                        <ChevronDown className="w-3 h-3 -rotate-90 text-[#B0A898]" />
                      </Link>

                      <Link
                        href="/teams?tab=hackathon"
                        onClick={() => setProfileOpen(false)}
                        className="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                      >
                        <span className="flex items-center gap-2">
                          <Award className="w-3.5 h-3.5 text-[#B8873A]" />
                          Team Sixth Sense (SIH Roster)
                        </span>
                        <span className="text-[9px] px-1 py-0.2 rounded bg-[#FBF2E4] text-[#8A611E] font-semibold border border-[#D4B87A]">
                          SIH 2026
                        </span>
                      </Link>

                      <button
                        onClick={() => { setProfileOpen(false); setSettingsOpen(true); }}
                        className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors text-left"
                      >
                        <span className="flex items-center gap-2">
                          <Settings className="w-3.5 h-3.5 text-[#7A8599]" />
                          Platform Settings &amp; HUD Config
                        </span>
                        <span
                          className="text-[9px] text-[#7A8599] bg-[#E8E2D4] px-1 py-0.2 rounded border border-[#D8D0C4] font-mono"
                        >
                          ⌘,
                        </span>
                      </button>
                    </div>

                    {/* Footer */}
                    <div className="px-3.5 py-2 flex items-center justify-between text-[10px] text-[#7A8599]" style={{ background: '#F7F3EA' }}>
                      <span>Problem Statement: SIH26069</span>
                      <span className="font-semibold text-[#4A5568]">Team Sixth Sense</span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </motion.header>

      {/* Settings Drawer */}
      <SettingsDrawer
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      {/* Report Submission Modal */}
      <ReportSubmissionModal
        open={reportModalOpen}
        onClose={() => setReportModalOpen(false)}
      />
    </>
  );
}
