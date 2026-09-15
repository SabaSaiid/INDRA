/**
 * INDRA Platform — API Client
 * Typed fetch functions with mock-data fallback.
 * All functions try/catch and return mock data on failure.
 */

import {
  kpiData,
  mapMarkers,
  recentEvents,
  eventDistribution,
  reportsTrend,
  liveFeedItems,
  mockTeams,
  mockUserProfile,
  mockProfilesMap,
  mockSixthSenseTeam,
  type KpiItem,
  type MapMarker,
  type RecentEvent,
  type DistributionItem,
  type TrendDataPoint,
  type FeedItem,
  type TeamItem,
  type UserProfile,
  type HackathonTeamData,
} from './mock-data';
import { sanitizeIncidentCoordinate } from './geo-resolver';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

// ─── Dashboard Summary ───────────────────────────────────────────────────────

export interface DashboardSummary {
  total_reports: number;
  total_reports_delta_pct: number;
  verified_events: number;
  verified_events_delta_pct: number;
  critical_events: number;
  critical_events_delta_pct: number;
  citizen_reports: number;
  citizen_reports_delta_pct: number;
}

export async function fetchDashboardSummary(): Promise<KpiItem[]> {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/summary`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: DashboardSummary = await res.json();

    return [
      {
        id: 'total-reports',
        label: 'Total Reports',
        value: data.total_reports,
        delta: data.total_reports_delta_pct,
        deltaLabel: 'last 24h',
        color: '#2563EB',
        bgColor: '#EFF6FF',
        icon: 'reports',
      },
      {
        id: 'verified-events',
        label: 'Verified Events',
        value: data.verified_events,
        delta: data.verified_events_delta_pct,
        deltaLabel: 'last 24h',
        color: '#10B981',
        bgColor: '#D1FAE5',
        icon: 'verified',
      },
      {
        id: 'critical-events',
        label: 'Critical Events',
        value: data.critical_events,
        delta: data.critical_events_delta_pct,
        deltaLabel: 'last 24h',
        color: '#EF4444',
        bgColor: '#FEE2E2',
        icon: 'critical',
      },
      {
        id: 'citizen-reports',
        label: 'Citizen Reports',
        value: data.citizen_reports,
        delta: data.citizen_reports_delta_pct,
        deltaLabel: 'last 24h',
        color: '#8B5CF6',
        bgColor: '#EDE9FE',
        icon: 'citizens',
      },
    ];
  } catch (err) {
    console.warn('[INDRA] fetchDashboardSummary failed, using mock data:', err);
    return kpiData;
  }
}

// ─── Events (Map + Recent Events List) ───────────────────────────────────────

export interface ApiEvent {
  id: string;
  event_code: string;
  eventType: string;
  severity: string;
  confidence_score: number;
  verification: string;
  review_status: string;
  quadrant: string;
  impact_radius_km: number;
  lat: number;
  lng: number;
  city: string;
  state: string;
  imageGradient: string;
  verified_at: string;
  timestamp: string;
}

export const fallbackApiEvents: ApiEvent[] = mapMarkers.map((m, idx) => ({
  id: m.id,
  event_code: `WX-EV-2823${1827 + idx}-A`,
  eventType: m.eventType,
  severity: m.severity,
  confidence_score: m.confidence || Number((0.94 - idx * 0.02).toFixed(2)),
  verification: m.verification,
  review_status: m.verification === 'verified' ? 'AUTO_PUBLISHED' : 'PENDING_HUMAN_REVIEW',
  quadrant: `${m.city} Central Sector`,
  impact_radius_km: 5.0 + idx * 0.5,
  lat: m.lat,
  lng: m.lng,
  city: m.city,
  state: m.state,
  imageGradient: 'linear-gradient(135deg, #2563EB, #1E3A8A)',
  verified_at: new Date(Date.now() - idx * 3600000).toISOString(),
  timestamp: new Date(Date.now() - idx * 3600000).toISOString(),
}));

export async function fetchEvents(
  params?: { severity?: string; time_range?: string; bbox?: string }
): Promise<ApiEvent[]> {
  try {
    const searchParams = new URLSearchParams();
    if (params?.severity) searchParams.set('severity', params.severity);
    if (params?.time_range) searchParams.set('time_range', params.time_range);
    if (params?.bbox) searchParams.set('bbox', params.bbox);

    const url = `${API_BASE}/api/events${searchParams.toString() ? '?' + searchParams.toString() : ''}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data) || data.length === 0) throw new Error('Empty events response');
    return data;
  } catch (err) {
    console.warn('[INDRA] fetchEvents failed, using mock data:', err);
    let filtered = fallbackApiEvents;
    if (params?.severity) {
      filtered = filtered.filter(e => e.severity.toLowerCase() === params.severity!.toLowerCase());
    }
    return filtered;
  }
}

export function apiEventsToMapMarkers(events: ApiEvent[]): MapMarker[] {
  return events.map((ev, idx) => {
    const sanitized = sanitizeIncidentCoordinate(
      ev.lat,
      ev.lng,
      ev.city,
      ev.state,
      ev.eventType,
      idx
    );
    return {
      id: ev.id,
      lat: sanitized.lat,
      lng: sanitized.lng,
      city: sanitized.city || ev.city,
      state: sanitized.state || ev.state,
      eventType: ev.eventType as any,
      severity: ev.severity as any,
      description: `${ev.eventType} — ${ev.quadrant}`,
      verification: ev.verification as any,
    };
  });
}

export function apiEventsToRecentEvents(events: ApiEvent[]): RecentEvent[] {
  return events.slice(0, 5).map((ev) => ({
    id: ev.id,
    city: ev.city,
    state: ev.state,
    eventType: ev.eventType as any,
    severity: ev.severity as any,
    verification: ev.verification as any,
    timestamp: new Date(ev.timestamp || ev.verified_at),
    imageGradient: ev.imageGradient,
  }));
}

// ─── Event Distribution (Donut Chart) ────────────────────────────────────────

export async function fetchEventDistribution(): Promise<DistributionItem[]> {
  try {
    const res = await fetch(`${API_BASE}/api/events/distribution`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || data.length === 0) throw new Error('Empty distribution');
    return data;
  } catch (err) {
    console.warn('[INDRA] fetchEventDistribution failed, using mock data:', err);
    return eventDistribution;
  }
}

// ─── Reports Trend (Line Chart) ──────────────────────────────────────────────

export async function fetchReportsTrend(range: string = '7d'): Promise<TrendDataPoint[]> {
  try {
    const res = await fetch(`${API_BASE}/api/reports/trend?range=${range}`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || data.length === 0) throw new Error('Empty trend');
    return data;
  } catch (err) {
    console.warn('[INDRA] fetchReportsTrend failed, using mock data:', err);
    return reportsTrend;
  }
}

// ─── Live Feed ───────────────────────────────────────────────────────────────

export async function fetchRecentFeed(limit: number = 10): Promise<FeedItem[]> {
  try {
    const res = await fetch(`${API_BASE}/api/feed/recent?limit=${limit}`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || data.length === 0) throw new Error('Empty feed');
    return data;
  } catch (err) {
    console.warn('[INDRA] fetchRecentFeed failed, using mock data:', err);
    return liveFeedItems;
  }
}

// ─── Teams (Disaster Response Units & Hub) ───────────────────────────────────

export async function fetchTeams(params?: {
  agency?: string;
  status?: string;
  city?: string;
}): Promise<TeamItem[]> {
  try {
    const searchParams = new URLSearchParams();
    if (params?.agency) searchParams.set('agency', params.agency);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.city) searchParams.set('city', params.city);

    const url = `${API_BASE}/api/teams${searchParams.toString() ? '?' + searchParams.toString() : ''}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || data.length === 0) return mockTeams;
    return data;
  } catch (err) {
    console.warn('[INDRA] fetchTeams failed, using mock data:', err);
    let filtered = mockTeams;
    if (params?.agency) filtered = filtered.filter(t => t.agency.toLowerCase() === params.agency!.toLowerCase());
    if (params?.status) filtered = filtered.filter(t => t.status.toLowerCase() === params.status!.toLowerCase());
    if (params?.city) filtered = filtered.filter(t => t.city.toLowerCase().includes(params.city!.toLowerCase()));
    return filtered;
  }
}

export async function fetchTeamById(teamId: string): Promise<TeamItem> {
  try {
    const res = await fetch(`${API_BASE}/api/teams/${teamId}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[INDRA] fetchTeamById(${teamId}) failed, using mock data:`, err);
    const match = mockTeams.find(t => t.id === teamId || t.team_code === teamId);
    return match || mockTeams[0];
  }
}

export async function assignTeamToEvent(teamId: string, eventId: string | null): Promise<any> {
  try {
    const res = await fetch(`${API_BASE}/api/teams/${teamId}/assign`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[INDRA] assignTeamToEvent failed, updating local state:`, err);
    const team = mockTeams.find(t => t.id === teamId || t.team_code === teamId);
    if (team) {
      team.status = eventId ? 'DEPLOYED' : 'AVAILABLE';
      team.assigned_event_code = eventId ? (eventId.startsWith('WX-') ? eventId : 'WX-EV-28231827-A') : null;
    }
    return { status: eventId ? 'DEPLOYED' : 'AVAILABLE' };
  }
}

export async function fetchHackathonTeam(): Promise<HackathonTeamData> {
  try {
    const res = await fetch(`${API_BASE}/api/teams/hackathon/sixth-sense`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[INDRA] fetchHackathonTeam failed, using mock data:', err);
    return mockSixthSenseTeam;
  }
}

// ─── User Profile & Identity ──────────────────────────────────────────────────

export async function fetchUserProfile(username?: string): Promise<UserProfile> {
  try {
    const url = username
      ? `${API_BASE}/api/profile/me?user=${username}`
      : `${API_BASE}/api/profile/me`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[INDRA] fetchUserProfile failed, using mock data:', err);
    if (username && mockProfilesMap[username]) {
      return mockProfilesMap[username];
    }
    return mockUserProfile;
  }
}

export async function updateUserProfile(data: Partial<UserProfile>, username: string = 'commander'): Promise<UserProfile> {
  try {
    const res = await fetch(`${API_BASE}/api/profile/me?user=${username}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[INDRA] updateUserProfile failed, updating local mock state:', err);
    if (data.full_name) {
      data.avatar_initials = data.full_name
        .trim()
        .split(/\s+/)
        .map((p) => p[0])
        .slice(0, 2)
        .join('')
        .toUpperCase();
    }
    if (username && mockProfilesMap[username]) {
      Object.assign(mockProfilesMap[username], data);
      return mockProfilesMap[username];
    }
    Object.assign(mockUserProfile, data);
    return mockUserProfile;
  }
}

