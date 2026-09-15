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
    shortcut: '⌘1',
    description: 'National overview & key telemetry metrics',
  },
  {
    id: 'live-map',
    label: 'Live Tactical Map',
    icon: Map,
    href: '/live-map',
    section: 'tactical',
    badge: { text: 'LIVE', variant: 'live' },
    shortcut: '⌘2',
    description: '3D interactive globe & Doppler radar feeds',
  },
  {
    id: 'events',
    label: 'Incident Events',
    icon: CalendarClock,
    href: '/events',
    section: 'tactical',
    badge: { text: '18', variant: 'warning' },
    shortcut: '⌘3',
    description: 'Active severe weather alerts & emergency timeline',
  },

  // Intelligence & Feeds
  {
    id: 'alerts',
    label: 'Early Warnings',
    icon: Bell,
    href: '/alerts',
    section: 'intelligence',
    badge: { text: '4 CRIT', variant: 'critical' },
    shortcut: '⌘4',
    description: 'Flash flood, cyclone & IMD hazard bulletins',
  },
  {
    id: 'reports',
    label: 'Field Reports',
    icon: FileText,
    href: '/reports',
    section: 'intelligence',
    shortcut: '⌘5',
    description: 'Citizen ground truth & verified field intelligence',
  },
  {
    id: 'analytics',
    label: 'Telemetry Analytics',
    icon: BarChart3,
    href: '/analytics',
    section: 'intelligence',
    shortcut: '⌘6',
    description: 'BigQuery trend models & multi-source correlations',
  },
  {
    id: 'datasets',
    label: 'Geospatial Feeds',
    icon: Database,
    href: '/datasets',
    section: 'intelligence',
    shortcut: '⌘7',
    description: 'IMD raster data, satellite imagery & GIS archives',
  },

  // Command & Roster
  {
    id: 'teams',
    label: 'Teams Hub',
    icon: Users,
    href: '/teams',
    section: 'command',
    shortcut: '⌘8',
    description: 'Disaster response battalions & command units',
  },
  {
    id: 'profile',
    label: 'Operator Profile',
    icon: User,
    href: '/profile',
    section: 'command',
    shortcut: '⌘9',
    description: 'Credentials, security clearance & duty roster',
  },
  {
    id: 'admin',
    label: 'Admin Command',
    icon: Shield,
    href: '/admin',
    section: 'command',
    shortcut: '⌘0',
    description: 'System governance, RBAC permissions & node telemetry',
  },
  {
    id: 'settings',
    label: 'Platform Settings',
    icon: Settings,
    href: '/settings',
    section: 'command',
    shortcut: '⌘,',
    description: 'Tactical GIS, alert siren audio, units & HUD preferences',
  },
];


// ─── KPI Data ────────────────────────────────────────────────────────────────

export interface KpiItem {
  id: string;
  label: string;
  value: number;
  delta: number;
  deltaLabel: string;
  color: string;
  bgColor: string;
  icon: 'reports' | 'verified' | 'critical' | 'citizens';
}

export const kpiData: KpiItem[] = [
  {
    id: 'total-reports',
    label: 'Total Reports',
    value: 1248,
    delta: 12,
    deltaLabel: 'last 24h',
    color: '#2563EB',
    bgColor: '#EFF6FF',
    icon: 'reports',
  },
  {
    id: 'verified-events',
    label: 'Verified Events',
    value: 37,
    delta: 8,
    deltaLabel: 'last 24h',
    color: '#10B981',
    bgColor: '#D1FAE5',
    icon: 'verified',
  },
  {
    id: 'critical-events',
    label: 'Critical Events',
    value: 5,
    delta: 2,
    deltaLabel: 'last 24h',
    color: '#EF4444',
    bgColor: '#FEE2E2',
    icon: 'critical',
  },
  {
    id: 'citizen-reports',
    label: 'Citizen Reports',
    value: 8421,
    delta: 15,
    deltaLabel: 'last 24h',
    color: '#8B5CF6',
    bgColor: '#EDE9FE',
    icon: 'citizens',
  },
];

// ─── Map Markers ─────────────────────────────────────────────────────────────

export type SeverityLevel = 'critical' | 'high' | 'moderate' | 'low';
export type VerificationStatus = 'verified' | 'under-review';
export type EventType = 'Severe Rainfall' | 'Flood' | 'Thunderstorm' | 'Strong Winds' | 'Fog' | 'Urban Flooding' | 'Heavy Rainfall';

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  city: string;
  state: string;
  eventType: EventType;
  severity: SeverityLevel;
  verification: VerificationStatus;
  description: string;
  title?: string;
  impact?: string;
  action?: string;
  timeAgo?: string;
  confidence?: number;
  verified?: boolean;
}

export const mapMarkers: MapMarker[] = [
  {
    id: 'ev-1',
    lat: 25.6093,
    lng: 85.1376,
    city: 'Patna',
    state: 'Bihar',
    eventType: 'Urban Flooding',
    severity: 'critical',
    description: 'Heavy waterlogging in multiple areas, water level rising',
    verification: 'verified',
  },
  {
    id: 'ev-2',
    lat: 26.1445,
    lng: 91.7362,
    city: 'Guwahati',
    state: 'Assam',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    description: 'Continuous heavy rainfall, rivers near danger mark',
    verification: 'under-review',
  },
  {
    id: 'ev-3',
    lat: 19.0760,
    lng: 72.8777,
    city: 'Mumbai',
    state: 'Maharashtra',
    eventType: 'Strong Winds',
    severity: 'moderate',
    description: 'High velocity winds in coastal areas',
    verification: 'verified',
  },
  {
    id: 'ev-4',
    lat: 28.6139,
    lng: 77.2090,
    city: 'New Delhi',
    state: 'Delhi',
    eventType: 'Fog',
    severity: 'low',
    description: 'Dense fog advisory for morning hours',
    verification: 'verified',
  },
  {
    id: 'ev-5',
    lat: 13.0827,
    lng: 80.2707,
    city: 'Chennai',
    state: 'Tamil Nadu',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    description: 'IMD red alert: Very heavy rainfall expected',
    verification: 'under-review',
  },
  {
    id: 'ev-6',
    lat: 22.5726,
    lng: 88.3639,
    city: 'Kolkata',
    state: 'West Bengal',
    eventType: 'Thunderstorm',
    severity: 'moderate',
    description: 'Isolated thunderstorm activity with lightning',
    verification: 'verified',
  },
  {
    id: 'ev-7',
    lat: 26.9124,
    lng: 75.7873,
    city: 'Jaipur',
    state: 'Rajasthan',
    eventType: 'Strong Winds',
    severity: 'low',
    description: 'Dust storm advisory in desert region',
    verification: 'verified',
  },
  {
    id: 'ev-8',
    lat: 12.9716,
    lng: 77.5946,
    city: 'Bengaluru',
    state: 'Karnataka',
    eventType: 'Severe Rainfall',
    severity: 'moderate',
    description: 'Heavy rains causing urban flooding in low-lying areas',
    verification: 'under-review',
  },
  {
    id: 'ev-9',
    lat: 26.8467,
    lng: 80.9462,
    city: 'Lucknow',
    state: 'Uttar Pradesh',
    eventType: 'Flood',
    severity: 'high',
    description: 'Gomti river near danger level, low-lying areas evacuated',
    verification: 'verified',
  },
  {
    id: 'ev-10',
    lat: 23.0225,
    lng: 72.5714,
    city: 'Ahmedabad',
    state: 'Gujarat',
    eventType: 'Thunderstorm',
    severity: 'low',
    description: 'Light thunderstorm activity expected in evening',
    verification: 'verified',
  },
];

// ─── Recent Events ───────────────────────────────────────────────────────────

export interface RecentEvent {
  id: string;
  city: string;
  state: string;
  eventType: EventType;
  severity: SeverityLevel;
  verification: VerificationStatus;
  timestamp: Date;
  imageGradient: string;
}

const now = new Date();

export const recentEvents: RecentEvent[] = [
  {
    id: 'ev-1',
    city: 'Patna',
    state: 'Bihar',
    eventType: 'Urban Flooding',
    severity: 'critical',
    verification: 'verified',
    timestamp: new Date(now.getTime() - 2 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #8C2F26, #5C1A14)',
  },
  {
    id: 'ev-2',
    city: 'Guwahati',
    state: 'Assam',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    verification: 'under-review',
    timestamp: new Date(now.getTime() - 3 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #B8873A, #8A611E)',
  },
  {
    id: 'ev-3',
    city: 'Mumbai',
    state: 'Maharashtra',
    eventType: 'Strong Winds',
    severity: 'moderate',
    verification: 'verified',
    timestamp: new Date(now.getTime() - 5 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #4A6670, #2D4A54)',
  },
  {
    id: 'ev-4',
    city: 'New Delhi',
    state: 'Delhi',
    eventType: 'Fog',
    severity: 'low',
    verification: 'verified',
    timestamp: new Date(now.getTime() - 6 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #7A8599, #4A5568)',
  },
  {
    id: 'ev-5',
    city: 'Chennai',
    state: 'Tamil Nadu',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    verification: 'under-review',
    timestamp: new Date(now.getTime() - 8 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #B8873A, #8A611E)',
  },
];

// ─── Event Distribution (Donut Chart) ────────────────────────────────────────

export interface DistributionItem {
  name: string;
  value: number;
  count?: number;
  color: string;
}

export const eventDistribution: DistributionItem[] = [
  { name: 'Rainfall', value: 14, count: 14, color: '#4A6670' },
  { name: 'Flood', value: 8, count: 8, color: '#8C2F26' },
  { name: 'Thunderstorm', value: 6, count: 6, color: '#7A5C8A' },
  { name: 'Strong Winds', value: 5, count: 5, color: '#26314A' },
  { name: 'Fog', value: 3, count: 3, color: '#7A8599' },
  { name: 'Others', value: 1, count: 1, color: '#B0A898' },
];

export const eventSeverityDistribution: DistributionItem[] = [
  { name: 'Critical', value: 4, count: 4, color: '#8C2F26' },
  { name: 'High', value: 8, count: 8, color: '#B8873A' },
  { name: 'Moderate', value: 15, count: 15, color: '#4A6670' },
  { name: 'Advisory', value: 10, count: 10, color: '#4C7A5B' },
];


// ─── Reports Trend (Line Chart — 7 days) ─────────────────────────────────────

export interface TrendDataPoint {
  date: string;
  reports: number;
}

export const reportsTrend: TrendDataPoint[] = [
  { date: '18 Nov', reports: 42 },
  { date: '19 Nov', reports: 78 },
  { date: '20 Nov', reports: 156 },
  { date: '21 Nov', reports: 420 },
  { date: '22 Nov', reports: 580 },
  { date: '23 Nov', reports: 650 },
  { date: '24 Nov', reports: 720 },
];

// ─── Live Feed ───────────────────────────────────────────────────────────────

export type FeedSourceType = 'citizen' | 'social' | 'imd' | 'news';

export interface FeedItem {
  id: string;
  source: FeedSourceType;
  sourceLabel: string;
  message: string;
  time: string;
}

export const liveFeedItems: FeedItem[] = [
  {
    id: 'feed-1',
    source: 'citizen',
    sourceLabel: 'Citizen report',
    message: 'Heavy rainfall near Gandhi Maidan, Patna',
    time: '14:28',
  },
  {
    id: 'feed-2',
    source: 'social',
    sourceLabel: 'Social media',
    message: '#IMD Heavy rain in parts of Guwahati',
    time: '14:26',
  },
  {
    id: 'feed-3',
    source: 'imd',
    sourceLabel: 'IMD Alert',
    message: 'Moderate to heavy rainfall likely in Assam tomorrow',
    time: '14:20',
  },
  {
    id: 'feed-4',
    source: 'news',
    sourceLabel: 'News Source',
    message: 'Waterlogging reported in several parts of Mumbai',
    time: '14:15',
  },
  {
    id: 'feed-5',
    source: 'citizen',
    sourceLabel: 'Citizen report',
    message: 'Road blocked near MG Road, Bengaluru due to flooding',
    time: '14:10',
  },
  {
    id: 'feed-6',
    source: 'imd',
    sourceLabel: 'IMD Alert',
    message: 'Red alert issued for Chennai coast — cyclonic activity',
    time: '14:05',
  },
  {
    id: 'feed-7',
    source: 'social',
    sourceLabel: 'Social media',
    message: 'Dense fog grips Delhi-NCR, visibility below 50 meters',
    time: '13:58',
  },
  {
    id: 'feed-8',
    source: 'news',
    sourceLabel: 'News Source',
    message: 'Gomti river water level crosses warning mark in Lucknow',
    time: '13:52',
  },
];

// ─── Severity Config (shared lookup) ─────────────────────────────────────────

// Low Pressure severity palette — muted earth tones
export const severityConfig: Record<SeverityLevel, { label: string; color: string; bg: string; textColor: string }> = {
  critical: { label: 'Critical', color: '#8C2F26', bg: '#F5E8E7', textColor: '#6D1F18' },
  high: { label: 'High', color: '#B8873A', bg: '#FBF2E4', textColor: '#8A611E' },
  moderate: { label: 'Moderate', color: '#4A6670', bg: '#E6EFF1', textColor: '#374E57' },
  low: { label: 'Low', color: '#6B7280', bg: '#F3F4F6', textColor: '#4B5563' },
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

// ─── Default Mock Data ────────────────────────────────────────────────────────

export const mockTeams: TeamItem[] = [
  {
    id: 'team-1',
    team_code: 'TEAM-NDRF-09',
    name: 'NDRF 9th Battalion - Flood Rescue Unit',
    agency: 'NDRF',
    city: 'Patna',
    state: 'Bihar',
    lead_name: 'Commandant R. K. Verma',
    lead_phone: '+91 94311 02847',
    radio_callsign: 'HAWK-ONE',
    specialization: 'Urban Flood & Deep Water Evacuation',
    status: 'DEPLOYED',
    members_count: 18,
    assigned_event_code: 'WX-EV-28231827-A',
    assigned_event_type: 'URBAN_FLOOD',
    members: [
      { id: 'm-1', full_name: 'Commandant R. K. Verma', team_role: 'Commander', duty_status: 'DEPLOYED', badge_number: 'NDRF-PAT-091', callsign: 'HAWK-LEAD' },
      { id: 'm-2', full_name: 'Inspector Sunil Yadav', team_role: 'Boat Rescue Lead', duty_status: 'DEPLOYED', badge_number: 'NDRF-PAT-104', callsign: 'HAWK-2' },
      { id: 'm-3', full_name: 'Sub-Inspector Priya Sinha', team_role: 'Medical Dispatcher', duty_status: 'DEPLOYED', badge_number: 'NDRF-PAT-112', callsign: 'MEDIC-1' },
      { id: 'm-4', full_name: 'Constable Amit Roy', team_role: 'Logistics / Dewatering', duty_status: 'DEPLOYED', badge_number: 'NDRF-PAT-130', callsign: 'PUMP-LEAD' },
    ],
  },
  {
    id: 'team-2',
    team_code: 'TEAM-SDRF-MH01',
    name: 'SDRF Coastal Quick Response Team',
    agency: 'SDRF',
    city: 'Mumbai',
    state: 'Maharashtra',
    lead_name: 'Inspector Sanjay Deshmukh',
    lead_phone: '+91 98220 54198',
    radio_callsign: 'SEA-HAWK-4',
    specialization: 'Coastal Inundation & High Tide Evacuation',
    status: 'DEPLOYED',
    members_count: 14,
    assigned_event_code: 'WX-EV-77291044-B',
    assigned_event_type: 'CYCLONE_INUNDATION',
  },
  {
    id: 'team-3',
    team_code: 'TEAM-IMD-NOW01',
    name: 'IMD Severe Weather Nowcasting Cell',
    agency: 'IMD',
    city: 'New Delhi',
    state: 'Delhi',
    lead_name: 'Dr. Sunita Raman',
    lead_phone: '+91 98110 77312',
    radio_callsign: 'DOPPLER-BASE',
    specialization: 'Doppler Radar Analysis & Microburst Tracking',
    status: 'AVAILABLE',
    members_count: 8,
  },
  {
    id: 'team-4',
    team_code: 'TEAM-CWC-HYDRO04',
    name: 'CWC Brahmaputra Basin Hydrology Unit',
    agency: 'CWC',
    city: 'Guwahati',
    state: 'Assam',
    lead_name: 'Chief Hydrologist B. K. Sarma',
    lead_phone: '+91 94350 18273',
    radio_callsign: 'RIVER-GUARD-2',
    specialization: 'River Embankment & Inundation Modeling',
    status: 'DEPLOYED',
    members_count: 12,
    assigned_event_code: 'WX-EV-44810293-C',
    assigned_event_type: 'RIVER_BREACH',
  },
  {
    id: 'team-5',
    team_code: 'TEAM-NDRF-04',
    name: 'NDRF 4th Battalion - Cyclone Action Team',
    agency: 'NDRF',
    city: 'Chennai',
    state: 'Tamil Nadu',
    lead_name: 'Deputy Commandant S. Karthik',
    lead_phone: '+91 94440 99821',
    radio_callsign: 'COROMANDEL-ONE',
    specialization: 'Severe Cyclonic Storm Response & Heavy Debris Clearing',
    status: 'STANDBY',
    members_count: 22,
  },
  {
    id: 'team-6',
    team_code: 'TEAM-BBMP-URB02',
    name: 'BBMP Disaster Rapid Drainage Taskforce',
    agency: 'MUNICIPAL',
    city: 'Bengaluru',
    state: 'Karnataka',
    lead_name: 'Executive Engineer K. Shivakumar',
    lead_phone: '+91 98450 33124',
    radio_callsign: 'RAPID-PUMP-8',
    specialization: 'Stormwater Drain Cleansing & High-Volume Dewatering',
    status: 'AVAILABLE',
    members_count: 16,
  },
  {
    id: 'team-7',
    team_code: 'TEAM-GHMC-HYD01',
    name: 'GHMC Monsoon Emergency Action Team',
    agency: 'MUNICIPAL',
    city: 'Hyderabad',
    state: 'Telangana',
    lead_name: 'Superintendent P. Anji Reddy',
    lead_phone: '+91 98490 12099',
    radio_callsign: 'DECCAN-SHIELD-3',
    specialization: 'Urban Flash Flood Control & Road Clearing',
    status: 'STANDBY',
    members_count: 15,
  },
  {
    id: 'team-8',
    team_code: 'TEAM-NDMA-NAT01',
    name: 'NDMA National Aerial Reconnaissance Wing',
    agency: 'NDMA',
    city: 'New Delhi',
    state: 'Delhi',
    lead_name: 'Group Captain V. Nair',
    lead_phone: '+91 99100 44552',
    radio_callsign: 'GARUDA-CENTRAL',
    specialization: 'UAV Disaster Surveillance & Thermal Flood Mapping',
    status: 'AVAILABLE',
    members_count: 10,
  },
];

export const mockUserProfile: UserProfile = {
  id: '22222222-2222-2222-2222-222222222201',
  username: 'commander',
  full_name: 'Commandant Rajesh K. Verma',
  email: 'rajesh.verma@sih-indra.gov.in',
  phone: '+91 94311 02847',
  role: 'COMMANDER',
  agency: 'SDMA_BIHAR',
  operator_id: 'OP-CMD-001',
  badge_number: 'NDRF-PAT-091',
  callsign: 'NDRF-CMD-09',
  team_name: 'NDRF 9th Battalion — Flood Rescue Unit',
  team_code: 'TEAM-NDRF-09',
  team_role: 'Incident Commander',
  duty_status: 'ON_DUTY',
  avatar_initials: 'RV',
  bio: 'National Disaster Response Force commander leading urban inundation and river flood operations across Eastern India.',
  verified_events_triaged: 24,
  audits_logged: 19,
  accuracy_rate: 96.8,
  last_active_at: '2026-09-14T20:45:00Z',
};

export const mockProfilesMap: Record<string, UserProfile> = {
  commander: mockUserProfile,
  admin: {
    id: '22222222-2222-2222-2222-222222222202',
    username: 'admin',
    full_name: 'Saba Saeed',
    email: 'sabasaid826@gmail.com',
    phone: '+91 84347 08060',
    role: 'ADMIN',
    agency: 'NDMA',
    operator_id: 'OP-ADMIN-001',
    badge_number: 'NDMA-DIR-001',
    callsign: 'NDMA-DIR-01',
    team_name: 'NDMA National Aerial Reconnaissance Wing',
    team_code: 'TEAM-NDMA-NAT01',
    team_role: 'Platform Administrator & Team Lead',
    duty_status: 'ON_DUTY',
    avatar_initials: 'SS',
    bio: 'Lead System Architect and NDMA Platform Administrator managing the INDRA national big data weather platform.',
    verified_events_triaged: 37,
    audits_logged: 42,
    accuracy_rate: 99.1,
    last_active_at: '2026-09-15T11:00:00Z',
  },
  analyst: {
    id: '22222222-2222-2222-2222-222222222203',
    username: 'analyst',
    full_name: 'Dr. Vikram Sethi',
    email: 'vikram.sethi@imd.gov.in',
    phone: '+91 98710 44210',
    role: 'ANALYST',
    agency: 'IMD',
    operator_id: 'OP-ANL-001',
    badge_number: 'IMD-MET-552',
    callsign: 'RADAR-HAWK',
    team_name: 'IMD Severe Weather Nowcasting Cell',
    team_code: 'TEAM-IMD-NOW01',
    team_role: 'Lead Meteorological Analyst',
    duty_status: 'ON_DUTY',
    avatar_initials: 'VS',
    bio: 'IMD Nowcasting specialist focusing on Doppler weather radar echoes and cloudburst probability synthesis.',
    verified_events_triaged: 31,
    audits_logged: 28,
    accuracy_rate: 94.5,
    last_active_at: '2026-09-14T20:30:00Z',
  },
  citizen: {
    id: '22222222-2222-2222-2222-222222222204',
    username: 'citizen',
    full_name: 'Meenal Sinha',
    email: 'meenal.sinha09@gmail.com',
    phone: '+91 93541 18582',
    role: 'CITIZEN',
    agency: 'PUBLIC',
    operator_id: 'OP-CIT-001',
    badge_number: 'CITIZEN-REP-06',
    callsign: 'OBSERVER-MEENAL',
    team_name: 'Community Weather Watch Volunteers',
    team_code: 'TEAM-COMM-VOL',
    team_role: 'Volunteer Reporter',
    duty_status: 'ON_DUTY',
    avatar_initials: 'MS',
    bio: 'Registered citizen weather observer and ground-truth volunteer contributing geotagged ground reports and flooding photos.',
    verified_events_triaged: 5,
    audits_logged: 0,
    accuracy_rate: 92.4,
    last_active_at: '2026-09-15T10:45:00Z',
  },
};

export const mockRoleActivities: Record<string, OperatorActivity[]> = {
  commander: [
    { id: 'act-c-1', action: 'Dispatched Quick Response Taskforce', target: 'WX-EV-28231827-A (Patna Urban Flood)', time: '18 mins ago', status: 'DISPATCHED' },
    { id: 'act-c-2', action: 'High-Confidence Triage Signed', target: 'WX-EV-77291044-B (Mumbai Coastal Surge)', time: '2 hours ago', status: 'VERIFIED' },
    { id: 'act-c-3', action: 'Manual Override Confirmation', target: 'SIG-10928 (River Gauge Anomaly)', time: '5 hours ago', status: 'LOGGED' },
    { id: 'act-c-4', action: 'Shift Roll-Call & Tactical Inspection', target: 'Patna Regional Command Base', time: '11 hours ago', status: 'ON DUTY' },
    { id: 'act-c-5', action: 'Evacuation Corridor Authorized', target: 'Sector 4 Embankment Zone', time: 'Yesterday', status: 'COMPLETED' },
  ],
  analyst: [
    { id: 'act-a-1', action: 'Doppler Radar Echo Cross-Validation', target: 'DWR-PAT-02 (Cloudburst Echo Cluster)', time: '12 mins ago', status: 'VERIFIED' },
    { id: 'act-a-2', action: 'Bayesian Prior Recalibration', target: 'AWS-BIH-104 (Rainfall Gauge Drift)', time: '1 hour ago', status: 'COMPLETED' },
    { id: 'act-a-3', action: 'False Alarm Signal Quarantined', target: 'SIG-99120 (Acoustic Glitch Triage)', time: '4 hours ago', status: 'QUARANTINED' },
    { id: 'act-a-4', action: 'Flash Flood Guidance Synthesis', target: 'South Bihar River Basins', time: '8 hours ago', status: 'LOGGED' },
    { id: 'act-a-5', action: 'INSAT-3DR Rapid Scan Overlay', target: 'Eastern Himalayan Frontal Cloud', time: 'Yesterday', status: 'COMPLETED' },
  ],
  admin: [
    { id: 'act-ad-1', action: 'Platform Security Audit & Integrity Check', target: 'Ledger Block #84920 (SHA-256 Validated)', time: '8 mins ago', status: 'VERIFIED' },
    { id: 'act-ad-2', action: 'Taskforce Deployment Roster Reallocated', target: 'TEAM-NDRF-09 & TEAM-SDRF-02', time: '45 mins ago', status: 'COMPLETED' },
    { id: 'act-ad-3', action: 'Activated Pan-India Multi-Hazard Gateway', target: 'NDMA Central Node 01', time: '3 hours ago', status: 'ON DUTY' },
    { id: 'act-ad-4', action: 'RBAC Policy Matrix Synchronized', target: 'Field Responder Clearance Tier 2', time: '6 hours ago', status: 'LOGGED' },
    { id: 'act-ad-5', action: 'PostgreSQL TimeScale Hypertables Reindexed', target: 'Station Readings Cluster (120M Rows)', time: 'Yesterday', status: 'COMPLETED' },
  ],
  citizen: [
    { id: 'act-ct-1', action: 'Geotagged Waterlogging Report Submitted', target: 'Kankarbagh Main Road, Patna (0.8m Depth)', time: '25 mins ago', status: 'SUBMITTED' },
    { id: 'act-ct-2', action: 'Local Drain Overflow Alert Logged', target: 'Ward 12 Municipal Inundation', time: '3 hours ago', status: 'VERIFIED' },
    { id: 'act-ct-3', action: 'Community Warning Upvoted', target: 'WX-EV-28231827-A Flash Flood Warning', time: '5 hours ago', status: 'COMPLETED' },
    { id: 'act-ct-4', action: 'Ground-Truth Station Reading Confirmed', target: 'Neighborhood Rain Gauge RG-04', time: '10 hours ago', status: 'LOGGED' },
    { id: 'act-ct-5', action: 'Evacuation Route Feedback Shared', target: 'Boring Road Relief Shelter Path', time: 'Yesterday', status: 'SUBMITTED' },
  ],
};

export const mockRoleTelemetry: Record<string, RoleTelemetryItem[]> = {
  commander: [
    { label: 'Events Triaged', value: 24, sublabel: 'Verified emergency ops', iconName: 'FileCheck', color: 'blue' },
    { label: 'Audits Signed', value: 19, sublabel: 'Cryptographic sign-offs', iconName: 'Shield', color: 'purple' },
    { label: 'Bayesian Accuracy', value: '96.8%', sublabel: 'Triage verification rate', iconName: 'CheckCircle2', color: 'emerald' },
    { label: 'Avg Dispatch Response', value: '< 12 mins', sublabel: 'Target < 15 mins', iconName: 'Clock', color: 'amber' },
  ],
  analyst: [
    { label: 'Radar Scans Analyzed', value: 142, sublabel: 'Doppler echo arrays', iconName: 'Activity', color: 'blue' },
    { label: 'Priors Calibrated', value: 31, sublabel: 'Bayesian weighting nodes', iconName: 'Zap', color: 'purple' },
    { label: 'Model Concordance', value: '94.5%', sublabel: 'Nowcast verification score', iconName: 'CheckCircle2', color: 'emerald' },
    { label: 'Edge Inference Latency', value: '< 420 ms', sublabel: 'TensorRT pipeline', iconName: 'Clock', color: 'amber' },
  ],
  admin: [
    { label: 'System Grid Uptime', value: '99.98%', sublabel: 'High availability SLA', iconName: 'Activity', color: 'blue' },
    { label: 'Audits Verified', value: 42, sublabel: 'Master ledger blocks', iconName: 'Shield', color: 'purple' },
    { label: 'Zero-Trust Hardening', value: '99.1%', sublabel: 'SOC2 compliant identity', iconName: 'CheckCircle2', color: 'emerald' },
    { label: 'Active Ingestion Nodes', value: '8 Nodes', sublabel: 'CWC, IMD, Sensor feeds', iconName: 'Zap', color: 'amber' },
  ],
  citizen: [
    { label: 'Ground Reports Logged', value: 14, sublabel: 'Geotagged observations', iconName: 'FileCheck', color: 'blue' },
    { label: 'Community Upvotes', value: 48, sublabel: 'Civic trust endorsements', iconName: 'Users', color: 'purple' },
    { label: 'Ground Accuracy', value: '92.4%', sublabel: 'Validated field photo score', iconName: 'CheckCircle2', color: 'emerald' },
    { label: 'Civic Impact Rank', value: 'Top 5%', sublabel: 'Verified volunteer level', iconName: 'Award', color: 'amber' },
  ],
};

export const mockRoleSecurity: Record<string, RoleSecurityProfile> = {
  commander: {
    clearanceLevel: 'Level 4 (Tactical Command & Dispatch)',
    clearanceCode: 'LVL-4-TAC',
    clearanceColor: 'text-emerald-600',
    tokenExpiry: '8h (HS256 Bearer)',
    ledgerImmutability: 'SHA-256 Armed & Validated',
    permissions: [
      { key: 'dispatch', name: 'Direct Taskforce Dispatch', description: 'Deploy NDRF/SDRF battalions to active events', authorized: true },
      { key: 'override', name: 'Bayesian Manual Override', description: 'Elevate or suppress AI automated probability score', authorized: true },
      { key: 'verify', name: 'Emergency Event Triage', description: 'Publish verified multi-hazard disaster warnings', authorized: true },
      { key: 'sensors', name: 'Sensor Telemetry Config', description: 'Reconfigure hardware sensor reporting frequency', authorized: false },
      { key: 'reports', name: 'Ground Truth Report Ingestion', description: 'Submit and validate field observations', authorized: true },
      { key: 'admin', name: 'Platform Master Admin', description: 'Manage RBAC permissions and national node gateways', authorized: false },
    ],
  },
  analyst: {
    clearanceLevel: 'Level 3 (Scientific Analysis & IMD Nowcasting)',
    clearanceCode: 'LVL-3-SCI',
    clearanceColor: 'text-blue-600',
    tokenExpiry: '12h (HS256 Bearer)',
    ledgerImmutability: 'SHA-256 Armed & Validated',
    permissions: [
      { key: 'dispatch', name: 'Direct Taskforce Dispatch', description: 'Deploy NDRF/SDRF battalions to active events', authorized: false },
      { key: 'override', name: 'Bayesian Manual Override', description: 'Elevate or suppress AI automated probability score', authorized: true },
      { key: 'verify', name: 'Emergency Event Triage', description: 'Publish verified multi-hazard disaster warnings', authorized: true },
      { key: 'sensors', name: 'Sensor Telemetry Config', description: 'Reconfigure hardware sensor reporting frequency', authorized: true },
      { key: 'reports', name: 'Ground Truth Report Ingestion', description: 'Submit and validate field observations', authorized: true },
      { key: 'admin', name: 'Platform Master Admin', description: 'Manage RBAC permissions and national node gateways', authorized: false },
    ],
  },
  admin: {
    clearanceLevel: 'Level 5 (NDMA Strategic Root Command)',
    clearanceCode: 'LVL-5-ROOT',
    clearanceColor: 'text-purple-600',
    tokenExpiry: '4h (HS256 Bearer + 2FA)',
    ledgerImmutability: 'SHA-256 Armed & Master Locked',
    permissions: [
      { key: 'dispatch', name: 'Direct Taskforce Dispatch', description: 'Deploy NDRF/SDRF battalions to active events', authorized: true },
      { key: 'override', name: 'Bayesian Manual Override', description: 'Elevate or suppress AI automated probability score', authorized: true },
      { key: 'verify', name: 'Emergency Event Triage', description: 'Publish verified multi-hazard disaster warnings', authorized: true },
      { key: 'sensors', name: 'Sensor Telemetry Config', description: 'Reconfigure hardware sensor reporting frequency', authorized: true },
      { key: 'reports', name: 'Ground Truth Report Ingestion', description: 'Submit and validate field observations', authorized: true },
      { key: 'admin', name: 'Platform Master Admin', description: 'Manage RBAC permissions and national node gateways', authorized: true },
    ],
  },
  citizen: {
    clearanceLevel: 'Level 1 (Public Observation & Community Ground Truth)',
    clearanceCode: 'LVL-1-PUB',
    clearanceColor: 'text-amber-600',
    tokenExpiry: '24h (Session Key)',
    ledgerImmutability: 'SHA-256 Publicly Verifiable',
    permissions: [
      { key: 'dispatch', name: 'Direct Taskforce Dispatch', description: 'Deploy NDRF/SDRF battalions to active events', authorized: false },
      { key: 'override', name: 'Bayesian Manual Override', description: 'Elevate or suppress AI automated probability score', authorized: false },
      { key: 'verify', name: 'Emergency Event Triage', description: 'Publish verified multi-hazard disaster warnings', authorized: false },
      { key: 'sensors', name: 'Sensor Telemetry Config', description: 'Reconfigure hardware sensor reporting frequency', authorized: false },
      { key: 'reports', name: 'Ground Truth Report Ingestion', description: 'Submit and validate field observations', authorized: true },
      { key: 'admin', name: 'Platform Master Admin', description: 'Manage RBAC permissions and national node gateways', authorized: false },
    ],
  },
};

export const mockSixthSenseTeam: HackathonTeamData = {
  team_name: 'Sixth Sense',
  problem_statement: 'SIH26069 — National Weather Big Data Analytics Platform',
  theme: 'Disaster Management',
  tagline: 'From fragmented weather reports to verified, actionable weather events.',
  institution: 'Smart India Hackathon 2026',
  members: [
    {
      id: 'ss-1',
      name: 'Saba Saeed',
      role: 'Team Lead & Full-Stack Architect',
      specialty: 'Next.js Command Center, Real-Time WebSockets & System Design',
      bio: 'Directs architecture and cross-service orchestration for the INDRA intelligence platform.',
      avatar_initials: 'SS',
      github: 'https://github.com/SabaSaiid',
      badge: 'LEAD ARCHITECT',
    },
    {
      id: 'ss-2',
      name: 'Pritam Singh',
      role: 'AI & Bayesian Engine Lead',
      specialty: 'Bayesian Probability Fusion, Anomaly Detection & Cross-Source Weighting',
      bio: 'Formulated the 3-phase evidence synthesis engine condensing 127 raw signals into verified confidence receipts.',
      avatar_initials: 'PS',
      github: 'https://github.com/SabaSaiid/INDRA',
      badge: 'FUSION SCIENTIST',
    },
    {
      id: 'ss-3',
      name: 'Aditya',
      role: 'Geospatial Systems Engineer',
      specialty: 'Uber H3 Spatial Hexagons, DBSCAN Spatio-Temporal Clustering & PostGIS',
      bio: 'Implemented dynamic ε-neighborhood spatial clustering and convex hull boundary polygon calculation.',
      avatar_initials: 'AD',
      github: 'https://github.com/SabaSaiid/INDRA',
      badge: 'SPATIAL ENGINEER',
    },
    {
      id: 'ss-4',
      name: 'Salman Khurshid',
      role: 'Data Pipeline Architect',
      specialty: 'Redpanda / Kafka Streaming, Async Workers & Sensor Ingestion',
      bio: 'Engineered high-throughput consumer pipelines processing citizen reports, AWS gauges, and social signals.',
      avatar_initials: 'SK',
      github: 'https://github.com/SabaSaiid/INDRA',
      badge: 'PIPELINE LEAD',
    },
    {
      id: 'ss-5',
      name: 'Pragati Sahu',
      role: 'NLP & Semantic Deduplication Lead',
      specialty: 'TF-IDF + Cosine Similarity, Multilingual Signal Deduplication & Spam Filtering',
      bio: 'Created the semantic similarity layer that clusters repetitive emergency reports within spatial windows.',
      avatar_initials: 'PS',
      github: 'https://github.com/SabaSaiid/INDRA',
      badge: 'NLP SPECIALIST',
    },
    {
      id: 'ss-6',
      name: 'Meenal Sinha',
      role: 'Citizen Intelligence & Cloud Security',
      specialty: 'Crowdsourced Ground Verification, OAuth2 RBAC & Immutable SHA-256 Audit Logs',
      bio: 'Leads citizen ground-truth verification workflows and tamper-proof cryptographic audit tracking.',
      avatar_initials: 'MS',
      github: 'https://github.com/SabaSaiid/INDRA',
      badge: 'INTELLIGENCE LEAD',
    },
  ],
};

