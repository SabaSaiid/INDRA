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
  ChevronRight,
  ExternalLink,
  Users,
  Building2,
  Sparkles,
  AlertCircle,
  LogIn,
} from 'lucide-react';
import Link from 'next/link';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import SignInDialog from '@/components/SignInDialog';
import {
  type UserProfile,
  type DutyStatus,
  dutyStatusConfig,
  type TeamItem,
  ROLE_CAPABILITIES,
  LEDGER_IMMUTABILITY,
} from '@/lib/ui-config';
import { useOperatorProfile } from '@/lib/useOperatorProfile';
import { roleLabel, sessionExpiryLabel } from '@/lib/auth';
import { fetchTeams } from '@/lib/api';
import { useSidebar } from '@/lib/useSidebar';
import { useTranslation } from '@/lib/i18n/useTranslation';

export default function ProfilePage() {
  const { t } = useTranslation();
  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  const {
    session,
    profile,
    profileError,
    updateDuty,
    updateProfile,
    isUpdatingStatus,
    isSavingProfile,
  } = useOperatorProfile();
  // Signed out there is no profile to show, and none is invented: the page
  // offers sign-in instead.
  const [signInOpen, setSignInOpen] = useState(false);

  // Edit Modal State
  // The operational-unit picker lists the real roster. It used to list a
  // hardcoded array of teams, so an operator could be "assigned" to a unit that
  // does not exist in the database.
  const [teams, setTeams] = useState<TeamItem[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchTeams()
      .then((rows) => { if (!cancelled) setTeams(rows); })
      .catch(() => { if (!cancelled) setTeams([]); });
    return () => { cancelled = true; };
  }, []);

  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState<Partial<UserProfile>>({});
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [toastTone, setToastTone] = useState<'ok' | 'error'>('ok');
  // Why the last save in this edit session was refused. Cleared when the form
  // opens, so an old failure is never shown against a new edit.
  const [formError, setFormError] = useState<string | null>(null);

  // Copy-to-clipboard state tracking
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const copyToClipboard = (text: string | undefined, fieldName: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleOpenEdit = () => {
    if (!profile) return;
    setFormData({
      full_name: profile.full_name || '',
      email: profile.email || '',
      phone: profile.phone || '',
      callsign: profile.callsign || '',
      agency: profile.agency || '',
      badge_number: profile.badge_number || '',
      team_name: profile.team_name || '',
      team_code: profile.team_code || '',
      team_role: profile.team_role || '',
      bio: profile.bio || '',
    });
    setFormError(null);
    setIsEditing(true);
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateProfile(formData);
      setIsEditing(false);
      setToastTone('ok');
      setToastMessage('Profile saved');
      setTimeout(() => setToastMessage(null), 4000);
    } catch (err) {
      // Keep the form open with the operator's edits, and say why it failed.
      console.error('Failed to save profile', err);
      const reason = err instanceof Error ? err.message : 'the backend refused the update';
      setFormError(reason);
      setToastTone('error');
      setToastMessage(`Not saved — ${reason}`);
      setTimeout(() => setToastMessage(null), 6000);
    }
  };

  // No dot for a status the profile does not carry: never a default 'On Duty'.
  const activeStatusCfg = profile ? dutyStatusConfig[profile.duty_status as DutyStatus] ?? null : null;
  // Real ledger actions, real counts, real RBAC.
  const currentActivities = profile?.recent_activities ?? [];
  const currentTelemetry = [
    {
      label: 'Events triaged',
      value: profile?.verified_events_triaged ?? 0,
      color: 'blue',
      iconName: 'FileCheck',
      sublabel: 'approvals and rejections in the ledger',
    },
    {
      label: 'Ledger entries authored',
      value: profile?.audits_logged ?? 0,
      color: 'purple',
      iconName: 'Shield',
      sublabel: 'hash-chained audit records',
    },
  ];
  const roleKey = String(profile?.role ?? '').toUpperCase();
  // As the backend stores it, with underscores read as spaces: 'SDMA_BIHAR' → 'SDMA BIHAR'.
  const agencyDisplay = (profile?.agency || '').replace(/_/g, ' ');
  const currentCapabilities = ROLE_CAPABILITIES[roleKey] ?? [];

  // Icon mapping for dynamic telemetry
  const renderTelemetryIcon = (iconName: string) => {
    switch (iconName) {
      case 'FileCheck':
        return <FileCheck className="w-5 h-5 text-primary" />;
      case 'Shield':
        return <Shield className="w-5 h-5 text-purple-600" />;
      case 'CheckCircle2':
        return <CheckCircle2 className="w-5 h-5 text-emerald-600" />;
      case 'Clock':
        return <Clock className="w-5 h-5 text-amber-600" />;
      case 'Activity':
        return <Activity className="w-5 h-5 text-blue-600" />;
      case 'Zap':
        return <Zap className="w-5 h-5 text-amber-500" />;
      case 'Users':
        return <Users className="w-5 h-5 text-purple-600" />;
      case 'Award':
        return <Award className="w-5 h-5 text-amber-600" />;
      default:
        return <Zap className="w-5 h-5 text-primary" />;
    }
  };

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
          sidebarCollapsed ? 'md:ml-[68px]' : 'md:ml-[272px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1400px] mx-auto space-y-6">
          {/* Toast Notification Banner */}
          <AnimatePresence>
            {toastMessage && (
              <motion.div
                initial={{ opacity: 0, y: -12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.98 }}
                className="flex items-center justify-between p-3.5 px-5 rounded-2xl bg-slate-900 text-white shadow-xl shadow-slate-900/10 border border-slate-800"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${
                      toastTone === 'error' ? 'bg-rose-500' : 'bg-emerald-400 animate-ping'
                    }`}
                  />
                  <span className="text-xs font-semibold tracking-wide">{toastMessage}</span>
                </div>
                <button
                  onClick={() => setToastMessage(null)}
                  className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Page Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-2xl font-black text-text-primary tracking-tight">{t('nav.operator')}</h1>
              </div>
              <p className="text-sm text-text-secondary mt-1">
                Identity, role, duty status and the actions this operator has taken in the audit ledger.
              </p>
            </div>

            {profile && (
              <button
                onClick={handleOpenEdit}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 font-bold text-xs transition-all shadow-sm self-start sm:self-auto hover:border-slate-300"
              >
                <Edit3 className="w-3.5 h-3.5 text-primary" />
                Edit Profile
              </button>
            )}
          </div>

          {!session ? (
            <div className="bg-white rounded-3xl p-8 border border-slate-200/80 shadow-sm flex flex-col items-center text-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-500 flex items-center justify-center">
                <User className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-text-primary">Sign in to see your operator profile</h2>
              <p className="text-xs text-text-secondary max-w-md">
                Your identity, role, duty status and ledger activity come from your operator account in
                the backend. The dashboards stay open to read without signing in.
              </p>
              <button
                onClick={() => setSignInOpen(true)}
                className="mt-1 inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold transition-all shadow-sm"
              >
                <LogIn className="w-3.5 h-3.5" />
                Sign in
              </button>
            </div>
          ) : !profile ? (
            <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm text-sm">
              {profileError ? (
                <p role="alert" className="flex items-center gap-2 text-rose-600 font-semibold">
                  <AlertCircle className="w-4 h-4" />
                  Your profile could not be loaded:{' '}
                  {profileError instanceof Error ? profileError.message : 'the backend did not answer'}
                </p>
              ) : (
                <p className="text-slate-400">Loading your profile…</p>
              )}
            </div>
          ) : (
            <>
            {/* ═══════════════════ HERO OPERATOR PROFILE CARD ═══════════════════ */}
            <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200/80 shadow-sm relative overflow-hidden">
              <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-6 relative z-10">
                {/* Avatar + Main Identity Details */}
                <div className="flex flex-col sm:flex-row sm:items-center gap-5">
                  <div className="relative self-start sm:self-auto">
                    <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-3xl bg-gradient-to-br from-primary via-blue-600 to-indigo-700 text-white flex items-center justify-center font-black text-2xl sm:text-3xl shadow-lg shadow-primary/20">
                      {profile.avatar_initials || '—'}
                    </div>
                    {activeStatusCfg && (
                      <span
                        className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-white ring-2 ring-slate-100"
                        style={{ backgroundColor: activeStatusCfg.dot }}
                        title={`Duty Status: ${activeStatusCfg.label}`}
                      />
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-xl sm:text-2xl font-extrabold text-text-primary">
                        {profile.full_name}
                      </h2>
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-50 text-primary border border-blue-100">
                        {profile.role}
                      </span>
                      {agencyDisplay && (
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-700">
                          {agencyDisplay}
                        </span>
                      )}
                    </div>

                    <p className="text-xs sm:text-sm text-text-secondary font-medium">
                      {[profile.team_role, profile.team_name].filter(Boolean).join(' • ') || 'No unit assigned'}
                    </p>

                    <div className="flex flex-wrap items-center gap-2.5 pt-1.5">
                      {/* Operator ID chip with copy button */}
                      <button
                        onClick={() => copyToClipboard(profile.operator_id, 'id')}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs font-mono font-medium text-slate-700 hover:bg-slate-100 transition-colors"
                        title="Click to copy Operator ID"
                      >
                        <span>{profile.operator_id}</span>
                        {copiedField === 'id' ? (
                          <Check className="w-3.5 h-3.5 text-emerald-600" />
                        ) : (
                          <Copy className="w-3.5 h-3.5 text-slate-400" />
                        )}
                      </button>

                      {/* Radio Callsign chip */}
                      {profile.callsign ? (
                        <button
                          onClick={() => copyToClipboard(profile.callsign, 'callsign')}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-100 text-xs font-mono font-bold text-indigo-700 hover:bg-indigo-100 transition-colors"
                          title="Click to copy Radio Callsign"
                        >
                          <Radio className="w-3.5 h-3.5" />
                          <span>{profile.callsign}</span>
                          {copiedField === 'callsign' ? (
                            <Check className="w-3 h-3 text-emerald-600" />
                          ) : (
                            <Copy className="w-3 h-3 text-indigo-400" />
                          )}
                        </button>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs font-mono text-slate-400">
                          <Radio className="w-3.5 h-3.5 text-slate-300" />
                          No callsign
                        </span>
                      )}

                      {/* Email quick copy */}
                      {profile.email && (
                        <button
                          onClick={() => copyToClipboard(profile.email, 'email')}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600 hover:bg-slate-100 transition-colors"
                          title="Click to copy email"
                        >
                          <Mail className="w-3 h-3 text-slate-400" />
                          <span className="truncate max-w-[180px]">{profile.email}</span>
                          {copiedField === 'email' && <Check className="w-3 h-3 text-emerald-600" />}
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Duty Status Selector Controls */}
                <div className="bg-slate-50/80 p-3.5 rounded-2xl border border-slate-200/80 self-start xl:self-auto space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">
                      Operational Duty Status
                    </span>
                    {isUpdatingStatus && (
                      <span className="text-[10px] text-primary animate-pulse font-medium">Syncing...</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {(['ON_DUTY', 'STANDBY', 'DEPLOYED', 'OFF_DUTY'] as DutyStatus[]).map((st) => {
                      const cfg = dutyStatusConfig[st];
                      const isSelected = profile.duty_status === st;
                      return (
                        <button
                          key={st}
                          onClick={() => updateDuty(st)}
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

            {/* ═══════════════════ MAIN DETAILS & TELEMETRY GRID ═══════════════════ */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column (2 Cols): Credentials, Team Hub & Tactical Activity Ledger */}
              <div className="lg:col-span-2 space-y-6">
                {/* Tactical & Contact Credentials */}
                <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                      <Shield className="w-4 h-4 text-primary" />
                      Tactical &amp; Contact Credentials
                    </h3>
                    <button
                      onClick={handleOpenEdit}
                      className="text-xs text-primary hover:underline font-semibold flex items-center gap-1"
                    >
                      Edit Credentials
                    </button>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                    {/* Email */}
                    <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold shrink-0">
                          <Mail className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-slate-400 block text-[11px]">Email</span>
                          <span className={`truncate block ${profile.email ? 'font-semibold text-slate-800' : 'text-slate-400'}`}>
                            {profile.email || 'Not on record'}
                          </span>
                        </div>
                      </div>
                      {profile.email && (
                        <button
                          onClick={() => copyToClipboard(profile.email, 'cred-email')}
                          className="p-1.5 rounded-lg hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors shrink-0"
                          title="Copy Email"
                        >
                          {copiedField === 'cred-email' ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                    </div>

                    {/* Phone */}
                    <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold shrink-0">
                          <Phone className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-slate-400 block text-[11px]">Phone</span>
                          <span className={`truncate block ${profile.phone ? 'font-semibold text-slate-800' : 'text-slate-400'}`}>
                            {profile.phone || 'Not on record'}
                          </span>
                        </div>
                      </div>
                      {profile.phone && (
                        <button
                          onClick={() => copyToClipboard(profile.phone, 'cred-phone')}
                          className="p-1.5 rounded-lg hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors shrink-0"
                          title="Copy Phone"
                        >
                          {copiedField === 'cred-phone' ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                    </div>

                    {/* Callsign */}
                    <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold shrink-0">
                          <Radio className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-slate-400 block text-[11px]">Radio Callsign</span>
                          <span className={`truncate block ${profile.callsign ? 'font-mono font-bold text-slate-800' : 'text-slate-400'}`}>
                            {profile.callsign || 'No callsign'}
                          </span>
                        </div>
                      </div>
                      {profile.callsign && (
                        <button
                          onClick={() => copyToClipboard(profile.callsign, 'cred-callsign')}
                          className="p-1.5 rounded-lg hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors shrink-0"
                          title="Copy Callsign"
                        >
                          {copiedField === 'cred-callsign' ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                    </div>

                    {/* Badge Number */}
                    <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center font-bold shrink-0">
                          <Award className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-slate-400 block text-[11px]">Badge Number</span>
                          <span className={`truncate block ${profile.badge_number ? 'font-mono font-bold text-slate-800' : 'text-slate-400'}`}>
                            {profile.badge_number || 'Not on record'}
                          </span>
                        </div>
                      </div>
                      {profile.badge_number && (
                        <button
                          onClick={() => copyToClipboard(profile.badge_number, 'cred-badge')}
                          className="p-1.5 rounded-lg hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors shrink-0"
                          title="Copy Badge Number"
                        >
                          {copiedField === 'cred-badge' ? (
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Bio / Command Assignment Statement */}
                  <div className="pt-2">
                    <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                      Command Assignment &amp; Mission Scope
                    </span>
                    <p
                      className={`text-xs leading-relaxed bg-slate-50 p-4 rounded-2xl border border-slate-100 ${
                        profile.bio ? 'text-text-secondary' : 'text-slate-400'
                      }`}
                    >
                      {profile.bio || 'No bio on record'}
                    </p>
                  </div>
                </div>

                {/* Assigned response unit, only when the profile names one */}
                {(profile.team_id || profile.team_code) && (
                  <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="space-y-1.5">
                      <span className="text-xs font-bold text-primary uppercase tracking-wider">
                        Assigned Response Unit
                      </span>
                      <h4 className="text-lg font-bold text-text-primary">
                        {profile.team_name || profile.team_code}
                      </h4>
                      <p className="text-xs text-text-secondary">
                        {profile.team_code && (
                          <>
                            Unit Code: <strong className="font-mono text-slate-800">{profile.team_code}</strong>
                          </>
                        )}
                        {profile.team_code && profile.team_role && ' • '}
                        {profile.team_role && (
                          <>
                            Role in unit: <strong className="text-slate-800">{profile.team_role}</strong>
                          </>
                        )}
                      </p>
                    </div>

                    {profile.team_code && (
                      <Link
                        href={`/teams?search=${encodeURIComponent(profile.team_code)}`}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-bold transition-all self-start sm:self-auto shadow-sm shadow-primary/20 shrink-0"
                      >
                        <Users className="w-3.5 h-3.5" />
                        View Team in Roster →
                      </Link>
                    )}
                  </div>
                )}

                {/* Dynamic Role-Specific Tactical Activity Ledger */}
                <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
                  <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                    <Activity className="w-4 h-4 text-primary" />
                    Activity Ledger (SHA-256 Hash Chain)
                  </h3>

                  <div className="space-y-3 text-xs">
                    {currentActivities.length === 0 && (
                      <p className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 text-slate-400">
                        No ledger entries by this operator yet.
                      </p>
                    )}
                    {currentActivities.map((act) => {
                      const isDispatched = act.status === 'DISPATCHED' || act.status === 'COMPLETED';
                      const isVerified = act.status === 'VERIFIED';
                      const isQuarantined = act.status === 'QUARANTINED';
                      return (
                        <div
                          key={act.id}
                          className="p-3.5 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-between hover:bg-slate-100/60 transition-colors"
                        >
                          <div className="space-y-1">
                            <p className="font-bold text-slate-900 flex items-center gap-1.5">
                              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                              {act.action}
                            </p>
                            <p className="text-slate-500 font-mono text-[11px] pl-3">{act.target}</p>
                          </div>
                          <div className="text-right shrink-0">
                            <span
                              className={`font-bold block text-[11px] ${
                                isQuarantined
                                  ? 'text-amber-600'
                                  : isVerified
                                  ? 'text-blue-600'
                                  : isDispatched
                                  ? 'text-emerald-600'
                                  : 'text-slate-700'
                              }`}
                            >
                              {act.status}
                            </span>
                            <span className="text-[10px] text-slate-400">{act.time}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="pt-2 text-[11px] text-slate-400 border-t border-slate-100">
                    <Link href="/admin" className="hover:text-slate-700 hover:underline">
                      The chain&apos;s verification status is on Admin Command →
                    </Link>
                  </div>
                </div>
              </div>

              {/* Right Column: Dynamic Role Telemetry & RBAC Security Matrix */}
              <div className="space-y-6">
                {/* Role-Tailored Operational Telemetry */}
                <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
                  <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                    <Zap className="w-4 h-4 text-amber-500" />
                    Operational Telemetry
                  </h3>

                  <div className="space-y-3">
                    {currentTelemetry.map((metric, idx) => {
                      const bgClass =
                        metric.color === 'purple'
                          ? 'bg-purple-50/70 border-purple-100'
                          : metric.color === 'emerald'
                          ? 'bg-emerald-50/70 border-emerald-100'
                          : metric.color === 'amber'
                          ? 'bg-amber-50/70 border-amber-100'
                          : 'bg-blue-50/70 border-blue-100';

                      return (
                        <div
                          key={idx}
                          className={`p-4 rounded-2xl border flex items-center justify-between ${bgClass}`}
                        >
                          <div>
                            <span className="text-[11px] text-slate-500 block font-medium">
                              {metric.label}
                            </span>
                            <strong className="text-xl font-extrabold text-slate-900 tracking-tight">
                              {metric.value}
                            </strong>
                            {metric.sublabel && (
                              <span className="text-[10px] text-slate-400 block mt-0.5">
                                {metric.sublabel}
                              </span>
                            )}
                          </div>
                          <div className="p-2.5 rounded-xl bg-white shadow-sm border border-slate-100">
                            {renderTelemetryIcon(metric.iconName)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Dynamic Security, Clearance & RBAC Matrix */}
                <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-text-primary flex items-center gap-2">
                      <Lock className="w-4 h-4 text-primary" />
                      Security &amp; RBAC Clearance
                    </h3>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                      {profile.operator_id}
                    </span>
                  </div>

                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                      <span className="text-slate-500 font-medium">Role</span>
                      <span className="font-bold text-slate-800">{roleLabel(profile.role)}</span>
                    </div>
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                      <span className="text-slate-500 font-medium">Agency</span>
                      <span className="font-bold text-slate-800">{agencyDisplay || 'Not on record'}</span>
                    </div>
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                      <span className="text-slate-500 font-medium">Session expires</span>
                      <span className="font-mono text-slate-700">{sessionExpiryLabel(session)}</span>
                    </div>
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50">
                      <span className="text-slate-500 font-medium">Ledger Immutability</span>
                      <span className="font-semibold text-emerald-700">{LEDGER_IMMUTABILITY}</span>
                    </div>
                  </div>

                  {/* RBAC Permissions Capability Matrix */}
                  <div className="pt-2 border-t border-slate-100">
                    <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-2.5">
                      Authorized Capabilities
                    </span>
                    <div className="space-y-2">
                      {currentCapabilities.map((perm) => (
                        <div
                          key={perm.label}
                          className="flex items-center justify-between p-2 rounded-xl bg-slate-50/70 border border-slate-100 text-xs"
                        >
                          <div className="min-w-0 pr-2">
                            <p className="font-semibold text-slate-800 truncate">{perm.label}</p>
                          </div>
                          {perm.granted ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 font-bold text-[10px] shrink-0">
                              <Check className="w-3 h-3" />
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-200 text-slate-600 font-medium text-[10px] shrink-0">
                              <Lock className="w-3 h-3" />
                              Restricted
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            </>
          )}
        </main>
      </div>

      {/* ════════════════════════ EDIT PROFILE MODAL ════════════════════════ */}
      <AnimatePresence>
        {isEditing && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm overflow-y-auto">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.2 }}
              className="bg-white rounded-3xl shadow-2xl max-w-xl w-full overflow-hidden border border-slate-100 my-8"
            >
              <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/70">
                <div>
                  <h3 className="text-lg font-bold text-text-primary">Edit Operator Profile</h3>
                  <p className="text-xs text-text-secondary mt-0.5">
                    Saved to your operator record.
                  </p>
                </div>
                <button
                  onClick={() => setIsEditing(false)}
                  className="p-2 rounded-xl hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSaveProfile} className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Full Name */}
                  <div className="sm:col-span-2">
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Full Name
                    </label>
                    <input
                      type="text"
                      value={formData.full_name || ''}
                      onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      required
                    />
                  </div>

                  {/* Email */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Email
                    </label>
                    <input
                      type="email"
                      value={formData.email || ''}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Phone */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Phone
                    </label>
                    <input
                      type="text"
                      value={formData.phone || ''}
                      onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Radio Callsign */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Radio Callsign
                    </label>
                    <input
                      type="text"
                      value={formData.callsign || ''}
                      onChange={(e) => setFormData({ ...formData, callsign: e.target.value.toUpperCase() })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Badge Number */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Badge Number
                    </label>
                    <input
                      type="text"
                      value={formData.badge_number || ''}
                      onChange={(e) => setFormData({ ...formData, badge_number: e.target.value.toUpperCase() })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Agency */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Agency / Department
                    </label>
                    <input
                      type="text"
                      value={formData.agency || ''}
                      onChange={(e) => setFormData({ ...formData, agency: e.target.value })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Command / Team Role */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Command Role in Unit
                    </label>
                    <input
                      type="text"
                      value={formData.team_role || ''}
                      onChange={(e) => setFormData({ ...formData, team_role: e.target.value })}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>

                  {/* Assigned Team Dropdown */}
                  <div className="sm:col-span-2">
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Assigned Operational Unit
                    </label>
                    <select
                      value={formData.team_code || ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        if (!val) {
                          setFormData({
                            ...formData,
                            team_code: '',
                            team_name: '',
                          });
                        } else {
                          const selected = teams.find((t) => t.team_code === val);
                          if (selected) {
                            setFormData({
                              ...formData,
                              team_code: selected.team_code,
                              team_name: selected.name,
                            });
                          }
                        }
                      }}
                      className="w-full h-10 px-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    >
                      <option value="">No unit assigned</option>
                      {teams.map((team) => (
                        <option key={team.id} value={team.team_code}>
                          {team.team_code} — {team.name} ({team.city}, {team.agency})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Bio */}
                  <div className="sm:col-span-2">
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Operational Bio / Mission Scope
                    </label>
                    <textarea
                      value={formData.bio || ''}
                      onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                      rows={3}
                      className="w-full p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-none"
                    />
                  </div>
                </div>

                {formError && !isSavingProfile && (
                  <p role="alert" className="text-xs font-semibold text-rose-600">
                    Not saved — {formError}
                  </p>
                )}
                <div className="pt-3 flex items-center justify-end gap-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={() => setIsEditing(false)}
                    className="px-4 py-2.5 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSavingProfile}
                    className="px-5 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-bold transition-all shadow-sm shadow-primary/20 flex items-center gap-2"
                  >
                    <Save className="w-3.5 h-3.5" />
                    {isSavingProfile ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <SignInDialog open={signInOpen} onClose={() => setSignInOpen(false)} />
    </div>
  );
}
