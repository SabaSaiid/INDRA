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
  type KpiItem,
  type MapMarker,
  type RecentEvent,
  type DistributionItem,
  type TrendDataPoint,
  type FeedItem,
} from './mock-data';

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
    return await res.json();
  } catch (err) {
    console.warn('[INDRA] fetchEvents failed, using mock data:', err);
    return [];
  }
}

export function apiEventsToMapMarkers(events: ApiEvent[]): MapMarker[] {
  return events.map((ev) => ({
    id: ev.id,
    lat: ev.lat,
    lng: ev.lng,
    city: ev.city,
    state: ev.state,
    eventType: ev.eventType as any,
    severity: ev.severity as any,
    description: `${ev.eventType} — ${ev.quadrant}`,
    verification: ev.verification as any,
  }));
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
