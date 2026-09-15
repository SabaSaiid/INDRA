'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  User,
  Shield,
  Radio,
  MapPin,
  Phone,
  Mail,
  Award,
  Clock,
  CheckCircle2,
  Edit3,
  Save,
  X,
  Copy,
  Check,
  Zap,
  Activity,
  FileCheck,
  Lock,
} from 'lucide-react';
import Link from 'next/link';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import {
  type UserProfile,
  type DutyStatus,
  mockUserProfile,
  dutyStatusConfig,
} from '@/lib/mock-data';
import { fetchUserProfile, updateUserProfile } from '@/lib/api';
import { fadeIn } from '@/lib/motion';
import { useSidebar } from '@/lib/useSidebar';

export default function ProfilePage() {
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();
  const [profile, setProfile] = useState<UserProfile>(mockUserProfile);
  const [isLoading, setIsLoading] = useState(true);

  // Edit Modal State
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({
    full_name: '',
    phone: '',
    callsign: '',
    bio: '',
  });
  const [isSaving, setIsSaving] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  // Fetch current user profile
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchUserProfile();
        if (!cancelled && data) {
          setProfile(data);
          setFormData({
            full_name: data.full_name || '',
            phone: data.phone || '',
            callsign: data.callsign || '',
            bio: data.bio || '',
          });
        }
      } catch (err) {
        console.warn('Using fallback profile', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleDutyChange = async (newStatus: DutyStatus) => {
    if (newStatus === profile.duty_status) return;
    setProfile((prev) => ({ ...prev, duty_status: newStatus }));
    try {
      await updateUserProfile({ duty_status: newStatus });
    } catch (err) {
      console.error('Failed to update status', err);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const updated = await updateUserProfile(formData);
      setProfile((prev) => ({ ...prev, ...formData }));
      setIsEditing(false);
    } catch (err) {
      console.error('Failed to save profile', err);
    } finally {
      setIsSaving(false);
    }
  };

  const copyOperatorId = () => {
    navigator.clipboard.writeText(profile.operator_id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const activeStatusCfg = dutyStatusConfig[profile.duty_status as DutyStatus] || dutyStatusConfig.ON_DUTY;

  return (
    <div className="min-h-screen bg-surface">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileMenuOpen}
        onMobileClose={closeMobile}
      />

      <div
        className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[260px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1400px] mx-auto space-y-6">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-text-primary">Operator Profile</h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
                  Verified Identity
                </span>
              </div>
              <p className="text-sm text-text-secondary mt-1">
                Command credentials, active emergency unit affiliation, and tactical telemetry.
              </p>
            </div>

            <button
              onClick={() => {
                setFormData({
                  full_name: profile.full_name || '',
                  phone: profile.phone || '',
                  callsign: profile.callsign || '',
                  bio: profile.bio || '',
                });
                setIsEditing(true);
              }}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 font-semibold text-xs transition-all shadow-sm"
            >
              <Edit3 className="w-3.5 h-3.5 text-primary" />
              Edit Profile
            </button>
          </div>

          {/* Hero Profile Card */}
          <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-100 shadow-sm relative overflow-hidden">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6 relative z-10">
              {/* Avatar + Main Details */}
              <div className="flex items-center gap-5">
                <div className="relative">
                  <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-3xl bg-gradient-to-br from-primary via-blue-600 to-indigo-700 text-white flex items-center justify-center font-black text-2xl sm:text-3xl shadow-lg shadow-primary/20">
                    {profile.avatar_initials || 'RV'}
                  </div>
                  <span
                    className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-white ring-2 ring-slate-100"
                    style={{ backgroundColor: activeStatusCfg.dot }}
                    title={`Duty Status: ${activeStatusCfg.label}`}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl sm:text-2xl font-extrabold text-text-primary">
                      {profile.full_name}
                    </h2>
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-50 text-primary border border-blue-100">
                      {profile.role}
                    </span>
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-700">
                      {profile.agency}
                    </span>
                  </div>

                  <p className="text-xs sm:text-sm text-text-secondary">
                    {profile.team_role || 'Incident Commander'} • {profile.team_name || 'NDRF 9th Battalion'}
                  </p>

                  <div className="flex items-center gap-3 pt-1">
                    {/* Operator ID chip with copy button */}
                    <button
                      onClick={copyOperatorId}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs font-mono font-medium text-slate-700 hover:bg-slate-100 transition-colors"
                      title="Click to copy Operator ID"
                    >
                      {profile.operator_id}
                      {copiedId ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-slate-400" />
                      )}
                    </button>

                    {profile.callsign && (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-100 text-xs font-mono font-semibold text-indigo-700">
                        <Radio className="w-3.5 h-3.5" />
                        {profile.callsign}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Duty Status Selector Controls */}
              <div className="bg-slate-50 p-3 rounded-2xl border border-slate-200/80 self-start sm:self-auto">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-2">
                  Duty Status
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {(['ON_DUTY', 'STANDBY', 'DEPLOYED', 'OFF_DUTY'] as DutyStatus[]).map((st) => {
                    const cfg = dutyStatusConfig[st];
                    const isSelected = profile.duty_status === st;
                    return (
                      <button
                        key={st}
                        onClick={() => handleDutyChange(st)}
                        className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5 ${
                          isSelected
                            ? 'bg-slate-900 text-white shadow-sm'
                            : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                        }`}
                      >
                        <span
                          className="w-2 h-2 rounded-full"
                          style={{ backgroundColor: isSelected ? '#FFFFFF' : cfg.dot }}
                        />
                        {cfg.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Telemetry & Details Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column (2 Cols): Contact, Team & Bio */}
            <div className="lg:col-span-2 space-y-6">
              {/* Tactical Contact Credentials */}
              <div className="bg-white rounded-3xl p-6 border border-slate-100 shadow-sm space-y-4">
                <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                  <Shield className="w-4 h-4 text-primary" />
                  Tactical &amp; Contact Credentials
                </h3>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
                      <Mail className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Official Email</span>
                      <span className="font-semibold text-slate-800">
                        {profile.email || 'commander@sih-indra.gov.in'}
                      </span>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
                      <Phone className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Emergency Hotline</span>
                      <span className="font-semibold text-slate-800">
                        {profile.phone || '+91 94311 02847'}
                      </span>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold">
                      <Radio className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Radio Callsign</span>
                      <span className="font-mono font-bold text-slate-800">
                        {profile.callsign || 'EAGLE-LEADER'}
                      </span>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center font-bold">
                      <Award className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Badge Number</span>
                      <span className="font-mono font-bold text-slate-800">
                        {profile.badge_number || 'NDRF-PAT-091'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Bio / Tactical Statement */}
                <div className="pt-2">
                  <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                    Command Assignment &amp; Scope
                  </span>
                  <p className="text-xs text-text-secondary leading-relaxed bg-slate-50 p-3.5 rounded-2xl border border-slate-100">
                    {profile.bio ||
                      'National Disaster Response Force commander leading urban inundation and river flood operations across Eastern India. Authorizes real-time deployment of quick response taskforces.'}
                  </p>
                </div>
              </div>

              {/* Assigned Disaster Response Unit Card */}
              <div className="bg-white rounded-3xl p-6 border border-slate-100 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <span className="text-xs font-semibold text-primary uppercase tracking-wider">
                    Assigned Response Unit
                  </span>
                  <h4 className="text-lg font-bold text-text-primary">
                    {profile.team_name || 'NDRF 9th Battalion - Flood Rescue Unit'}
                  </h4>
                  <p className="text-xs text-text-secondary">
                    Team Code: <strong className="font-mono text-slate-700">{profile.team_code || 'TEAM-NDRF-09'}</strong> • Role: <strong>{profile.team_role || 'Incident Commander'}</strong>
                  </p>
                </div>

                <Link
                  href="/teams"
                  className="px-4 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-all self-start sm:self-auto shadow-sm shadow-primary/20"
                >
                  View Team Hub &amp; Roster →
                </Link>
              </div>

              {/* Tactical Activity Ledger */}
              <div className="bg-white rounded-3xl p-6 border border-slate-100 shadow-sm space-y-4">
                <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                  <Activity className="w-4 h-4 text-primary" />
                  Recent Tactical Actions (Immutable Ledger)
                </h3>

                <div className="space-y-3 text-xs">
                  {[
                    { action: 'Dispatched NDRF 9th Battalion', target: 'WX-EV-28231827-A (Patna Urban Flood)', time: '20 mins ago', status: 'COMPLETED' },
                    { action: 'Approved High Confidence Receipt', target: 'WX-EV-77291044-B (Mumbai Rains)', time: '2 hours ago', status: 'VERIFIED' },
                    { action: 'Manual Override Confirmation', target: 'Signal SIG-10928 (River Gauge Anomaly)', time: '5 hours ago', status: 'LOGGED' },
                    { action: 'Shift Roll-Call & Personnel Inspection', target: 'Patna Regional Command Base', time: '12 hours ago', status: 'ON DUTY' },
                  ].map((act, i) => (
                    <div
                      key={i}
                      className="p-3 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between"
                    >
                      <div className="space-y-0.5">
                        <p className="font-bold text-slate-800">{act.action}</p>
                        <p className="text-slate-500 font-mono text-[11px]">{act.target}</p>
                      </div>
                      <div className="text-right">
                        <span className="font-semibold text-emerald-600 block text-[11px]">
                          {act.status}
                        </span>
                        <span className="text-[10px] text-slate-400">{act.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column: Performance Telemetry & RBAC Security */}
            <div className="space-y-6">
              {/* Telemetry Metrics */}
              <div className="bg-white rounded-3xl p-6 border border-slate-100 shadow-sm space-y-4">
                <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                  <Zap className="w-4 h-4 text-amber-500" />
                  Operational Telemetry
                </h3>

                <div className="space-y-3">
                  <div className="p-3.5 rounded-2xl bg-blue-50/60 border border-blue-100 flex items-center justify-between">
                    <div>
                      <span className="text-[11px] text-slate-500 block font-medium">Events Triaged</span>
                      <strong className="text-xl font-bold text-slate-900">
                        {profile.verified_events_triaged || 24}
                      </strong>
                    </div>
                    <FileCheck className="w-6 h-6 text-primary" />
                  </div>

                  <div className="p-3.5 rounded-2xl bg-purple-50/60 border border-purple-100 flex items-center justify-between">
                    <div>
                      <span className="text-[11px] text-slate-500 block font-medium">Audits Signed</span>
                      <strong className="text-xl font-bold text-slate-900">
                        {profile.audits_logged || 19}
                      </strong>
                    </div>
                    <Shield className="w-6 h-6 text-purple-600" />
                  </div>

                  <div className="p-3.5 rounded-2xl bg-emerald-50/60 border border-emerald-100 flex items-center justify-between">
                    <div>
                      <span className="text-[11px] text-slate-500 block font-medium">Bayesian Accuracy</span>
                      <strong className="text-xl font-bold text-emerald-700">
                        {profile.accuracy_rate || 96.8}%
                      </strong>
                    </div>
                    <CheckCircle2 className="w-6 h-6 text-emerald-600" />
                  </div>

                  <div className="p-3.5 rounded-2xl bg-amber-50/60 border border-amber-100 flex items-center justify-between">
                    <div>
                      <span className="text-[11px] text-slate-500 block font-medium">Avg Dispatch Response</span>
                      <strong className="text-xl font-bold text-amber-700">&lt; 12 mins</strong>
                    </div>
                    <Clock className="w-6 h-6 text-amber-600" />
                  </div>
                </div>
              </div>

              {/* Security & Clearance */}
              <div className="bg-white rounded-3xl p-6 border border-slate-100 shadow-sm space-y-4">
                <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                  <Lock className="w-4 h-4 text-primary" />
                  Security &amp; Clearance
                </h3>

                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                    <span className="text-slate-500">RBAC Role</span>
                    <span className="font-bold text-slate-800">{profile.role}</span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                    <span className="text-slate-500">Clearance Level</span>
                    <span className="font-bold text-emerald-600">Level 4 (Tactical Command)</span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                    <span className="text-slate-500">JWT Token Expiry</span>
                    <span className="font-mono text-slate-700">8h (HS256)</span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                    <span className="text-slate-500">Ledger Immutability</span>
                    <span className="font-semibold text-primary">SHA-256 Armed</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* ════════════════════════ EDIT PROFILE MODAL ════════════════════════ */}
      <AnimatePresence>
        {isEditing && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.2 }}
              className="bg-white rounded-3xl shadow-2xl max-w-lg w-full overflow-hidden border border-slate-100"
            >
              <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                <h3 className="text-lg font-bold text-text-primary">Edit Operator Profile</h3>
                <button
                  onClick={() => setIsEditing(false)}
                  className="p-2 rounded-xl hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSaveProfile} className="p-6 space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={formData.full_name}
                    onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                    className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Emergency Hotline / Phone
                  </label>
                  <input
                    type="text"
                    value={formData.phone}
                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                    className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Radio Frequency Callsign
                  </label>
                  <input
                    type="text"
                    value={formData.callsign}
                    onChange={(e) => setFormData({ ...formData, callsign: e.target.value.toUpperCase() })}
                    className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Operational Bio / Mission Scope
                  </label>
                  <textarea
                    value={formData.bio}
                    onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                    rows={3}
                    className="w-full p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-none"
                  />
                </div>

                <div className="pt-2 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsEditing(false)}
                    className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSaving}
                    className="px-5 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-bold transition-all shadow-sm shadow-primary/20 flex items-center gap-1.5"
                  >
                    <Save className="w-3.5 h-3.5" />
                    {isSaving ? 'Saving...' : 'Save Changes'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
