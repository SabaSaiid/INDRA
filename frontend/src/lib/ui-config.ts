/**
 * INDRA Platform — UI configuration
 *
 * Types and presentation constants only. **There is no fabricated data in this
 * file, and none may be added to it.** A component with nothing to show renders
 * an empty state that says so.
 */

import {
  LayoutDashboard,
  Map,
  CalendarClock,
  FileText,
  BarChart3,
  Bell,
  Database,
  Shield,
  Users,
  User,
  Settings,
  type LucideIcon,
} from 'lucide-react';

// ─── Navigation Items ────────────────────────────────────────────────────────

export interface NavBadge {
  text: string;
  variant: 'critical' | 'warning' | 'live' | 'neutral';
}

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  href: string;
  section: 'tactical' | 'intelligence' | 'command';
  badge?: NavBadge;
  shortcut?: string;
  description?: string;
}

export const navSections = [
  { id: 'tactical', label: 'Tactical Operations' },
  { id: 'intelligence', label: 'Intelligence & Feeds' },
  { id: 'command', label: 'Command & Roster' },
] as const;

export const navItems: NavItem[] = [
  // Tactical Operations
  {
    id: 'dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    href: '/',
    section: 'tactical',
    description: 'National overview: reports, events, warnings',
  },
  {
    id: 'live-map',
    label: 'Live Tactical Map',
    icon: Map,
    href: '/live-map',
    section: 'tactical',
    description: 'Events, official warnings and reports on a 3D globe',
  },
  {
    id: 'events',
    label: 'Incident Events',
    icon: CalendarClock,
    href: '/events',
    section: 'tactical',
    description: 'Fused events, their severity and review status',
  },

  // Intelligence & Feeds
  {
    id: 'alerts',
    label: 'Early Warnings',
    icon: Bell,
    href: '/alerts',
    section: 'intelligence',
    description: 'Official IMD, CWC and SDMA warnings via SACHET',
  },
  {
    id: 'reports',
    label: 'Field Reports',
    icon: FileText,
    href: '/reports',
    section: 'intelligence',
    description: 'Citizen ground truth & verified field intelligence',
  },
  {
    id: 'analytics',
    label: 'Telemetry Analytics',
    icon: BarChart3,
    href: '/analytics',
    section: 'intelligence',
    description: 'Report volume and event distribution',
  },
  {
    id: 'datasets',
    label: 'Geospatial Feeds',
    icon: Database,
    href: '/datasets',
    section: 'intelligence',
    description: 'The feeds INDRA reads, and what is not connected',
  },

  // Command & Roster
  {
    id: 'teams',
    label: 'Teams Hub',
    icon: Users,
    href: '/teams',
    section: 'command',
    description: 'Response teams and dispatch',
  },
  {
    id: 'profile',
    label: 'Operator Profile',
    icon: User,
    href: '/profile',
    section: 'command',
    description: 'Identity, role and duty status',
  },
  {
    id: 'admin',
    label: 'Admin Command',
    icon: Shield,
    href: '/admin',
    section: 'command',
    description: 'Dependency health, accounts and the audit ledger',
  },
  {
    id: 'settings',
    label: 'Platform Settings',
    icon: Settings,
    href: '/settings',
    section: 'command',
    description: 'Map, units and display preferences',
  },
];


// ─── KPI Data ────────────────────────────────────────────────────────────────

export interface KpiItem {
  id: string;
  label: string;
  value: number;
  /** Change over the last 24 h in percent; null when the figure has no comparison window. */
  delta: number | null;
  deltaLabel: string;
  color: string;
  bgColor: string;
  icon: 'reports' | 'verified' | 'critical' | 'citizens';
}
/** 'unrated' is a marker whose source carries no severity (a raw citizen report, an unrated warning). */
export type SeverityLevel = 'critical' | 'high' | 'moderate' | 'advisory' | 'low' | 'unrated';
export type VerificationStatus = 'verified' | 'under-review';
export type EventType = 'Severe Rainfall' | 'Flood' | 'Thunderstorm' | 'Strong Winds' | 'Fog' | 'Urban Flooding' | 'Heavy Rainfall';

/**
 * Which layer a marker belongs to. The map draws each one differently and
 * never lets one pass for another: a raw citizen report has not been
 * clustered, corroborated or scored, and drawing it like a verified event
 * would put an unreviewed claim on a national console as a fact.
 */
export type MapLayer = 'event' | 'alert' | 'report';

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  city: string;
  state: string;
  /** Display name, already hedged and already handling the unresolved case. */
  placeLabel?: string;
  layer?: MapLayer;
  eventType: EventType;
  severity: SeverityLevel;
  verification: VerificationStatus;
  description: string;
  title?: string;
}
export interface RecentEvent {
  id: string;
  city: string;
  state: string;
  /** Display name, already hedged and already handling the unresolved case. */
  placeLabel?: string;
  eventType: EventType;
  severity: SeverityLevel;
  verification: VerificationStatus;
  timestamp: Date;
  imageGradient: string;
}

export interface DistributionItem {
  name: string;
  value: number;
  count?: number;
  color: string;
}
export interface TrendDataPoint {
  date: string;
  /** The IST day as YYYY-MM-DD; absent from a backend older than 24 Sep. */
  day?: string;
  reports: number;
}
export type FeedSourceType =
  | 'citizen' | 'official' | 'social' | 'imd' | 'news' | 'event' | 'review' | 'warning';

export interface FeedItem {
  id: string;
  source: FeedSourceType;
  sourceLabel: string;
  message: string;
  /** HH:MM in IST. */
  time: string;
  /** Which stream the item came from (backend since 24 Sep). */
  kind?: 'report' | 'event' | 'warning';
  /** ISO 8601 instant, for relative times and dates (backend since 24 Sep). */
  at?: string | null;
  place?: string | null;
  severity?: string | null;
  status?: string | null;
  event_id?: string;
  city?: string;
  confidence?: number;
  eventType?: string;
  type?: string;
  timestamp?: string;
}
export const severityConfig: Record<SeverityLevel, { label: string; color: string; bg: string; textColor: string }> = {
  critical: { label: 'Critical', color: '#8C2F26', bg: '#F5E8E7', textColor: '#6D1F18' },
  high: { label: 'High', color: '#B8873A', bg: '#FBF2E4', textColor: '#8A611E' },
  moderate: { label: 'Moderate', color: '#4A6670', bg: '#E6EFF1', textColor: '#374E57' },
  // The backend grades most fresh clusters ADVISORY (two to four reports, no
  // depth quoted). Without this entry the recent-events list fell back to
  // 'moderate' and showed every advisory event as Moderate.
  advisory: { label: 'Advisory', color: '#7A8599', bg: '#EEF0F4', textColor: '#4A5568' },
  low: { label: 'Low', color: '#6B7280', bg: '#F3F4F6', textColor: '#4B5563' },
  unrated: { label: 'Unrated', color: '#9CA3AF', bg: '#F3F4F6', textColor: '#6B7280' },
};

export const verificationConfig: Record<VerificationStatus, { label: string; color: string; bg: string; textColor: string; icon: string }> = {
  verified: { label: 'Verified', color: '#4C7A5B', bg: '#E7F2EC', textColor: '#3A5E46', icon: '✓' },
  'under-review': { label: 'Under review', color: '#B8873A', bg: '#FBF2E4', textColor: '#8A611E', icon: '○' },
};

export const feedSourceConfig: Record<FeedSourceType, { color: string; bg: string }> = {
  citizen: { color: '#26314A', bg: '#ECEEF3' },
  social: { color: '#4A5568', bg: '#F3F4F6' },
  imd: { color: '#B8873A', bg: '#FBF2E4' },
  news: { color: '#8C2F26', bg: '#F5E8E7' },
  official: { color: '#1B2432', bg: '#E8E2D4' },
  event: { color: '#8C2F26', bg: '#FEE2E2' },
  review: { color: '#065F46', bg: '#D1FAE5' },
  warning: { color: '#9A3412', bg: '#FFEDD5' },
};

// ─── Team & Profile Types & Configuration ─────────────────────────────────────

export type DutyStatus = 'ON_DUTY' | 'STANDBY' | 'DEPLOYED' | 'OFF_DUTY';
export type TeamAgency = 'NDRF' | 'SDRF' | 'IMD' | 'CWC' | 'NDMA' | 'MUNICIPAL';
export type TeamStatus = 'AVAILABLE' | 'DEPLOYED' | 'STANDBY' | 'OFF_DUTY';
export type OperatorRole = 'COMMANDER' | 'ANALYST' | 'ADMIN' | 'CITIZEN' | 'FIELD_RESPONDER';

export interface TeamMember {
  id: string;
  full_name: string;
  team_role: string;
  duty_status: DutyStatus | string;
  badge_number?: string;
  callsign?: string;
  phone?: string;
}

export interface TeamItem {
  id: string;
  team_code: string;
  name: string;
  agency: TeamAgency | string;
  city: string;
  state: string;
  lead_name: string;
  lead_phone?: string;
  radio_callsign?: string;
  specialization?: string;
  status: TeamStatus | string;
  members_count: number;
  created_at?: string;
  assigned_event_id?: string | null;
  assigned_event_code?: string | null;
  assigned_event_type?: string | null;
  event_lat?: number;
  event_lng?: number;
  members?: TeamMember[];
}

export interface UserProfile {
  id: string;
  username: string;
  full_name: string;
  email?: string;
  phone?: string;
  role: OperatorRole | string;
  agency: string;
  operator_id: string;
  badge_number?: string;
  callsign?: string;
  team_id?: string;
  team_name?: string;
  team_code?: string;
  team_role?: string;
  duty_status: DutyStatus;
  avatar_initials?: string;
  bio?: string;
  verified_events_triaged?: number;
  audits_logged?: number;
  accuracy_rate?: number;
  last_active_at?: string;
  /** Real ledger actions for this operator, newest first. Empty until they review something. */
  recent_activities?: OperatorActivity[];
}

export interface OperatorActivity {
  id: string;
  action: string;
  target: string;
  time: string;
  status: 'COMPLETED' | 'VERIFIED' | 'LOGGED' | 'ON DUTY' | 'DISPATCHED' | 'QUARANTINED' | 'SUBMITTED';
}

export interface RoleTelemetryItem {
  label: string;
  value: string | number;
  sublabel?: string;
  iconName: 'FileCheck' | 'Shield' | 'CheckCircle2' | 'Clock' | 'Radio' | 'Zap' | 'Activity' | 'Users' | 'Eye' | 'Satellite' | 'Server' | 'Award';
  color: 'blue' | 'purple' | 'emerald' | 'amber';
}

export interface RolePermission {
  key: string;
  name: string;
  description: string;
  authorized: boolean;
}

export interface RoleSecurityProfile {
  clearanceLevel: string;
  clearanceCode: string;
  clearanceColor: string;
  tokenExpiry: string;
  ledgerImmutability: string;
  permissions: RolePermission[];
}

export interface HackathonMember {
  id: string;
  name: string;
  role: string;
  specialty: string;
  bio: string;
  avatar_initials: string;
  github: string;
  badge: string;
}

export interface HackathonTeamData {
  team_name: string;
  problem_statement: string;
  theme: string;
  tagline: string;
  institution: string;
  members: HackathonMember[];
}

export const dutyStatusConfig: Record<DutyStatus, { label: string; color: string; bg: string; dot: string }> = {
  ON_DUTY: { label: 'On Duty', color: '#10B981', bg: '#D1FAE5', dot: '#059669' },
  STANDBY: { label: 'Standby', color: '#F59E0B', bg: '#FEF3C7', dot: '#D97706' },
  DEPLOYED: { label: 'Deployed', color: '#EF4444', bg: '#FEE2E2', dot: '#DC2626' },
  OFF_DUTY: { label: 'Off Duty', color: '#64748B', bg: '#F1F5F9', dot: '#475569' },
};

export const teamAgencyConfig: Record<string, { label: string; color: string; bg: string; border: string }> = {
  NDRF: { label: 'NDRF', color: '#EA580C', bg: '#FFEDD5', border: '#FDBA74' },
  SDRF: { label: 'SDRF', color: '#0284C7', bg: '#E0F2FE', border: '#7DD3FC' },
  IMD: { label: 'IMD', color: '#2563EB', bg: '#DBEAFE', border: '#93C5FD' },
  CWC: { label: 'CWC', color: '#0D9488', bg: '#CCFBF1', border: '#5EEAD4' },
  NDMA: { label: 'NDMA', color: '#7C3AED', bg: '#EDE9FE', border: '#C4B5FD' },
  MUNICIPAL: { label: 'Municipal', color: '#4F46E5', bg: '#EEF2FF', border: '#A5B4FC' },
};
/**
 * Rendering placeholder for the operator chrome (sidebar footer, topbar chip)
 * while `/api/profile/me` has not answered, or could not be reached.
 *
 * **This is not a fake operator and must never be mistaken for one.** Every
 * visible field is an em-dash or an explicit "unavailable" string, so a viewer
 * sees that the identity is missing rather than reading a plausible name and
 * badge number that belong to nobody. It exists only so the layout does not
 * collapse; the moment the backend answers it is replaced.
 */
export const PLACEHOLDER_OPERATOR: UserProfile = {
  id: '',
  username: '',
  full_name: 'Operator unavailable',
  role: '—',
  agency: '—',
  operator_id: '—',
  badge_number: '—',
  callsign: '—',
  duty_status: 'OFF_DUTY',
  avatar_initials: '—',
};

/**
 * What each role may actually do, transcribed from the backend's enforced auth
 * matrix (`backend/tests/test_auth_enforcement.py` and, since 22 Sep,
 * `test_mutation_auth.py`, `test_official_ingest.py` and `test_audit_api.py`).
 *
 * This replaces `mockRoleSecurity`, which invented "clearance codes" and
 * "clearance levels" — concepts INDRA has no notion of anywhere in its code.
 * Everything below is a statement about behaviour the backend really enforces,
 * so it belongs with the design constants rather than with the deleted fakes.
 *
 * Session expiry is the real JWT lifetime (`JWT_EXPIRY_HOURS = 8`, HS256).
 * Ledger immutability is real too: `services/audit.py` hash-chains every
 * decision with SHA-256 and `GET /api/events/{id}/provenance` verifies the
 * chain from genesis.
 */
export interface RoleCapability {
  label: string;
  granted: boolean;
}

export const ROLE_CAPABILITIES: Record<string, RoleCapability[]> = {
  ADMIN: [
    { label: 'Review & approve events', granted: true },
    { label: 'Override event severity', granted: true },
    { label: 'Create & dispatch response teams', granted: true },
    { label: 'File official dispatch reports', granted: true },
    { label: 'Read provenance & the audit ledger', granted: true },
    { label: 'Edit own profile', granted: true },
    { label: 'Submit citizen reports', granted: true },
  ],
  COMMANDER: [
    { label: 'Review & approve events', granted: true },
    { label: 'Override event severity', granted: true },
    { label: 'Create & dispatch response teams', granted: true },
    { label: 'File official dispatch reports', granted: true },
    { label: 'Read provenance & the audit ledger', granted: true },
    { label: 'Edit own profile', granted: true },
    { label: 'Submit citizen reports', granted: true },
  ],
  ANALYST: [
    { label: 'Review & approve events', granted: false },
    { label: 'Override event severity', granted: false },
    { label: 'Create & dispatch response teams', granted: false },
    { label: 'File official dispatch reports', granted: false },
    { label: 'Read provenance & the audit ledger', granted: true },
    { label: 'Edit own profile', granted: true },
    { label: 'Submit citizen reports', granted: true },
  ],
  CITIZEN: [
    { label: 'Review & approve events', granted: false },
    { label: 'Override event severity', granted: false },
    { label: 'Create & dispatch response teams', granted: false },
    { label: 'File official dispatch reports', granted: false },
    { label: 'Read provenance & the audit ledger', granted: false },
    { label: 'Edit own profile', granted: true },
    { label: 'Submit citizen reports', granted: true },
  ],
};

/** HS256, 8 h — `JWT_EXPIRY_HOURS` in backend/app/core/config.py. */
export const SESSION_TOKEN_LIFETIME = '8 h · HS256';
/** services/audit.py chains every decision; provenance verifies from genesis. */
export const LEDGER_IMMUTABILITY = 'SHA-256 hash chain';
