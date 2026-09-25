'use client';

/**
 * Operator sign-in.
 *
 * An operator signs in with the username and password of their account in the
 * backend (POST /api/auth/token). The tab keeps the token the backend issued
 * and what the backend said about the account, in sessionStorage under
 * `indra_session`. The password is never kept, and closing the tab ends the
 * session.
 *
 * Reading the dashboards needs no session. Reviewing events, dispatching teams,
 * filing official reports, editing a profile and reading provenance or the
 * audit ledger do, and the backend checks the role on every one of them.
 */

import { useEffect, useState } from 'react';
import { API_BASE } from './api-base';

export interface Session {
  username: string;
  /** As the backend issued it, upper-cased: 'COMMANDER', 'ANALYST', 'ADMIN', 'CITIZEN'. */
  role: string;
  agency: string;
  operatorId: string;
  accessToken: string;
  /** Epoch milliseconds after which the backend refuses the token. */
  expiresAt: number;
}

const SESSION_KEY = 'indra_session';

/** Fired on window whenever this tab signs in or out. */
export const AUTH_CHANGE_EVENT = 'indra-auth-change';

/** Roles the backend lets review events, dispatch teams and file official reports. */
export const COMMAND_ROLES = ['COMMANDER', 'ADMIN'] as const;
/** Roles the backend lets read provenance and the audit ledger. */
export const LEDGER_ROLES = ['ANALYST', 'COMMANDER', 'ADMIN'] as const;

export function hasRole(session: Session | null, roles: readonly string[]): boolean {
  return !!session && roles.includes(session.role);
}

/** 'COMMANDER' → 'Commander', 'FIELD_RESPONDER' → 'Field responder'. */
export function roleLabel(role: string | null | undefined): string {
  if (!role) return '—';
  const words = role.toLowerCase().replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The session's expiry as a wall-clock time in IST, e.g. '18:42 IST'. */
export function sessionExpiryLabel(session: Session): string {
  const time = new Date(session.expiresAt).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  return `${time} IST`;
}

// Used only when sessionStorage throws (blocked site data): the session then
// lasts until the page is left, rather than not at all.
let memorySession: Session | null = null;

function isSession(value: unknown): value is Session {
  const s = value as Session | null;
  return (
    !!s &&
    typeof s.username === 'string' &&
    typeof s.role === 'string' &&
    typeof s.agency === 'string' &&
    typeof s.operatorId === 'string' &&
    typeof s.accessToken === 'string' &&
    s.accessToken.length > 0 &&
    typeof s.expiresAt === 'number'
  );
}

function readStored(): Session | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(SESSION_KEY);
  } catch {
    return memorySession;
  }
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function store(session: Session | null) {
  memorySession = session;
  try {
    if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Storage unavailable; memorySession holds it for this page.
  }
}

function announce() {
  try {
    window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  } catch {
    // No window while the page is prerendered.
  }
}

/** This tab's session, or null when signed out or once the token has expired. */
export function getSession(): Session | null {
  if (typeof window === 'undefined') return null;
  const session = readStored();
  if (session && session.expiresAt <= Date.now()) {
    store(null);
    return null;
  }
  return session;
}

/** The JWT's claims, unverified. Only the backend can check the signature. */
function jwtClaims(token: string): Record<string, unknown> {
  const payload = token.split('.')[1];
  if (!payload) return {};
  try {
    const b64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const parsed: unknown = JSON.parse(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)));
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/**
 * Sign in against the backend. Resolves with the session, or throws an Error
 * whose message the sign-in form shows as it is.
 */
export async function signIn(username: string, password: string): Promise<Session> {
  const body = new URLSearchParams();
  body.set('username', username);
  body.set('password', password);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
  } catch {
    throw new Error(`Cannot reach the INDRA backend at ${API_BASE}`);
  }
  if (res.status === 401) throw new Error('Incorrect username or password');
  if (res.status === 503) throw new Error('The backend database is unavailable. Try again shortly.');
  if (!res.ok) throw new Error(`Sign-in failed (HTTP ${res.status})`);

  let data: Record<string, unknown>;
  try {
    data = (await res.json()) as Record<string, unknown>;
  } catch {
    throw new Error('The backend returned a malformed sign-in response');
  }
  const token = text(data.access_token);
  if (!token) throw new Error('The backend returned no token');

  const claims = jwtClaims(token);
  const expiresAt =
    typeof data.expires_in === 'number' && data.expires_in > 0
      ? Date.now() + data.expires_in * 1000
      : typeof claims.exp === 'number'
      ? claims.exp * 1000
      : NaN;
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    throw new Error('The backend issued a token with no usable expiry');
  }

  const session: Session = {
    username: text(data.username) ?? text(claims.sub) ?? username,
    role: (text(data.role) ?? text(claims.role) ?? '').toUpperCase(),
    agency: text(data.agency) ?? text(claims.agency) ?? '',
    operatorId: text(data.operator_id) ?? text(claims.operator_id) ?? '',
    accessToken: token,
    expiresAt,
  };
  store(session);
  announce();
  return session;
}

export function signOut() {
  store(null);
  announce();
}

/** `Authorization: Bearer …` for the current session, or nothing when signed out. */
export function authHeaders(): Record<string, string> {
  const session = getSession();
  return session ? { Authorization: `Bearer ${session.accessToken}` } : {};
}

/**
 * The current session, kept in step with sign-in and sign-out in this tab.
 * Null on the first render, so the server and the client render the same page.
 */
export function useSession(): Session | null {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const sync = () =>
      setSession((prev) => {
        const next = getSession();
        return prev && next && prev.accessToken === next.accessToken ? prev : next;
      });
    sync();
    window.addEventListener(AUTH_CHANGE_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(AUTH_CHANGE_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  // Sign out when the token lapses, so the page stops offering actions the
  // backend would refuse.
  useEffect(() => {
    if (!session) return;
    const remaining = Math.min(Math.max(session.expiresAt - Date.now(), 0), 2_147_483_647);
    const timer = setTimeout(signOut, remaining);
    return () => clearTimeout(timer);
  }, [session]);

  return session;
}
