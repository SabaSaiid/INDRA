'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Search,
  Bell,
  ChevronDown,
  Menu,
  User,
  Shield,
  Users,
  Award,
  Radio,
  Check,
  Settings,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { fadeIn } from '@/lib/motion';
import {
  type DutyStatus,
  dutyStatusConfig,
} from '@/lib/mock-data';
import { useOperatorProfile } from '@/lib/useOperatorProfile';
import SettingsDrawer from './SettingsDrawer';

interface TopbarProps {
  onMobileMenuOpen: () => void;
}

export default function Topbar({ onMobileMenuOpen }: TopbarProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const {
    profile: currentProfile,
    selectedRole,
    switchRole,
    updateDuty,
    isUpdatingStatus,
  } = useOperatorProfile();
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Click away listener to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Keyboard shortcut: Cmd+, for settings
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setSettingsOpen((prev) => !prev);
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
      style={{ background: 'rgba(247, 243, 234, 0.95)', backdropFilter: 'blur(16px)' }}
    >
      <div className="flex items-center justify-between h-[50px] px-4 lg:px-6">
        {/* Mobile menu button */}
        <button
          onClick={onMobileMenuOpen}
          className="md:hidden p-2 rounded-md hover:bg-[#F0EBE0] transition-colors"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5 text-ink-2" />
        </button>

        {/* Search */}
        <div className="flex-1 max-w-xl mx-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#B0A898]" />
            <input
              type="text"
              placeholder="Search location, event or report…"
              className="w-full h-8 pl-10 pr-4 rounded-md bg-[#F0EBE0] border border-[#E8E2D4] text-sm text-ink placeholder:text-[#B0A898] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20 focus:border-[#B5482E]/40 transition-all"
              aria-label="Search"
            />
          </div>
        </div>

        {/* Right section */}
        <div className="flex items-center gap-3">
          {/* Grid status moved to WelcomeHeader executive strip — removed duplicate here */}

          {/* Notifications */}
          <button
            className="relative p-2 rounded-md hover:bg-[#F0EBE0] transition-colors"
            aria-label="Notifications"
          >
            <Bell className="w-5 h-5 text-[#7A8599]" />
            {/* Alert dot */}
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#8C2F26]" />
          </button>

          {/* Settings trigger */}
          <button
            onClick={() => setSettingsOpen(true)}
            className="relative p-2 rounded-md hover:bg-[#F0EBE0] transition-colors text-[#7A8599] hover:text-ink group"
            aria-label="Platform Settings"
            title="System Settings & HUD Preferences (⌘,)"
          >
            <Settings className="w-5 h-5 transition-transform duration-300 group-hover:rotate-45" />
          </button>

          {/* Profile menu */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setProfileOpen(!profileOpen)}
              className="flex items-center gap-2.5 pl-2.5 pr-2 py-1.5 rounded-md hover:bg-[#F0EBE0] transition-colors border border-transparent hover:border-[#E8E2D4]"
              aria-expanded={profileOpen}
              aria-haspopup="true"
            >
              {/* Avatar */}
              <div className="relative">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center text-[#F7F3EA] text-xs font-semibold shadow-sm"
                  style={{ background: '#26314A' }}
                  suppressHydrationWarning
                >
                  {currentProfile.avatar_initials || 'RV'}
                </div>
                <span
                  className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[#F7F3EA]"
                  style={{ backgroundColor: activeStatusCfg.dot }}
                  title={`Status: ${activeStatusCfg.label}`}
                />
              </div>

              {/* Name metadata */}
              <div className="hidden sm:block text-left">
                <p
                  className="text-xs font-semibold text-ink leading-tight truncate max-w-[140px]"
                  title={currentProfile.full_name}
                  suppressHydrationWarning
                >
                  {currentProfile.full_name}
                </p>
                <p className="text-[10px] text-[#7A8599]" suppressHydrationWarning>
                  {currentProfile.team_role || (currentProfile.role === 'COMMANDER' ? 'Operations Director' : currentProfile.role)}
                </p>
              </div>

              <ChevronDown
                className={`w-3.5 h-3.5 text-[#7A8599] hidden sm:block transition-transform duration-200 ${
                  profileOpen ? 'rotate-180' : ''
                }`}
              />
            </button>

            {/* Profile dropdown */}
            <AnimatePresence>
              {profileOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 8, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 8, scale: 0.96 }}
                  transition={{ duration: 0.15 }}
                  className="absolute right-0 mt-2 w-80 sm:w-96 rounded-lg border border-[#E8E2D4] overflow-hidden z-50 divide-y divide-[#E8E2D4]"
                  style={{ background: '#FDFAF5', boxShadow: '0 8px 24px rgba(30,42,59,0.12)' }}
                >
                  {/* Header: Operator card */}
                  <div className="p-4" style={{ background: '#F7F3EA' }}>
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-11 h-11 rounded-lg flex items-center justify-center font-semibold text-base"
                          style={{ background: '#26314A', color: '#F7F3EA' }}
                        >
                          {currentProfile.avatar_initials || 'RV'}
                        </div>
                        <div>
                          <h4 className="text-sm font-semibold text-ink leading-snug">
                            {currentProfile.full_name}
                          </h4>
                          <p className="text-xs text-[#7A8599]">
                            {currentProfile.email || 'operator@sih-indra.gov.in'}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-[#E8E2D4] text-[#4A5568]">
                              {currentProfile.operator_id}
                            </span>
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-[#ECEEF3] text-[#26314A]">
                              {currentProfile.agency}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Radio callsign */}
                    {currentProfile.callsign && (
                      <div className="mt-2 flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-md bg-[#FDFAF5] border border-[#E8E2D4] text-[#4A5568]">
                        <span className="flex items-center gap-1.5 font-medium">
                          <Radio className="w-3.5 h-3.5 text-[#7A8599]" />
                          Radio Designation:
                        </span>
                        <span
                          className="font-semibold text-ink tracking-wider"
                          style={{ fontFamily: 'JetBrains Mono, monospace' }}
                        >
                          {currentProfile.callsign}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Duty Status Selector */}
                  <div className="p-3.5">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold tracking-wider uppercase text-[#7A8599]">
                        Operational Status
                      </span>
                      {isUpdatingStatus && (
                        <span className="text-[10px] text-[#B5482E] animate-pulse">Syncing…</span>
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
                            className={`flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs font-medium transition-all ${
                              isSelected
                                ? 'text-[#F7F3EA]'
                                : 'bg-[#F3F4F6] text-[#4A5568] hover:bg-[#E8E2D4]'
                            }`}
                            style={isSelected ? { background: '#26314A' } : {}}
                          >
                            <span className="flex items-center gap-1.5">
                              <span
                                className="w-2 h-2 rounded-full"
                                style={{ backgroundColor: isSelected ? '#F7F3EA' : cfg.dot }}
                              />
                              {cfg.label}
                            </span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-[#F7F3EA]" />}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Role Switcher (RBAC Demo) */}
                  <div className="p-3.5" style={{ background: '#F7F3EA' }}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold tracking-wider uppercase text-[#7A8599] flex items-center gap-1">
                        <Shield className="w-3 h-3 text-[#7A8599]" />
                        Switch Role (RBAC Demo)
                      </span>
                      <span className="text-[10px] text-[#B0A898]">SIH Testing</span>
                    </div>
                    <div className="grid grid-cols-4 gap-1">
                      {[
                        { id: 'commander', label: 'Ops Lead' },
                        { id: 'analyst',   label: 'Analyst' },
                        { id: 'admin',     label: 'Admin'  },
                        { id: 'citizen',   label: 'Citizen' },
                      ].map((r) => {
                        const isSelected = selectedRole === r.id;
                        return (
                          <button
                            key={r.id}
                            onClick={() => switchRole(r.id)}
                            className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                              isSelected
                                ? 'text-[#F7F3EA] font-semibold'
                                : 'bg-[#FDFAF5] border border-[#E8E2D4] text-[#4A5568] hover:bg-[#F0EBE0]'
                            }`}
                            style={isSelected ? { background: '#B5482E' } : {}}
                          >
                            {r.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Navigation links */}
                  <div className="p-2 space-y-0.5">
                    <Link
                      href="/profile"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-md text-sm font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <User className="w-4 h-4 text-[#7A8599]" />
                        My Profile &amp; Dispatch Settings
                      </span>
                      <ChevronDown className="w-3.5 h-3.5 -rotate-90 text-[#B0A898]" />
                    </Link>

                    <Link
                      href="/teams"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-md text-sm font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <Users className="w-4 h-4 text-[#7A8599]" />
                        Disaster Response Units &amp; Teams
                      </span>
                      <ChevronDown className="w-3.5 h-3.5 -rotate-90 text-[#B0A898]" />
                    </Link>

                    <Link
                      href="/teams?tab=hackathon"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-md text-sm font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <Award className="w-4 h-4 text-[#B8873A]" />
                        Team Sixth Sense (SIH Roster)
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#FBF2E4] text-[#8A611E] font-semibold border border-[#D4B87A]">
                        SIH 2026
                      </span>
                    </Link>

                    <button
                      onClick={() => {
                        setProfileOpen(false);
                        setSettingsOpen(true);
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-md text-sm font-medium text-[#4A5568] hover:bg-[#F0EBE0] hover:text-ink transition-colors text-left"
                    >
                      <span className="flex items-center gap-2.5">
                        <Settings className="w-4 h-4 text-[#7A8599]" />
                        Platform Settings &amp; HUD Config
                      </span>
                      <span
                        className="text-[10px] text-[#7A8599] bg-[#E8E2D4] px-1.5 py-0.5 rounded border border-[#D8D0C4]"
                        style={{ fontFamily: 'JetBrains Mono, monospace' }}
                      >
                        ⌘,
                      </span>
                    </button>
                  </div>

                  {/* Footer */}
                  <div className="px-4 py-2.5 flex items-center justify-between text-[11px] text-[#7A8599]" style={{ background: '#F7F3EA' }}>
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
    </>
  );
}
