/**
 * INDRA Platform — API Client
 *
 * **Every value returned by this module came from the backend. There are no
 * fallbacks and no invented rows.**
 *
 * This file used to end every function with `catch { return mockData }`, and
 * several of them treated an empty list as a failure:
 *
 *     if (!Array.isArray(data) || data.length === 0) throw new Error('Empty');
 *     ...
 *     catch (err) { return fallbackApiEvents; }
 *
 * Between them those two lines meant an empty database rendered a *full*
 * dashboard. The first seconds of a live demo are exactly when the database is
 * empty, so the screen showed CRITICAL events at 0.94 confidence and
 * AUTO_PUBLISHED — values the real pipeline cannot currently produce at all,
 * since the maximum achievable confidence is 0.80 while the vision and anomaly
 * factors are offline. Nobody could tell the backend was down, because the
 * failure looked exactly like success.
 *
 * The rules now:
 *
 * 1. **An empty list is a result, not an error.** `[]` is returned as `[]`. The
 *    component renders an empty state. An empty dashboard that fills up as
 *    reports arrive is both honest and a better demonstration.
 * 2. **A failure throws.** Callers catch it and show an error state that says
 *    the backend is unreachable. A failure must never be indistinguishable
 *    from data.
 * 3. **Nothing in this file may import invented data.** `ui-config` holds types
 *    and presentation constants only.
 */

import {
  type KpiItem,
  type MapMarker,
  type RecentEvent,
  type DistributionItem,
  type TrendDataPoint,
  type FeedItem,
  type TeamItem,
  type UserProfile,
  type HackathonTeamData,
} from './ui-config';
import { sanitizeIncidentCoordinate } from './geo-resolver';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

/** Thrown when the backend could not be reached or answered with an error. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly endpoint: string;

  constructor(endpoint: string, status: number | null, message: string) {
    super(message);
    this.name = 'ApiError';
    this.endpoint = endpoint;
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: 'no-store' });
  } catch (err) {
    throw new ApiError(path, null, `Cannot reach the INDRA backend at ${API_BASE}`);
  }
  if (!res.ok) {
    throw new ApiError(path, res.status, `Backend returned HTTP ${res.status}`);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(path, res.status, 'Backend returned a malformed response');
  }
}

/** An endpoint that should return a list but did not is a backend defect, not data. */
function asArray<T>(value: unknown, path: string): T[] {
  if (!Array.isArray(value)) {
    throw new ApiError(path, 200, 'Expected a list from the backend');
  }
  return value as T[];
}

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
  const data = await getJson<DashboardSummary>('/api/dashboard/summary');

  // Colours and labels are design; the numbers are the backend's.
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

/**
 * Request deduplication, kept from the original client: the map and the recent
 * events list ask for the same URL at the same moment on first paint.
 *
 * A rejected promise is evicted immediately. Caching a failure for 15 s would
 * make a backend that recovered in between look like it was still down.
 */
const eventsInFlight = new Map<string, { promise: Promise<ApiEvent[]>; timestamp: number }>();
const EVENTS_CACHE_TTL_MS = 15000;

export async function fetchEvents(
  params?: { severity?: string; time_range?: string; bbox?: string }
): Promise<ApiEvent[]> {
  const searchParams = new URLSearchParams();
  if (params?.severity) searchParams.set('severity', params.severity);
  if (params?.time_range) searchParams.set('time_range', params.time_range);
  if (params?.bbox) searchParams.set('bbox', params.bbox);

  const path = `/api/events${searchParams.toString() ? '?' + searchParams.toString() : ''}`;
  const now = Date.now();

  const cached = eventsInFlight.get(path);
  if (cached && now - cached.timestamp < EVENTS_CACHE_TTL_MS) {
    return cached.promise;
  }

  const fetchPromise = getJson<unknown>(path)
    .then((data) => asArray<ApiEvent>(data, path))
    .catch((err) => {
      eventsInFlight.delete(path);
      throw err;
    });

  eventsInFlight.set(path, { promise: fetchPromise, timestamp: now });
  return fetchPromise;
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
  return events.slice(0, 10).map((ev) => ({
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

export async function fetchEventDistribution(
  groupBy: 'hazard' | 'severity' = 'hazard',
  timeRange: string = '7d'
): Promise<DistributionItem[]> {
  const path = `/api/events/distribution?by=${groupBy}&time_range=${timeRange}`;
  const data = asArray<any>(await getJson<unknown>(path), path);

  return data.map((item: any) => {
    const val = Number(item.value ?? item.count ?? 0);
    return {
      name: String(item.name || 'Unknown'),
      value: val,
      count: Number(item.count ?? val),
      color: item.color || '#94A3B8',
    };
  });
}

// ─── Reports Trend (Line Chart) ──────────────────────────────────────────────

export async function fetchReportsTrend(range: string = '7d'): Promise<TrendDataPoint[]> {
  const path = `/api/reports/trend?range=${range}`;
  return asArray<TrendDataPoint>(await getJson<unknown>(path), path);
}

// ─── Live Feed ───────────────────────────────────────────────────────────────

export async function fetchRecentFeed(limit: number = 10): Promise<FeedItem[]> {
  const path = `/api/feed/recent?limit=${limit}`;
  return asArray<FeedItem>(await getJson<unknown>(path), path);
}

// ─── Agency Alerts (SACHET / NDMA — IMD, CWC and state SDMA warnings) ────────

export interface AgencyAlert {
  id: string;
  identifier: string;
  sender: string | null;
  event: string | null;
  severity: string | null;
  raw_severity: string | null;
  certainty: string | null;
  urgency: string | null;
  headline: string | null;
  area_desc: string | null;
  effective_at: string | null;
  expires_at: string | null;
  sent_at: string | null;
  has_polygon: boolean;
}

export async function fetchAgencyAlerts(limit: number = 20): Promise<AgencyAlert[]> {
  const path = `/api/alerts/agency?limit=${limit}`;
  return asArray<AgencyAlert>(await getJson<unknown>(path), path);
}

// ─── Teams (Disaster Response Units & Hub) ───────────────────────────────────

export async function fetchTeams(params?: {
  agency?: string;
  status?: string;
  city?: string;
}): Promise<TeamItem[]> {
  const searchParams = new URLSearchParams();
  if (params?.agency) searchParams.set('agency', params.agency);
  if (params?.status) searchParams.set('status', params.status);
  if (params?.city) searchParams.set('city', params.city);

  const path = `/api/teams${searchParams.toString() ? '?' + searchParams.toString() : ''}`;
  return asArray<TeamItem>(await getJson<unknown>(path), path);
}

export async function fetchTeamById(teamId: string): Promise<TeamItem> {
  return getJson<TeamItem>(`/api/teams/${teamId}`);
}

export async function assignTeamToEvent(teamId: string, eventId: string | null): Promise<any> {
  const path = `/api/teams/${teamId}/assign`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId }),
    });
  } catch {
    throw new ApiError(path, null, `Cannot reach the INDRA backend at ${API_BASE}`);
  }
  if (!res.ok) {
    // A mutation that silently "succeeds" locally is worse than one that fails
    // loudly: the operator believes a team was dispatched when none was.
    throw new ApiError(path, res.status, `Assignment failed (HTTP ${res.status})`);
  }
  return res.json();
}

export async function fetchHackathonTeam(): Promise<HackathonTeamData> {
  return getJson<HackathonTeamData>('/api/teams/hackathon/sixth-sense');
}

// ─── User Profile & Identity ──────────────────────────────────────────────────

export async function fetchUserProfile(username?: string): Promise<UserProfile> {
  const path = username ? `/api/profile/me?user=${username}` : '/api/profile/me';
  return getJson<UserProfile>(path);
}

export async function updateUserProfile(
  data: Partial<UserProfile>,
  username: string = 'commander'
): Promise<UserProfile> {
  const path = `/api/profile/me?user=${username}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  } catch {
    throw new ApiError(path, null, `Cannot reach the INDRA backend at ${API_BASE}`);
  }
  if (!res.ok) {
    throw new ApiError(path, res.status, `Profile update failed (HTTP ${res.status})`);
  }
  return res.json();
}
