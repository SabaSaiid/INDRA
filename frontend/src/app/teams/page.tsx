'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSearchParams } from 'next/navigation';
import {
  Users,
  Shield,
  Radio,
  MapPin,
  Phone,
  Search,
  Award,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ChevronRight,
  X,
  ExternalLink,
  Zap,
  Filter,
  ArrowRight,
  Activity,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import {
  type TeamItem,
  type TeamMember,
  type HackathonTeamData,
  mockTeams,
  mockSixthSenseTeam,
  teamAgencyConfig,
  dutyStatusConfig,
} from '@/lib/mock-data';
import { fetchTeams, fetchHackathonTeam, assignTeamToEvent } from '@/lib/api';
import { fadeIn, staggerContainer } from '@/lib/motion';
import { useSidebar } from '@/lib/useSidebar';

function TeamsContent() {
  const searchParams = useSearchParams();
  const initialTab = searchParams.get('tab') === 'hackathon' ? 'hackathon' : 'operations';

  const [activeTab, setActiveTab] = useState<'operations' | 'hackathon'>(initialTab);

  const {
    collapsed: sidebarCollapsed,
    toggle: toggleSidebar,
    mobileOpen: mobileMenuOpen,
    openMobile,
    closeMobile,
  } = useSidebar();

  // Teams state
  const [teams, setTeams] = useState<TeamItem[]>(mockTeams);
  const [hackathonTeam, setHackathonTeam] = useState<HackathonTeamData>(mockSixthSenseTeam);
  const [selectedTeam, setSelectedTeam] = useState<TeamItem | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [agencyFilter, setAgencyFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [isUpdatingDispatch, setIsUpdatingDispatch] = useState(false);

  // Fetch teams & hackathon data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [teamsData, sihData] = await Promise.all([
          fetchTeams(),
          fetchHackathonTeam(),
        ]);
        if (!cancelled) {
          if (teamsData && teamsData.length > 0) setTeams(teamsData);
          if (sihData) setHackathonTeam(sihData);
        }
      } catch (err) {
        console.warn('Using fallback teams data', err);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Filtered operational teams
  const filteredTeams = useMemo(() => {
    return teams.filter((team) => {
      const matchesSearch =
        team.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        team.city.toLowerCase().includes(searchQuery.toLowerCase()) ||
        team.lead_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        team.team_code.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesAgency = agencyFilter === 'ALL' || team.agency.toUpperCase() === agencyFilter;
      const matchesStatus = statusFilter === 'ALL' || team.status.toUpperCase() === statusFilter;

      return matchesSearch && matchesAgency && matchesStatus;
    });
  }, [teams, searchQuery, agencyFilter, statusFilter]);

  // Statistics
  const stats = useMemo(() => {
    const totalTeams = teams.length;
    const deployedTeams = teams.filter((t) => t.status === 'DEPLOYED').length;
    const totalResponders = teams.reduce((acc, t) => acc + (t.members_count || 12), 0);
    const standbyUnits = teams.filter((t) => t.status === 'STANDBY').length;
    return { totalTeams, deployedTeams, totalResponders, standbyUnits };
  }, [teams]);

  // Toggle dispatch state for a team
  const handleToggleDispatch = async (team: TeamItem) => {
    setIsUpdatingDispatch(true);
    const isCurrentlyDeployed = team.status === 'DEPLOYED';
    const newEventId = isCurrentlyDeployed ? null : 'WX-EV-28231827-A';

    try {
      await assignTeamToEvent(team.id, newEventId);
      setTeams((prev) =>
        prev.map((t) =>
          t.id === team.id
            ? {
                ...t,
                status: isCurrentlyDeployed ? 'AVAILABLE' : 'DEPLOYED',
                assigned_event_code: isCurrentlyDeployed ? null : 'WX-EV-28231827-A',
                assigned_event_type: isCurrentlyDeployed ? null : 'URBAN_FLOOD',
              }
            : t
        )
      );
      if (selectedTeam && selectedTeam.id === team.id) {
        setSelectedTeam((prev) =>
          prev
            ? {
                ...prev,
                status: isCurrentlyDeployed ? 'AVAILABLE' : 'DEPLOYED',
                assigned_event_code: isCurrentlyDeployed ? null : 'WX-EV-28231827-A',
              }
            : null
        );
      }
    } catch (err) {
      console.error('Failed to toggle dispatch', err);
    } finally {
      setIsUpdatingDispatch(false);
    }
  };

  const openTeamDetail = (team: TeamItem) => {
    setSelectedTeam(team);
    setIsDetailOpen(true);
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
          sidebarCollapsed ? 'md:ml-[72px]' : 'md:ml-[260px]'
        }`}
      >
        <Topbar onMobileMenuOpen={openMobile} />

        <main className="p-4 lg:p-6 max-w-[1600px] mx-auto space-y-6">
          {/* Header & Tabs */}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-text-primary">Teams &amp; Response Units</h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800">
                  Command Hub
                </span>
              </div>
              <p className="text-sm text-text-secondary mt-1">
                Deploy and monitor disaster response taskforces, field units, and SIH project personnel.
              </p>
            </div>

            {/* Tab Pills */}
            <div className="flex items-center p-1 bg-white rounded-2xl border border-slate-200/80 shadow-sm self-start">
              <button
                onClick={() => setActiveTab('operations')}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
                  activeTab === 'operations'
                    ? 'bg-primary text-white shadow-sm'
                    : 'text-slate-600 hover:text-text-primary'
                }`}
              >
                <Shield className="w-3.5 h-3.5" />
                Disaster Response Units ({teams.length})
              </button>
              <button
                onClick={() => setActiveTab('hackathon')}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
                  activeTab === 'hackathon'
                    ? 'bg-primary text-white shadow-sm'
                    : 'text-slate-600 hover:text-text-primary'
                }`}
              >
                <Award className="w-3.5 h-3.5 text-amber-300" />
                Team Sixth Sense (SIH Roster)
              </button>
            </div>
          </div>

          {/* KPI Stats Bar */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white rounded-2xl p-4 border border-slate-100 shadow-sm flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
                <Users className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-text-muted font-medium">Total Emergency Teams</p>
                <h3 className="text-xl font-bold text-text-primary">{stats.totalTeams} Units</h3>
              </div>
            </div>

            <div className="bg-white rounded-2xl p-4 border border-slate-100 shadow-sm flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center font-bold">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-text-muted font-medium">Deployed in Field</p>
                <h3 className="text-xl font-bold text-text-primary">{stats.deployedTeams} Units</h3>
              </div>
            </div>

            <div className="bg-white rounded-2xl p-4 border border-slate-100 shadow-sm flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center font-bold">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-text-muted font-medium">Standby Fast-Response</p>
                <h3 className="text-xl font-bold text-text-primary">{stats.standbyUnits} Units</h3>
              </div>
            </div>

            <div className="bg-white rounded-2xl p-4 border border-slate-100 shadow-sm flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-text-muted font-medium">Total Field Responders</p>
                <h3 className="text-xl font-bold text-text-primary">~{stats.totalResponders} Personnel</h3>
              </div>
            </div>
          </div>

          {/* ════════════════════════ TAB 1: OPERATIONS ════════════════════════ */}
          {activeTab === 'operations' && (
            <motion.div
              variants={fadeIn}
              initial="hidden"
              animate="visible"
              className="space-y-6"
            >
              {/* Filter and Search Bar */}
              <div className="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
                {/* Search */}
                <div className="relative flex-1 max-w-md">
                  <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search by team, commander, or city..."
                    className="w-full h-10 pl-10 pr-4 rounded-xl bg-slate-50 border border-slate-200 text-sm text-text-primary placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                  />
                </div>

                {/* Agency and Status Chips */}
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1 bg-slate-50 p-1 rounded-xl border border-slate-200/70 text-xs">
                    <span className="text-slate-400 pl-2 pr-1 font-medium">Agency:</span>
                    {['ALL', 'NDRF', 'SDRF', 'IMD', 'CWC'].map((ag) => (
                      <button
                        key={ag}
                        onClick={() => setAgencyFilter(ag)}
                        className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                          agencyFilter === ag
                            ? 'bg-white text-primary shadow-sm border border-slate-200'
                            : 'text-slate-600 hover:text-text-primary'
                        }`}
                      >
                        {ag}
                      </button>
                    ))}
                  </div>

                  <div className="flex items-center gap-1 bg-slate-50 p-1 rounded-xl border border-slate-200/70 text-xs">
                    <span className="text-slate-400 pl-2 pr-1 font-medium">Status:</span>
                    {['ALL', 'DEPLOYED', 'AVAILABLE', 'STANDBY'].map((st) => (
                      <button
                        key={st}
                        onClick={() => setStatusFilter(st)}
                        className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                          statusFilter === st
                            ? 'bg-white text-primary shadow-sm border border-slate-200'
                            : 'text-slate-600 hover:text-text-primary'
                        }`}
                      >
                        {st === 'ALL' ? 'All' : st.charAt(0) + st.slice(1).toLowerCase()}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Grid of Team Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {filteredTeams.map((team) => {
                  const agCfg = teamAgencyConfig[team.agency] || teamAgencyConfig.NDRF;
                  const isDeployed = team.status === 'DEPLOYED';

                  return (
                    <div
                      key={team.id}
                      className="bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md transition-all duration-200 p-5 flex flex-col justify-between"
                    >
                      <div>
                        {/* Top Row: Agency Badge & Status */}
                        <div className="flex items-center justify-between gap-2 mb-3">
                          <span
                            className="px-2.5 py-1 rounded-lg text-xs font-bold border"
                            style={{
                              color: agCfg.color,
                              backgroundColor: agCfg.bg,
                              borderColor: agCfg.border,
                            }}
                          >
                            {team.agency}
                          </span>

                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                              isDeployed
                                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                                : team.status === 'STANDBY'
                                ? 'bg-amber-50 text-amber-700 border border-amber-200'
                                : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                            }`}
                          >
                            <span
                              className={`w-2 h-2 rounded-full ${
                                isDeployed
                                  ? 'bg-rose-500 animate-pulse'
                                  : team.status === 'STANDBY'
                                  ? 'bg-amber-500'
                                  : 'bg-emerald-500'
                              }`}
                            />
                            {team.status}
                          </span>
                        </div>

                        {/* Title & Code */}
                        <h3 className="text-base font-bold text-text-primary leading-snug">
                          {team.name}
                        </h3>
                        <p className="text-[11px] font-mono text-slate-400 mt-0.5">
                          {team.team_code}
                        </p>

                        {/* Specialization */}
                        {team.specialization && (
                          <div className="mt-3">
                            <span className="inline-block text-[11px] px-2.5 py-1 rounded-lg bg-slate-50 text-slate-600 border border-slate-100">
                              {team.specialization}
                            </span>
                          </div>
                        )}

                        {/* Metadata Rows */}
                        <div className="mt-4 space-y-2 text-xs text-text-secondary">
                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-slate-400">
                              <MapPin className="w-3.5 h-3.5" /> Base Location:
                            </span>
                            <span className="font-medium text-slate-700">
                              {team.city}, {team.state}
                            </span>
                          </div>

                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-slate-400">
                              <Shield className="w-3.5 h-3.5" /> Team Commander:
                            </span>
                            <span className="font-medium text-slate-700 truncate max-w-[170px]">
                              {team.lead_name}
                            </span>
                          </div>

                          {team.radio_callsign && (
                            <div className="flex items-center justify-between">
                              <span className="flex items-center gap-1.5 text-slate-400">
                                <Radio className="w-3.5 h-3.5" /> Callsign:
                              </span>
                              <span className="font-mono font-semibold text-primary">
                                {team.radio_callsign}
                              </span>
                            </div>
                          )}

                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-slate-400">
                              <Users className="w-3.5 h-3.5" /> Unit Personnel:
                            </span>
                            <span className="font-semibold text-slate-800">
                              {team.members_count} Responders
                            </span>
                          </div>
                        </div>

                        {/* Event Assignment Banner if Deployed */}
                        {isDeployed && team.assigned_event_code && (
                          <div className="mt-4 p-2.5 rounded-xl bg-rose-50/80 border border-rose-100 flex items-center justify-between text-xs text-rose-800">
                            <span className="flex items-center gap-1.5 font-semibold">
                              <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />
                              Deployed to:
                            </span>
                            <span className="font-mono font-bold">{team.assigned_event_code}</span>
                          </div>
                        )}
                      </div>

                      {/* Card Action Buttons */}
                      <div className="mt-5 pt-3 border-t border-slate-100 flex items-center gap-2">
                        <button
                          onClick={() => openTeamDetail(team)}
                          className="flex-1 py-2 px-3 rounded-xl bg-slate-50 hover:bg-slate-100 text-slate-700 font-semibold text-xs transition-colors flex items-center justify-center gap-1"
                        >
                          View Roster &amp; Spec
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>

                        <button
                          onClick={() => handleToggleDispatch(team)}
                          disabled={isUpdatingDispatch}
                          className={`py-2 px-3 rounded-xl font-semibold text-xs transition-all flex items-center justify-center gap-1 ${
                            isDeployed
                              ? 'bg-rose-100 text-rose-700 hover:bg-rose-200'
                              : 'bg-primary text-white hover:bg-primary-hover shadow-sm shadow-primary/20'
                          }`}
                        >
                          {isDeployed ? 'Recall Base' : 'Dispatch'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {filteredTeams.length === 0 && (
                <div className="text-center py-16 bg-white rounded-2xl border border-slate-100 p-8">
                  <Shield className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <h4 className="text-base font-bold text-text-primary">No Response Units Found</h4>
                  <p className="text-xs text-text-secondary mt-1">
                    Try adjusting your search query or removing agency filters.
                  </p>
                </div>
              )}
            </motion.div>
          )}

          {/* ════════════════════════ TAB 2: HACKATHON ROSTER ════════════════════════ */}
          {activeTab === 'hackathon' && (
            <motion.div
              variants={fadeIn}
              initial="hidden"
              animate="visible"
              className="space-y-6"
            >
              {/* Mission Statement Showcase Banner */}
              <div className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 rounded-3xl p-6 sm:p-8 text-white shadow-xl">
                <div className="relative z-10 max-w-3xl space-y-3">
                  <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 backdrop-blur-md border border-white/20 text-xs font-semibold text-amber-300">
                    <Award className="w-3.5 h-3.5" />
                    Smart India Hackathon 2026 • Problem Statement: SIH26069
                  </div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
                    Team Sixth Sense — Developers of INDRA
                  </h2>
                  <p className="text-slate-300 text-sm leading-relaxed">
                    &ldquo;We are building an intelligence platform, not a weather app. From fragmented, noisy weather reports across social media and citizen apps to unified, explainable, and verified national weather events.&rdquo;
                  </p>
                  <div className="flex flex-wrap items-center gap-4 pt-2 text-xs text-slate-400">
                    <span><strong>Theme:</strong> Disaster Management</span>
                    <span>•</span>
                    <span><strong>Institution:</strong> Ministry of Earth Sciences / NDRF</span>
                    <span>•</span>
                    <span><strong>Version:</strong> 1.0.0 Production Release</span>
                  </div>
                </div>

                {/* Decorative background glow */}
                <div className="absolute right-0 top-0 w-96 h-96 bg-primary/20 rounded-full blur-3xl pointer-events-none" />
              </div>

              {/* Developer Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {hackathonTeam.members.map((member) => (
                  <div
                    key={member.id}
                    className="bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md transition-all p-5 flex flex-col justify-between"
                  >
                    <div>
                      {/* Avatar and Badge */}
                      <div className="flex items-start justify-between gap-3 mb-4">
                        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary to-blue-700 text-white flex items-center justify-center font-bold text-lg shadow-md shadow-primary/20">
                          {member.avatar_initials}
                        </div>
                        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold tracking-wide uppercase bg-blue-50 text-primary border border-blue-100">
                          {member.badge}
                        </span>
                      </div>

                      <h3 className="text-base font-bold text-text-primary leading-tight">
                        {member.name}
                      </h3>
                      <p className="text-xs font-medium text-primary mt-0.5">
                        {member.role}
                      </p>

                      <div className="mt-3 p-2.5 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-600">
                        <strong className="text-slate-800">Specialty:</strong> {member.specialty}
                      </div>

                      <p className="mt-3 text-xs text-text-secondary leading-relaxed">
                        {member.bio}
                      </p>
                    </div>

                    <div className="mt-5 pt-3 border-t border-slate-100 flex items-center justify-between">
                      <span className="text-[11px] text-slate-400 font-medium">Core Contributor</span>
                      <a
                        href={member.github}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-700 hover:text-primary hover:bg-slate-50 transition-colors"
                      >
                        GitHub
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </main>
      </div>

      {/* ════════════════════════ SLIDE-OVER DETAIL MODAL ════════════════════════ */}
      <AnimatePresence>
        {isDetailOpen && selectedTeam && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.2 }}
              className="bg-white rounded-3xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col border border-slate-100"
            >
              {/* Modal Header */}
              <div className="p-6 border-b border-slate-100 flex items-start justify-between bg-slate-50/50">
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-primary/10 text-primary border border-primary/20">
                      {selectedTeam.agency}
                    </span>
                    <span className="font-mono text-xs text-slate-400">
                      {selectedTeam.team_code}
                    </span>
                  </div>
                  <h2 className="text-xl font-bold text-text-primary leading-tight">
                    {selectedTeam.name}
                  </h2>
                </div>
                <button
                  onClick={() => setIsDetailOpen(false)}
                  className="p-2 rounded-xl hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Modal Body */}
              <div className="p-6 overflow-y-auto space-y-6">
                {/* Status & Location Cards */}
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100">
                    <span className="text-slate-400 block mb-1">Deployment Status</span>
                    <span className="font-bold text-slate-800 text-sm">
                      {selectedTeam.status}
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100">
                    <span className="text-slate-400 block mb-1">Base Jurisdiction</span>
                    <span className="font-bold text-slate-800 text-sm">
                      {selectedTeam.city}, {selectedTeam.state}
                    </span>
                  </div>
                </div>

                {/* Tactical Specs */}
                <div className="space-y-2 text-xs">
                  <h4 className="font-bold text-slate-800 uppercase tracking-wider text-[11px]">
                    Operational Specifications
                  </h4>
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 space-y-1.5">
                    <p>
                      <strong>Specialization:</strong>{' '}
                      {selectedTeam.specialization || 'General Emergency Disaster Operations'}
                    </p>
                    <p>
                      <strong>Commander in Charge:</strong> {selectedTeam.lead_name} ({selectedTeam.lead_phone || 'Radio Dispatch'})
                    </p>
                    <p>
                      <strong>Radio Frequency / Callsign:</strong>{' '}
                      <span className="font-mono text-primary font-bold">{selectedTeam.radio_callsign || 'INDRA-DISPATCH'}</span>
                    </p>
                  </div>
                </div>

                {/* Member Roster */}
                <div className="space-y-2">
                  <h4 className="font-bold text-slate-800 uppercase tracking-wider text-[11px]">
                    Unit Personnel Roster ({selectedTeam.members?.length || 4} Officers)
                  </h4>
                  <div className="space-y-2">
                    {(selectedTeam.members || [
                      { id: 'm1', full_name: selectedTeam.lead_name, team_role: 'Unit Commander', duty_status: selectedTeam.status, callsign: selectedTeam.radio_callsign, badge_number: `${selectedTeam.agency}-001` },
                      { id: 'm2', full_name: 'Sub-Inspector Ankit Kumar', team_role: 'Tactical GIS Officer', duty_status: selectedTeam.status, callsign: 'TACT-02', badge_number: `${selectedTeam.agency}-004` },
                      { id: 'm3', full_name: 'Inspector Meera Sen', team_role: 'Medical Liaison', duty_status: selectedTeam.status, callsign: 'MEDIC-01', badge_number: `${selectedTeam.agency}-007` },
                      { id: 'm4', full_name: 'Specialist Rahul Das', team_role: 'Dewatering Operator', duty_status: selectedTeam.status, callsign: 'PUMP-03', badge_number: `${selectedTeam.agency}-012` },
                    ]).map((member, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-3 rounded-xl bg-white border border-slate-100 shadow-sm text-xs"
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-xs">
                            {member.full_name.split(' ').map((n) => n[0]).slice(0, 2).join('')}
                          </div>
                          <div>
                            <p className="font-bold text-slate-800">{member.full_name}</p>
                            <p className="text-slate-500 text-[11px]">{member.team_role}</p>
                          </div>
                        </div>

                        <div className="text-right">
                          <span className="font-mono text-[10px] text-slate-400 block">
                            {member.badge_number}
                          </span>
                          <span className="font-semibold text-emerald-600 text-[11px]">
                            {member.duty_status}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Modal Footer */}
              <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-between">
                <button
                  onClick={() => setIsDetailOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-200/70 transition-colors"
                >
                  Close
                </button>

                <button
                  onClick={() => handleToggleDispatch(selectedTeam)}
                  disabled={isUpdatingDispatch}
                  className={`px-5 py-2.5 rounded-xl text-xs font-bold transition-all shadow-sm ${
                    selectedTeam.status === 'DEPLOYED'
                      ? 'bg-rose-600 hover:bg-rose-700 text-white'
                      : 'bg-primary hover:bg-primary-hover text-white'
                  }`}
                >
                  {selectedTeam.status === 'DEPLOYED' ? 'Recall Unit to Base' : 'Deploy to Active Event'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function TeamsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="min-h-screen bg-surface flex items-center justify-center">
          <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        </div>
      }
    >
      <TeamsContent />
    </React.Suspense>
  );
}

