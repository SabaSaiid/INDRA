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
  LogOut,
  ExternalLink,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { fadeIn } from '@/lib/motion';
import {
  type UserProfile,
  type DutyStatus,
  dutyStatusConfig,
  mockUserProfile,
} from '@/lib/mock-data';
import { fetchUserProfile, updateUserProfile } from '@/lib/api';

interface TopbarProps {
  onMobileMenuOpen: () => void;
}

export default function Topbar({ onMobileMenuOpen }: TopbarProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [currentProfile, setCurrentProfile] = useState<UserProfile>(mockUserProfile);
  const [selectedRole, setSelectedRole] = useState<string>('commander');
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Load profile on mount or role change
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchUserProfile(selectedRole);
        if (!cancelled && data) {
          setCurrentProfile(data);
        }
      } catch {
        // Fallback already in place
      }
    })();
    return () => { cancelled = true; };
  }, [selectedRole]);

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

  const handleDutyChange = async (newStatus: DutyStatus) => {
    if (newStatus === currentProfile.duty_status) return;
    setIsUpdatingStatus(true);
    setCurrentProfile(prev => ({ ...prev, duty_status: newStatus }));
    try {
      await updateUserProfile({ duty_status: newStatus }, selectedRole);
    } catch (err) {
      console.warn('Failed to update duty status', err);
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const activeStatusCfg = dutyStatusConfig[currentProfile.duty_status as DutyStatus] || dutyStatusConfig.ON_DUTY;

  return (
    <motion.header
      variants={fadeIn}
      initial="hidden"
      animate="visible"
      className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-slate-100"
    >
      <div className="flex items-center justify-between h-16 px-4 lg:px-6">
        {/* Mobile menu button */}
        <button
          onClick={onMobileMenuOpen}
          className="md:hidden p-2 rounded-lg hover:bg-slate-100 transition-colors"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5 text-slate-600" />
        </button>

        {/* Search */}
        <div className="flex-1 max-w-xl mx-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search location, event or report..."
              className="w-full h-10 pl-10 pr-4 rounded-xl bg-slate-50 border border-slate-200 text-sm text-text-primary placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
              aria-label="Search"
            />
          </div>
        </div>

        {/* Right section */}
        <div className="flex items-center gap-3">
          {/* Live System Status Pill */}
          <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-50 border border-slate-100">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-medium text-slate-600">National Grid Active</span>
          </div>

          {/* Notifications */}
          <button
            className="relative p-2 rounded-xl hover:bg-slate-50 transition-colors"
            aria-label="Notifications"
          >
            <Bell className="w-5 h-5 text-slate-500" />
            {/* Red dot badge */}
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-critical" />
          </button>

          {/* Interactive User & Team Profile Menu */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setProfileOpen(!profileOpen)}
              className="flex items-center gap-2.5 pl-2.5 pr-2 py-1.5 rounded-xl hover:bg-slate-50 transition-colors border border-transparent hover:border-slate-200"
              aria-expanded={profileOpen}
              aria-haspopup="true"
            >
              {/* Avatar with live duty status ring */}
              <div className="relative">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-blue-700 flex items-center justify-center text-white text-xs font-bold shadow-sm">
                  {currentProfile.avatar_initials || 'SS'}
                </div>
                <span
                  className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ring-1 ring-slate-100"
                  style={{ backgroundColor: activeStatusCfg.dot }}
                  title={`Status: ${activeStatusCfg.label}`}
                />
              </div>

              {/* Text metadata */}
              <div className="hidden sm:block text-left">
                <div className="flex items-center gap-1.5">
                  <p className="text-sm font-semibold text-text-primary leading-tight truncate max-w-[130px]">
                    {currentProfile.full_name.split(' ')[0]}
                  </p>
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-50 text-primary border border-blue-100">
                    {currentProfile.role}
                  </span>
                </div>
                <p className="text-[10px] text-text-muted leading-tight truncate max-w-[130px]">
                  {currentProfile.team_name ? currentProfile.team_name.split('-')[0] : 'Team Sixth Sense'}
                </p>
              </div>

              <ChevronDown
                className={`w-3.5 h-3.5 text-slate-400 hidden sm:block transition-transform duration-200 ${
                  profileOpen ? 'rotate-180' : ''
                }`}
              />
            </button>

            {/* Profile Dropdown Popover */}
            <AnimatePresence>
              {profileOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 8, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 8, scale: 0.96 }}
                  transition={{ duration: 0.15 }}
                  className="absolute right-0 mt-2 w-80 sm:w-96 bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden z-50 divide-y divide-slate-100"
                >
                  {/* Dropdown Header: Operator Card */}
                  <div className="p-4 bg-gradient-to-br from-slate-50 via-white to-blue-50/40">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <div className="w-11 h-11 rounded-xl bg-primary text-white flex items-center justify-center font-bold text-base shadow-md shadow-primary/20">
                          {currentProfile.avatar_initials || 'SS'}
                        </div>
                        <div>
                          <h4 className="text-sm font-bold text-text-primary leading-snug">
                            {currentProfile.full_name}
                          </h4>
                          <p className="text-xs text-text-secondary">
                            {currentProfile.email || 'operator@sih-indra.gov.in'}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-200/80 text-slate-700">
                              {currentProfile.operator_id}
                            </span>
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-800">
                              {currentProfile.agency}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Radio Call Sign & Active Team */}
                    {currentProfile.callsign && (
                      <div className="mt-2 flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-lg bg-white/80 border border-slate-200/70 text-slate-600">
                        <span className="flex items-center gap-1.5 font-medium">
                          <Radio className="w-3.5 h-3.5 text-primary" />
                          Radio Callsign:
                        </span>
                        <span className="font-mono font-bold text-slate-800 tracking-wider">
                          {currentProfile.callsign}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Duty Status Selector */}
                  <div className="p-3.5 bg-white">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">
                        Operational Status
                      </span>
                      {isUpdatingStatus && (
                        <span className="text-[10px] text-primary animate-pulse">Syncing...</span>
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
                            className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                              isSelected
                                ? 'bg-slate-900 text-white shadow-sm'
                                : 'bg-slate-50 text-slate-600 hover:bg-slate-100'
                            }`}
                          >
                            <span className="flex items-center gap-1.5">
                              <span
                                className="w-2 h-2 rounded-full"
                                style={{ backgroundColor: isSelected ? '#FFFFFF' : cfg.dot }}
                              />
                              {cfg.label}
                            </span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-white" />}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Demo Role Switcher (RBAC Tester for SIH Jury) */}
                  <div className="p-3.5 bg-slate-50/70">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold tracking-wider uppercase text-slate-400 flex items-center gap-1">
                        <Shield className="w-3 h-3 text-slate-400" />
                        Switch Role (RBAC Demo)
                      </span>
                      <span className="text-[10px] text-slate-400">SIH Testing</span>
                    </div>
                    <div className="grid grid-cols-4 gap-1">
                      {[
                        { id: 'commander', label: 'Cmdr', badge: 'CMD' },
                        { id: 'analyst', label: 'Analyst', badge: 'ANL' },
                        { id: 'admin', label: 'Admin', badge: 'ADM' },
                        { id: 'citizen', label: 'Citizen', badge: 'CIT' },
                      ].map((r) => {
                        const isSelected = selectedRole === r.id;
                        return (
                          <button
                            key={r.id}
                            onClick={() => setSelectedRole(r.id)}
                            className={`px-2 py-1 rounded-lg text-[11px] font-medium transition-all ${
                              isSelected
                                ? 'bg-primary text-white font-semibold shadow-sm'
                                : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                            }`}
                          >
                            {r.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Navigation Links */}
                  <div className="p-2 space-y-0.5">
                    <Link
                      href="/profile"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-xl text-sm font-medium text-slate-700 hover:bg-slate-50 hover:text-primary transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <User className="w-4 h-4 text-slate-400" />
                        My Profile &amp; Dispatch Settings
                      </span>
                      <ChevronDown className="w-3.5 h-3.5 -rotate-90 text-slate-400" />
                    </Link>

                    <Link
                      href="/teams"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-xl text-sm font-medium text-slate-700 hover:bg-slate-50 hover:text-primary transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <Users className="w-4 h-4 text-slate-400" />
                        Disaster Response Units &amp; Teams
                      </span>
                      <ChevronDown className="w-3.5 h-3.5 -rotate-90 text-slate-400" />
                    </Link>

                    <Link
                      href="/teams?tab=hackathon"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center justify-between px-3 py-2 rounded-xl text-sm font-medium text-slate-700 hover:bg-slate-50 hover:text-primary transition-colors"
                    >
                      <span className="flex items-center gap-2.5">
                        <Award className="w-4 h-4 text-amber-500" />
                        Team Sixth Sense (SIH Roster)
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 font-semibold border border-amber-200">
                        SIH 2026
                      </span>
                    </Link>
                  </div>

                  {/* Footer */}
                  <div className="px-4 py-2.5 bg-slate-50 flex items-center justify-between text-[11px] text-slate-500">
                    <span>Problem Statement: SIH26069</span>
                    <span className="font-semibold text-slate-700">Team Sixth Sense</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </motion.header>
  );
}
