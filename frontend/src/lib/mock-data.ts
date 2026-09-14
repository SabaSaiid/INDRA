import {
  LayoutDashboard,
  Map,
  CalendarClock,
  FileText,
  BarChart3,
  Bell,
  Database,
  Shield,
  type LucideIcon,
} from 'lucide-react';

// ─── Navigation Items ────────────────────────────────────────────────────────

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  href: string;
}

export const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, href: '/' },
  { id: 'live-map', label: 'Live Map', icon: Map, href: '/live-map' },
  { id: 'events', label: 'Events', icon: CalendarClock, href: '/events' },
  { id: 'reports', label: 'Reports', icon: FileText, href: '/reports' },
  { id: 'analytics', label: 'Analytics', icon: BarChart3, href: '/analytics' },
  { id: 'alerts', label: 'Alerts', icon: Bell, href: '/alerts' },
  { id: 'datasets', label: 'Datasets', icon: Database, href: '/datasets' },
  { id: 'admin', label: 'Admin Panel', icon: Shield, href: '/admin' },
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
}

export const mapMarkers: MapMarker[] = [
  {
    id: 'mk-1',
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
    id: 'mk-2',
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
    id: 'mk-3',
    lat: 19.076,
    lng: 72.8777,
    city: 'Mumbai',
    state: 'Maharashtra',
    eventType: 'Strong Winds',
    severity: 'moderate',
    description: 'High velocity winds in coastal areas',
    verification: 'verified',
  },
  {
    id: 'mk-4',
    lat: 28.6139,
    lng: 77.209,
    city: 'New Delhi',
    state: 'Delhi',
    eventType: 'Fog',
    severity: 'low',
    description: 'Dense fog advisory for morning hours',
    verification: 'verified',
  },
  {
    id: 'mk-5',
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
    id: 'mk-6',
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
    id: 'mk-7',
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
    id: 'mk-8',
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
    id: 'mk-9',
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
    id: 'mk-10',
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
    imageGradient: 'linear-gradient(135deg, #2563EB, #1E3A8A)',
  },
  {
    id: 'ev-2',
    city: 'Guwahati',
    state: 'Assam',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    verification: 'under-review',
    timestamp: new Date(now.getTime() - 3 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #F59E0B, #92400E)',
  },
  {
    id: 'ev-3',
    city: 'Mumbai',
    state: 'Maharashtra',
    eventType: 'Strong Winds',
    severity: 'moderate',
    verification: 'verified',
    timestamp: new Date(now.getTime() - 5 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #0EA5E9, #4338CA)',
  },
  {
    id: 'ev-4',
    city: 'New Delhi',
    state: 'Delhi',
    eventType: 'Fog',
    severity: 'low',
    verification: 'verified',
    timestamp: new Date(now.getTime() - 6 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #94A3B8, #334155)',
  },
  {
    id: 'ev-5',
    city: 'Chennai',
    state: 'Tamil Nadu',
    eventType: 'Heavy Rainfall',
    severity: 'high',
    verification: 'under-review',
    timestamp: new Date(now.getTime() - 8 * 60 * 60 * 1000),
    imageGradient: 'linear-gradient(135deg, #EF4444, #C2410C)',
  },
];

// ─── Event Distribution (Donut Chart) ────────────────────────────────────────

export interface DistributionItem {
  name: string;
  value: number;
  color: string;
}

export const eventDistribution: DistributionItem[] = [
  { name: 'Rainfall', value: 14, color: '#3B82F6' },
  { name: 'Flood', value: 8, color: '#F59E0B' },
  { name: 'Thunderstorm', value: 6, color: '#8B5CF6' },
  { name: 'Strong Winds', value: 5, color: '#2563EB' },
  { name: 'Fog', value: 3, color: '#64748B' },
  { name: 'Others', value: 1, color: '#94A3B8' },
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

export const severityConfig: Record<SeverityLevel, { label: string; color: string; bg: string; textColor: string }> = {
  critical: { label: 'Critical', color: '#EF4444', bg: '#FEE2E2', textColor: '#991B1B' },
  high: { label: 'High', color: '#F59E0B', bg: '#FEF3C7', textColor: '#92400E' },
  moderate: { label: 'Moderate', color: '#3B82F6', bg: '#DBEAFE', textColor: '#1E40AF' },
  low: { label: 'Low', color: '#64748B', bg: '#F1F5F9', textColor: '#334155' },
};

export const verificationConfig: Record<VerificationStatus, { label: string; color: string; bg: string; textColor: string; icon: string }> = {
  verified: { label: 'Verified', color: '#10B981', bg: '#D1FAE5', textColor: '#065F46', icon: '✓' },
  'under-review': { label: 'Under Review', color: '#F59E0B', bg: '#FEF3C7', textColor: '#92400E', icon: '○' },
};

export const feedSourceConfig: Record<FeedSourceType, { color: string; bg: string }> = {
  citizen: { color: '#2563EB', bg: '#EFF6FF' },
  social: { color: '#0F172A', bg: '#F1F5F9' },
  imd: { color: '#F59E0B', bg: '#FEF3C7' },
  news: { color: '#EF4444', bg: '#FEE2E2' },
};
