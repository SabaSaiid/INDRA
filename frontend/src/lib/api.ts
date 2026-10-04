/**
 * INDRA Platform — API Client
 *
 * **Every value returned by this module came from the backend. There are no
 * fallbacks and no invented rows.**
 *
 * The rules:
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
import { API_BASE } from './api-base';
import { authHeaders, getSession, signOut } from './auth';

export type { FeedItem };
export const ALERT_ENGINE_BASE = process.env.NEXT_PUBLIC_ALERT_ENGINE_BASE_URL || 'http://localhost:8001';
export const ALERT_ENGINE_WS = process.env.NEXT_PUBLIC_ALERT_ENGINE_WS_URL || 'ws://localhost:8001/ws/alerts';

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

// ─── Authenticated calls ─────────────────────────────────────────────────────

/**
 * fetch with the signed-in operator's token. A 401 on a call that carried one
 * means the backend no longer accepts it (expired, or the account's login was
 * disabled), so the tab signs out rather than keep offering what will fail.
 */
async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const auth = authHeaders();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { ...(init.headers as Record<string, string> | undefined), ...auth },
    });
  } catch {
    throw new ApiError(path, null, `Cannot reach the INDRA backend at ${API_BASE}`);
  }
  if (res.status === 401 && auth.Authorization) signOut();
  return res;
}

/** A readable reason for a refused mutation, so the UI can say why. */
function mutationError(path: string, status: number, action: string): ApiError {
  if (status === 401) return new ApiError(path, status, `${action} needs you to sign in`);
  if (status === 403) return new ApiError(path, status, `${action} needs a Commander or Admin account`);
  if (status === 404) return new ApiError(path, status, `${action} failed: not found`);
  return new ApiError(path, status, `${action} failed (HTTP ${status})`);
}

// ─── Event Detail ────────────────────────────────────────────────────────────

export interface EventDetail {
  id: string;
  event_code: string;
  event_type: string;
  event_type_display: string;
  severity: string;
  severity_display: string;
  confidence_score: number;
  review_status: string;
  verification: string;
  quadrant: string;
  impact_radius_km: number;
  center: { lat: number; lng: number };
  boundary_geojson: string | null;
  verification_receipt: Record<string, any>;
  verified_at: string;
  /** Null when the backend could not place the event (see formatPlace). */
  city: string | null;
  state: string | null;
  place_precision?: string | null;
}

export async function fetchEventDetail(eventId: string): Promise<EventDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/api/events/${eventId}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[INDRA] fetchEventDetail(${eventId}) failed:`, err);
    return null;
  }
}

// ─── Event Provenance (Auth Required) ────────────────────────────────────────

export interface ProvenanceReport {
  id: string;
  source_type: string;
  raw_text: string;
  latitude: number;
  longitude: number;
  credibility_score: number;
  created_at: string;
  /** Operator who filed an OFFICIAL_DISPATCH; null for an anonymous citizen report. */
  submitted_by?: string | null;
}

export interface AuditEntry {
  seq: number;
  action_taken: string;
  operator_id: string;
  reason: string | null;
  details: Record<string, any> | null;
  logged_at: string;
  sha256_hash: string;
  prev_hash: string;
}

export interface ProvenanceData {
  event: {
    id: string;
    event_code: string;
    review_status: string;
    severity: string;
    confidence_score: number;
    verification_receipt: Record<string, any>;
  };
  reports: ProvenanceReport[];
  audit: AuditEntry[];
  chain: { valid: boolean; checked: number; error?: string };
}

/** Needs an Analyst, Commander or Admin session; null when refused or unreachable. */
export async function fetchEventProvenance(eventId: string): Promise<ProvenanceData | null> {
  try {
    const res = await authedFetch(`/api/events/${eventId}/provenance`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[INDRA] fetchEventProvenance(${eventId}) failed:`, err);
    return null;
  }
}

// ─── Event Review (Auth Required: COMMANDER / ADMIN) ─────────────────────────

export interface ReviewResponse extends EventDetail {}

export async function reviewEvent(
  eventId: string,
  action: 'approve' | 'reject' | 'override_severity',
  reason: string,
  newSeverity?: string
): Promise<{ success: boolean; data?: ReviewResponse; error?: string }> {
  if (!getSession()) {
    return { success: false, error: 'Sign in as a Commander or Admin to review' };
  }
  try {
    const body: Record<string, any> = { action, reason };
    if (action === 'override_severity' && newSeverity) {
      body.new_severity = newSeverity;
    }
    const res = await authedFetch(`/api/events/${eventId}/review`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      return { success: false, error: 'Your session has ended. Sign in again to review.' };
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      return { success: false, error: err.detail || `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: any) {
    console.warn(`[INDRA] reviewEvent(${eventId}) failed:`, err);
    return { success: false, error: err?.message || 'Network error' };
  }
}

// ─── Citizen Report Submission ───────────────────────────────────────────────

export interface ReportSubmission {
  latitude: number;
  longitude: number;
  text: string;
  media_url?: string;
}

export async function submitCitizenReport(
  report: ReportSubmission
): Promise<{ success: boolean; data?: any; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}/api/reports/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      return { success: false, error: err.detail || `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: any) {
    console.warn('[INDRA] submitCitizenReport failed:', err);
    return { success: false, error: err?.message || 'Network error' };
  }
}

/**
 * File a report from a trusted field source (a control room, an SDRF team)
 * through POST /api/reports/official (BUG-025). Needs a Commander or Admin
 * session; the backend stores it as OFFICIAL_DISPATCH with the operator's name,
 * which lifts the cluster's source reliability to 1.00. The public route above
 * can never claim a source, by design.
 */
export async function submitOfficialReport(
  report: ReportSubmission
): Promise<{ success: boolean; data?: any; error?: string }> {
  if (!getSession()) {
    return { success: false, error: 'Sign in as a Commander or Admin to file an official dispatch' };
  }
  try {
    const res = await authedFetch('/api/reports/official', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    });
    if (res.status === 401) {
      return { success: false, error: 'Your session has ended. Sign in again to file an official dispatch.' };
    }
    if (res.status === 403) {
      return { success: false, error: 'Filing an official dispatch needs a Commander or Admin account' };
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      return { success: false, error: err.detail || `HTTP ${res.status}` };
    }
    return { success: true, data: await res.json() };
  } catch (err: any) {
    console.warn('[INDRA] submitOfficialReport failed:', err);
    return { success: false, error: err?.message || 'Network error' };
  }
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
  /** Escalated or quarantined — counted separately so "Verified" can mean it. */
  awaiting_review: number;
  /** Unexpired CAP warnings currently in force, from the SACHET feed. */
  active_alerts: number;
}

/** The summary's raw counts, for pages that quote a figure rather than a KPI tile. */
export async function fetchSummaryCounts(): Promise<DashboardSummary> {
  return getJson<DashboardSummary>('/api/dashboard/summary');
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
    // "Verified Events" used to count everything the pipeline had not
    // rejected, so a quarantined event the engine itself called "Noise" was
    // advertised as verified. Splitting the tile corrects the number without
    // hiding anything: what left the first tile appears in this one.
    {
      id: 'awaiting-review',
      label: 'Awaiting Review',
      value: data.awaiting_review ?? 0,
      // No comparison window exists for this figure. A 0 here printed "0%",
      // which reads as "measured, unchanged".
      delta: null,
      deltaLabel: 'review queue',
      color: '#D97706',
      bgColor: '#FEF3C7',
      icon: 'critical',
    },
    // Live official warnings in force. These were being polled and stored all
    // along and appeared nowhere an officer would look.
    {
      id: 'active-alerts',
      label: 'Active Alerts',
      value: data.active_alerts ?? 0,
      delta: null,
      deltaLabel: 'in force now',
      color: '#0EA5E9',
      bgColor: '#E0F2FE',
      icon: 'verified',
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
  /** District name, or null when the backend could not place the point. */
  city: string | null;
  /** State name, or null alongside a null city. */
  state: string | null;
  /** 'district' (inside it) | 'near' (close to it) | null (unresolved). */
  place_precision?: string | null;
  imageGradient: string;
  verified_at: string;
  timestamp: string;
  corroborating_reports_count?: number;
}

/**
 * One place name from a district, a state and how sure the backend was.
 *
 * Every surface that shows a location goes through this, because each one
 * used to join the two fields itself and got it subtly wrong: with an empty
 * state, `{city}, {state}` rendered the literal string "Unknown, ", trailing
 * comma and all.
 *
 * A null name is rendered as an explicit "Location unresolved" rather than
 * hidden or filled in. The backend only sends null when its gazetteer
 * genuinely could not place the coordinates, and that is worth showing: an
 * operator who sees a pin with no name knows to check it, where one who sees
 * a plausible name has no reason to.
 */
export function formatPlace(
  city?: string | null,
  state?: string | null,
  precision?: string | null
): string {
  const parts = [city, state].filter((p): p is string => Boolean(p && p.trim()));
  if (parts.length === 0) return 'Location unresolved';
  const name = parts.join(', ');
  return precision === 'near' ? `near ${name}` : name;
}

/**
 * Request deduplication, kept from the original client: the map and the recent
 * events list ask for the same URL at the same moment on first paint.
 *
 * A rejected promise is evicted immediately. Caching a failure for 15 s would
 * make a backend that recovered in between look like it was still down.
 *
 * The window is 2 s, not the 15 s it was. A VERIFIED_EVENT arriving within 15 s
 * of the last fetch made every listener's refetch get the cached, pre-event
 * list back, so a new event could take a reload to appear.
 */
const eventsInFlight = new Map<string, { promise: Promise<ApiEvent[]>; timestamp: number }>();
const EVENTS_CACHE_TTL_MS = 2000;

export async function fetchEvents(
  params?: {
    severity?: string;
    time_range?: string;
    bbox?: string;
    /** YYYY-MM-DD (an IST day) or ISO instant, inclusive. */
    from?: string;
    limit?: number;
  }
): Promise<ApiEvent[]> {
  const searchParams = new URLSearchParams();
  if (params?.severity) searchParams.set('severity', params.severity);
  if (params?.time_range) searchParams.set('time_range', params.time_range);
  if (params?.bbox) searchParams.set('bbox', params.bbox);
  if (params?.from) searchParams.set('from', params.from);
  if (params?.limit) searchParams.set('limit', String(params.limit));

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

/**
 * True when both values are finite numbers. `Number.isFinite` rather than a
 * null check, because `Number(null)` is 0 and would put a pin in the Gulf of
 * Guinea.
 */
function hasPlottableCoords(lat: unknown, lng: unknown): boolean {
  return typeof lat === 'number' && typeof lng === 'number' && Number.isFinite(lat) && Number.isFinite(lng);
}

/**
 * Events as map markers, at the coordinates the API sent. An event without
 * plottable coordinates is left off the map and logged; it is never moved to a
 * plausible place.
 */
export function apiEventsToMapMarkers(events: ApiEvent[]): MapMarker[] {
  return events
    .filter((ev) => {
      if (hasPlottableCoords(ev.lat, ev.lng)) return true;
      console.warn(`[INDRA map] event ${ev.id} has no plottable coordinates (${ev.lat}, ${ev.lng}); not drawn`);
      return false;
    })
    .map((ev) => ({
      id: ev.id,
      lat: ev.lat,
      lng: ev.lng,
      city: ev.city ?? '',
      state: ev.state ?? '',
      placeLabel: formatPlace(ev.city, ev.state, ev.place_precision),
      eventType: ev.eventType as any,
      severity: ev.severity as any,
      description: `${ev.eventType} — ${ev.quadrant}`,
      verification: ev.verification as any,
      layer: 'event' as const,
    }));
}

export function apiEventsToRecentEvents(events: ApiEvent[]): RecentEvent[] {
  return events.slice(0, 10).map((ev) => ({
    id: ev.id,
    city: ev.city ?? '',
    state: ev.state ?? '',
    placeLabel: formatPlace(ev.city, ev.state, ev.place_precision),
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

/**
 * Reports, events and official warnings in force, newest first. A backend
 * older than 24 Sep ignores `include` and sends reports only, without `at`.
 */
export async function fetchRecentFeed(
  limit: number = 10,
  include?: Array<'reports' | 'events' | 'warnings'>
): Promise<FeedItem[]> {
  const inc = include?.length ? `&include=${include.join(',')}` : '';
  const path = `/api/feed/recent?limit=${limit}${inc}`;
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
  /**
   * Resolved from area_desc, because NDMA answers 403 on the CAP polygon
   * endpoint and not one stored alert carries a geometry. Null when the
   * alert's scope is below district level (state SDMAs issue mandal-level
   * warnings) — those stay off the map rather than being pinned to a
   * district centroid they are not actually in.
   */
  lat: number | null;
  lng: number | null;
  location_label: string | null;
  /** 'district' | 'state' | null — 'state' means the whole state, not a point. */
  location_precision: string | null;
  districts_matched: number;
}

export async function fetchAgencyAlerts(
  limit: number = 20,
  includeExpired = false
): Promise<AgencyAlert[]> {
  const path = `/api/alerts/agency?limit=${limit}&include_expired=${includeExpired}`;
  return asArray<AgencyAlert>(await getJson<unknown>(path), path);
}

/**
 * Live agency warnings as map markers.
 *
 * Alerts with no resolvable location are dropped rather than placed
 * somewhere plausible, so this can return fewer markers than there are
 * alerts. That gap is real and the alert list still shows every one.
 */
export function agencyAlertsToMapMarkers(alerts: AgencyAlert[]): MapMarker[] {
  return alerts
    .filter((a) => hasPlottableCoords(a.lat, a.lng))
    .map((a) => ({
      id: `alert-${a.id}`,
      lat: a.lat as number,
      lng: a.lng as number,
      city: a.location_label ?? '',
      state: '',
      placeLabel:
        a.location_precision === 'state'
          ? `${a.location_label} (state-wide)`
          : formatPlace(a.location_label, null),
      layer: 'alert' as const,
      // A warning that names no hazard or severity is shown as exactly that.
      eventType: (a.event || 'Unnamed warning') as any,
      severity: (a.severity ? a.severity.toLowerCase() : 'unrated') as any,
      description: a.headline || a.event || 'Agency warning',
      title: a.sender || 'Agency',
      verification: 'verified' as any,
    }));
}

const WARNING_SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MODERATE', 'ADVISORY'];
/** CAP severity mapped onto IMD's colour code, as the Early Warnings page shows it. */
const WARNING_SEVERITY_STYLE: Record<string, { name: string; color: string }> = {
  CRITICAL: { name: 'Red', color: '#DC2626' },
  HIGH: { name: 'Orange', color: '#F97316' },
  MODERATE: { name: 'Yellow', color: '#EAB308' },
  ADVISORY: { name: 'Advisory', color: '#10B981' },
};
const WARNING_HAZARD_COLORS = ['#2563EB', '#F59E0B', '#8B5CF6', '#0EA5E9', '#E11D48', '#10B981', '#64748B'];

/**
 * Official warnings in force grouped for the distribution donut: by the hazard
 * the agency named, or by severity colour. Counted from the alerts as served,
 * so the slices always add up to the number of warnings listed.
 */
export function agencyAlertsToDistribution(
  alerts: AgencyAlert[],
  by: 'hazard' | 'severity'
): DistributionItem[] {
  const counts = new Map<string, number>();
  for (const a of alerts) {
    const key = by === 'severity' ? (a.severity || 'UNRATED') : (a.event || 'Unnamed hazard').trim();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  if (by === 'severity') {
    const keys = [...WARNING_SEVERITY_ORDER, 'UNRATED'].filter((k) => counts.has(k));
    return keys.map((k) => ({
      name: WARNING_SEVERITY_STYLE[k]?.name ?? 'Unrated',
      value: counts.get(k)!,
      count: counts.get(k)!,
      color: WARNING_SEVERITY_STYLE[k]?.color ?? '#94A3B8',
    }));
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = sorted.slice(0, 6);
  const rest = sorted.slice(6).reduce((n, [, c]) => n + c, 0);
  const items = top.map(([name, n], i) => ({
    name,
    value: n,
    count: n,
    color: WARNING_HAZARD_COLORS[i % WARNING_HAZARD_COLORS.length],
  }));
  if (rest > 0) items.push({ name: 'Others', value: rest, count: rest, color: '#94A3B8' });
  return items;
}

// ─── Field Reports (raw citizen reports, not yet events) ─────────────────────

export interface FieldReport {
  id: string;
  source_type: string;
  text: string;
  lat: number;
  lng: number;
  district: string | null;
  state: string | null;
  created_at: string | null;
  fused: boolean;
  duplicate: boolean;
  depth_cm: number | null;
  /** The event it joined, when fused (backend since 24 Sep). */
  event_id?: string | null;
  event_code?: string | null;
  observed_at?: string | null;
  credibility_score?: number | null;
  media_url?: string | null;
  place_precision?: string | null;
}

/**
 * Stored reports, newest first. `unfusedOnly` (the map's default) leaves out
 * reports already drawn as their event and suppressed duplicates; the Field
 * Reports page asks for everything.
 */
export async function fetchFieldReports(
  limit: number = 100,
  hours: number = 72,
  unfusedOnly: boolean = true
): Promise<FieldReport[]> {
  const path = `/api/reports/recent?limit=${limit}&hours=${hours}&unfused_only=${unfusedOnly}`;
  return asArray<FieldReport>(await getJson<unknown>(path), path);
}

/**
 * Raw reports as map markers.
 *
 * These carry `layer: 'report'` and the map must draw them distinctly.
 * Nothing here has been clustered, corroborated or scored — drawing an
 * unreviewed citizen claim like a verified event is the one thing a national
 * console must not do.
 *
 * /api/reports/recent carries no hazard or severity, so a report is a
 * 'Citizen report' of 'unrated' severity rather than a guessed classification.
 */
export function fieldReportsToMapMarkers(reports: FieldReport[]): MapMarker[] {
  return reports
    .filter((r) => {
      if (hasPlottableCoords(r.lat, r.lng)) return true;
      console.warn(`[INDRA map] report ${r.id} has no plottable coordinates (${r.lat}, ${r.lng}); not drawn`);
      return false;
    })
    .map((r) => ({
      id: `report-${r.id}`,
      lat: r.lat,
      lng: r.lng,
      city: r.district ?? '',
      state: r.state ?? '',
      placeLabel: formatPlace(r.district, r.state),
      layer: 'report' as const,
      eventType: 'Citizen report' as any,
      severity: 'unrated' as any,
      description: r.text,
      verification: 'under-review' as any,
    }));
}

// ─── Data sources (GET /api/meta/sources) ────────────────────────────────────

export interface DataSourceStatus {
  feed: string;
  kind: string;
  title?: string;
  enabled: boolean;
  /** 'ok' | 'stale' | 'failing' | 'disabled' */
  status: string;
  last_success_at: string | null;
  last_error: string | null;
  rows_24h: number;
  rows_total: number;
  poll_interval_s: number | null;
  stale_after_s?: number | null;
  /** 'newest_row' until Phase 2's heartbeat table; 'push' for intake routes. */
  basis?: string;
}

/** Throws ApiError 404 on a backend older than 24 Sep, which has no such route. */
export async function fetchDataSources(): Promise<DataSourceStatus[]> {
  const path = '/api/meta/sources';
  const body = await getJson<{ feeds?: unknown }>(path);
  return asArray<DataSourceStatus>(body?.feeds, path);
}

// ─── Rainfall stations (GET /api/geo/stations) ───────────────────────────────

export interface RainfallStation {
  station_code: string;
  station_name: string;
  agency: string;
  lat: number;
  lng: number;
  /** Trailing 24 h accumulation at the newest observation hour. */
  rainfall_mm: number | null;
  recorded_at: string;
  series: Array<{ at: string; rainfall_mm: number | null }>;
}

export async function fetchStations(): Promise<RainfallStation[]> {
  const path = '/api/geo/stations';
  return asArray<RainfallStation>(await getJson<unknown>(path), path);
}

// ─── Geo Heatmap (GET /api/geo/heatmap) ─────────────────────────────────────

export interface GeoHeatmapCell {
  h3: string;
  lat: number;
  lng: number;
  report_count: number;
  linked_report_count: number;
}

export interface GeoHeatmapResponse {
  resolution: number;
  window: string;
  generated_at: string;
  cells: GeoHeatmapCell[];
}

export async function fetchGeoHeatmap(params?: {
  window?: '24h' | '48h' | '7d';
  resolution?: number;
}): Promise<GeoHeatmapResponse> {
  const searchParams = new URLSearchParams();
  if (params?.window) searchParams.set('window', params.window);
  if (params?.resolution) searchParams.set('resolution', String(params.resolution));

  const path = `/api/geo/heatmap${searchParams.toString() ? '?' + searchParams.toString() : ''}`;
  return getJson<GeoHeatmapResponse>(path);
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

/**
 * Dispatch a team to an event (its UUID), or recall it with null.
 *
 * Needs a COMMANDER or ADMIN token since BUG-009, sent as the signed-in
 * operator; an analyst or citizen account gets a 403 with a reason the page
 * can show.
 */
export async function assignTeamToEvent(teamId: string, eventId: string | null): Promise<any> {
  const path = `/api/teams/${teamId}/assign`;
  const res = await authedFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_id: eventId }),
  });
  if (!res.ok) {
    // A mutation that silently "succeeds" locally is worse than one that fails
    // loudly: the operator believes a team was dispatched when none was.
    throw mutationError(path, res.status, eventId ? 'Dispatch' : 'Recall');
  }
  return res.json();
}

export async function fetchHackathonTeam(): Promise<HackathonTeamData> {
  return getJson<HackathonTeamData>('/api/teams/hackathon/sixth-sense');
}

// ─── User Profile & Identity ──────────────────────────────────────────────────

/** The signed-in operator's profile: GET /api/profile/me with the session's token. */
export async function fetchUserProfile(): Promise<UserProfile> {
  const path = '/api/profile/me';
  if (!getSession()) throw new ApiError(path, 401, 'Not signed in');
  const res = await authedFetch(path, { cache: 'no-store' });
  if (!res.ok) {
    throw new ApiError(path, res.status, `Backend returned HTTP ${res.status}`);
  }
  try {
    return (await res.json()) as UserProfile;
  } catch {
    throw new ApiError(path, res.status, 'Backend returned a malformed response');
  }
}

/**
 * Save the signed-in operator's own profile. The backend edits the token's
 * subject and nothing else (BUG-009).
 */
export async function updateUserProfile(data: Partial<UserProfile>): Promise<UserProfile> {
  const path = '/api/profile/me';
  const res = await authedFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw mutationError(path, res.status, 'Profile update');
  }
  return res.json();
}

// ─── Platform health, operators and the audit ledger (admin console) ─────────

export interface HealthCheck {
  status: 'up' | 'down';
  latency_ms?: number;
  critical: boolean;
  error?: string;
}

export interface HealthReport {
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: Record<string, HealthCheck>;
}

/**
 * GET /healthz. Read even when it answers 503: an unhealthy report is exactly
 * what the admin console must be able to show, so only an unreachable backend
 * throws.
 */
export async function fetchHealth(): Promise<HealthReport> {
  const path = '/healthz';
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: 'no-store' });
  } catch {
    throw new ApiError(path, null, `Cannot reach the INDRA backend at ${API_BASE}`);
  }
  try {
    return (await res.json()) as HealthReport;
  } catch {
    throw new ApiError(path, res.status, 'Backend returned a malformed health report');
  }
}

export interface OperatorAccount {
  username: string;
  full_name: string;
  role: string;
  agency: string;
  operator_id: string;
  duty_status: string;
}

export async function fetchOperators(): Promise<OperatorAccount[]> {
  const path = '/api/profile/operators';
  return asArray<OperatorAccount>(await getJson<unknown>(path), path);
}

export interface AuditRow {
  seq: number;
  action_taken: string;
  operator_id: string;
  event_id: string | null;
  reason: string | null;
  logged_at: string | null;
  sha256_hash: string;
}

export interface AuditLedger {
  chain: { valid: boolean; checked: number; broken_at_seq: number | null };
  total: number;
  rows: AuditRow[];
}

/** GET /api/audit/recent — needs an Analyst, Commander or Admin session. */
export async function fetchAuditLedger(limit: number = 20): Promise<AuditLedger> {
  const path = `/api/audit/recent?limit=${limit}`;
  if (!getSession()) {
    throw new ApiError(path, 401, 'Sign in as an Analyst, Commander or Admin to read the audit ledger');
  }
  const res = await authedFetch(path, { cache: 'no-store' });
  if (res.status === 401) {
    throw new ApiError(path, 401, 'Your session has ended. Sign in again to read the audit ledger.');
  }
  if (res.status === 403) {
    throw new ApiError(path, 403, 'Reading the audit ledger needs an Analyst, Commander or Admin account');
  }
  if (!res.ok) {
    throw mutationError(path, res.status, 'Reading the audit ledger');
  }
  return (await res.json()) as AuditLedger;
}

// ─── Alert Engine (Additive UI Component Data) ────────────────────────────────

export interface EngineAlert {
  id: string;
  fingerprint: string;
  event_id: string;
  event_code: string;
  rule_id: string;
  rule_name?: string;
  severity: string;
  status: string;
  confidence: number;
  message: string;
  affected_area?: string;
  created_at: string;
  updated_at: string;
  expires_at?: string;
  acknowledged_by?: string;
  acknowledged_at?: string;
  notification_status?: string;
  mode?: string;
}

/**
 * Fetch active alerts from the independent Alert Engine service.
 * Returns [] if the engine is offline, rather than failing the whole page.
 */
export async function fetchEngineAlerts(): Promise<EngineAlert[]> {
  try {
    const res = await fetch(`${ALERT_ENGINE_BASE}/api/alerts`, { cache: 'no-store' });
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    // Return empty array when Alert Engine is offline so the main UI doesn't break
    return [];
  }
}

/**
 * Acknowledge an active Alert Engine alert.
 */
export async function acknowledgeEngineAlert(alertId: string): Promise<{ success: boolean; error?: string }> {
  const session = getSession();
  if (!session) return { success: false, error: 'Sign in to acknowledge an alert' };
  const operatorUsername = session.username;
  try {
    const res = await fetch(`${ALERT_ENGINE_BASE}/api/alerts/${alertId}/acknowledge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ acknowledged_by: operatorUsername }) // We still send it, but engine should verify via token
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      return { success: false, error: err.detail || `HTTP ${res.status}` };
    }
    return { success: true };
  } catch (err: any) {
    return { success: false, error: err?.message || 'Network error' };
  }
}

/**
 * Resolve an active Alert Engine alert.
 */
export async function resolveEngineAlert(alertId: string, reason: string = "Resolved by operator"): Promise<{ success: boolean; error?: string }> {
  const session = getSession();
  if (!session) return { success: false, error: 'Sign in to resolve an alert' };
  const operatorUsername = session.username;
  try {
    const res = await fetch(`${ALERT_ENGINE_BASE}/api/alerts/${alertId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ resolved_by: operatorUsername, reason: reason })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      return { success: false, error: err.detail || `HTTP ${res.status}` };
    }
    return { success: true };
  } catch (err: any) {
    return { success: false, error: err?.message || 'Network error' };
  }
}

// ---------------------------------------------------------------------------
// Analytics – new endpoints added 29 Sep
// ---------------------------------------------------------------------------

/** One bucket in the water inundation depth distribution chart. */
export interface InundationDepthBucket {
  bucket: string;   // e.g. '< 15 cm', '30 – 60 cm'
  count: number;
}

/**
 * GET /api/dashboard/inundation-depth
 * Bucketed distribution of depth_cm values extracted from raw_reports.
 * Returns [] when no reports have a depth reading yet.
 */
export async function fetchInundationDepth(): Promise<InundationDepthBucket[]> {
  return getJson<InundationDepthBucket[]>('/api/dashboard/inundation-depth');
}

// ----

/** One row in the Top Impacted Districts table. */
export interface TopDistrictRow {
  district: string;
  state: string | null;
  total: number;
  critical: number;
  high: number;
  moderate: number;
  low: number;
}

/**
 * GET /api/dashboard/top-districts
 * Top 10 districts by verified event count with severity breakdown.
 * Returns [] when no verified events with a district name exist yet.
 */
export async function fetchTopDistricts(): Promise<TopDistrictRow[]> {
  return getJson<TopDistrictRow[]>('/api/dashboard/top-districts');
}

// ----

/** One bucket in the AI confidence / verification breakdown chart. */
export interface VerificationBucket {
  bucket: string;           // e.g. '0.6 – 0.8'
  count: number;
  auto_published: number;
  human_approved: number;
}

/**
 * GET /api/dashboard/verification-breakdown
 * Distribution of AI confidence scores across all non-rejected events,
 * split by how they were finally approved (auto vs human).
 * Returns [] when no events exist yet.
 */
export async function fetchVerificationBreakdown(): Promise<VerificationBucket[]> {
  return getJson<VerificationBucket[]>('/api/dashboard/verification-breakdown');
}

// ─── Admin Omni & AI Observatory API ──────────────────────────────────────────

export interface MlComponentMetadata {
  component: string;
  version: string;
  backend_integration_status: string;
  artifact: string;
  artifact_sha256?: string;
  protected_receipt?: string;
  protected_receipt_sha256?: string;
  production_validation?: string;
}

export interface MlObservatoryData {
  status: string;
  release_state: string;
  generated_on: string;
  components: MlComponentMetadata[];
  tests: Record<string, any>;
  policy: Record<string, any>;
  live_telemetry: {
    total_reports: number;
    fused_reports: number;
    unfused_reports: number;
    duplicate_reports: number;
    verified_events: number;
    flagged_reports: number;
  };
  consensus_weights: Array<{
    factor: string;
    weight: number;
    metric: string;
    status: string;
  }>;
  nlp_model_info: {
    name: string;
    taxonomy: string[];
    features: string;
    cost_sensitive_safety_margin: string;
    supported_dialects: string;
  };
}

export interface NlpTestResult {
  status: string;
  top_class: string;
  confidence: number;
  probabilities: Record<string, number>;
  features_matched: number;
  model_version: string;
  latency_ms: number;
  warnings?: string[];
}

export interface ReclusterResult {
  success: boolean;
  clusters_count: number;
  reports_clustered: number;
  clusters: Array<{ cluster_id: number; size: number; report_ids: string[] }>;
}

export interface SignedMediaResponse {
  urls: Record<string, string>;
  external: Record<string, boolean>;
  size: string;
  expires_in: number;
  unavailable: Record<string, string>;
}

/**
 * GET /api/admin/ml-observatory
 * Fetch AI / ML model registry, release status, verification weights, and telemetry.
 */
export async function fetchMlObservatory(): Promise<MlObservatoryData> {
  const res = await authedFetch('/api/admin/ml-observatory', { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to load ML observatory: HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * POST /api/admin/ml-test-nlp
 * Dry-run text classification through the IndicBERT / NLP classifier.
 */
export async function testNlpClassification(text: string): Promise<NlpTestResult> {
  const res = await authedFetch('/api/admin/ml-test-nlp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * POST /api/admin/recluster
 * Trigger on-demand spatial DBSCAN reclustering.
 */
export async function triggerRecluster(): Promise<ReclusterResult> {
  const res = await authedFetch('/api/admin/recluster', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * POST /api/media/signed-urls
 * Request signed URLs for inspection. If original=true, audits access in ledger.
 */
export async function requestSignedMediaUrls(
  ids: string[],
  size: 'thumb' | 'full' = 'full',
  original: boolean = false
): Promise<SignedMediaResponse> {
  const res = await authedFetch('/api/media/signed-urls', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, size, original }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * GET /api/reports/export
 * Downloads the current selection as CSV or GeoJSON with bearer auth token.
 */
export async function downloadReportExport(
  format: 'csv' | 'geojson',
  params?: Record<string, string | number | undefined>
): Promise<void> {
  const q = new URLSearchParams({ format });
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') q.append(k, String(v));
    });
  }
  const path = `/api/reports/export?${q.toString()}`;
  const res = await authedFetch(path);
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Export requires an authenticated account. Please log in.');
    }
    if (res.status === 403) {
      throw new Error('Export requires Analyst or Admin privileges.');
    }
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `Export failed (HTTP ${res.status})`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `indra_reports_${new Date().toISOString().slice(0, 10)}.${format === 'csv' ? 'csv' : 'geojson'}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}
