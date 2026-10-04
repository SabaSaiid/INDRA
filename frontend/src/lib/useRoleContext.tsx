'use client';

/**
 * INDRA Platform — Role Perspective Context
 *
 * Allows an Admin to simulate what any other role sees on the platform
 * without signing out or minting a different JWT. Every component that
 * gates UI on a role reads `effectiveRole` from this context instead of
 * the raw session role.
 *
 * Non-Admin users: `effectiveRole` is always their real role; the
 * `setPerspective` callback is a no-op.
 *
 * Audit integrity: the backend still receives the genuine Admin JWT, so
 * every mutation is attributed to the real operator in the SHA-256 ledger.
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';
import { useSession } from './auth';

// ─── Types ─────────────────────────────────────────────────────────────────────

export type EffectiveRole =
  | 'ADMIN'
  | 'COMMANDER'
  | 'ANALYST'
  | 'CITIZEN'
  | 'FIELD_RESPONDER';

/** Role metadata shown in the perspective switcher UI. */
export interface RolePerspective {
  role: EffectiveRole;
  label: string;
  description: string;
  color: string;
}

export const ROLE_PERSPECTIVES: RolePerspective[] = [
  {
    role: 'ADMIN',
    label: 'Admin Omni-View',
    description: 'Full system access: all reports, AI observatory, audit ledger',
    color: '#7C3AED',
  },
  {
    role: 'COMMANDER',
    label: 'SEOC Commander',
    description: 'Event review, team dispatch, official reports',
    color: '#B5482E',
  },
  {
    role: 'ANALYST',
    label: 'Intelligence Analyst',
    description: 'Sensor telemetry, provenance, data exports',
    color: '#2563EB',
  },
  {
    role: 'CITIZEN',
    label: 'Citizen / Public',
    description: 'Public alerts, citizen reports, fuzzed GPS, blurred media',
    color: '#059669',
  },
  {
    role: 'FIELD_RESPONDER',
    label: 'Field Responder',
    description: 'Tactical rescue view, START triage, mesh beacon',
    color: '#D97706',
  },
];

// ─── Permission Matrix ─────────────────────────────────────────────────────────

/**
 * Which roles the backend allows for each protected action, transcribed from
 * the backend's enforced auth matrix (require_roles calls in the API layer).
 */
const PERMISSION_MATRIX: Record<string, readonly EffectiveRole[]> = {
  'review.events':       ['COMMANDER', 'ADMIN'],
  'override.severity':   ['COMMANDER', 'ADMIN'],
  'dispatch.teams':      ['COMMANDER', 'ADMIN'],
  'file.official':       ['COMMANDER', 'ADMIN'],
  'claim.events':        ['COMMANDER', 'ADMIN'],
  'read.provenance':     ['ANALYST', 'COMMANDER', 'ADMIN'],
  'read.audit':          ['ANALYST', 'COMMANDER', 'ADMIN'],
  'export.data':         ['ANALYST', 'COMMANDER', 'ADMIN'],
  'read.media.originals':['ANALYST', 'COMMANDER', 'ADMIN'],
  'review.queue':        ['ANALYST', 'COMMANDER', 'ADMIN'],
  'recluster.reports':   ['ANALYST', 'COMMANDER', 'ADMIN'],
  'source.credibility':  ['ANALYST', 'COMMANDER', 'ADMIN'],
  'edit.profile':        ['ADMIN', 'COMMANDER', 'ANALYST', 'CITIZEN', 'FIELD_RESPONDER'],
  'submit.citizen':      ['ADMIN', 'COMMANDER', 'ANALYST', 'CITIZEN', 'FIELD_RESPONDER'],
};

// ─── Context ────────────────────────────────────────────────────────────────────

interface RoleContextValue {
  /** The role from the signed JWT — never changes during a session. */
  actualRole: EffectiveRole | null;
  /** The currently active viewport role. Equals actualRole unless an Admin is impersonating. */
  effectiveRole: EffectiveRole | null;
  /** True when an Admin is simulating a different role. */
  isImpersonating: boolean;
  /** Switch the active perspective. Only works when actualRole is ADMIN. */
  setPerspective: (role: EffectiveRole) => void;
  /** Return to the Admin's own full-access viewport. */
  resetPerspective: () => void;
  /** Check whether the effective role is allowed a given action key. */
  can: (action: string) => boolean;
}

const RoleContext = createContext<RoleContextValue>({
  actualRole: null,
  effectiveRole: null,
  isImpersonating: false,
  setPerspective: () => {},
  resetPerspective: () => {},
  can: () => false,
});

// ─── Provider ───────────────────────────────────────────────────────────────────

export function RoleProvider({ children }: { children: ReactNode }) {
  const session = useSession();
  const actualRole = (session?.role?.toUpperCase() as EffectiveRole) ?? null;

  // The perspective the Admin has chosen. null means "use my own role".
  const [overrideRole, setOverrideRole] = useState<EffectiveRole | null>(null);

  const isAdmin = actualRole === 'ADMIN';

  // When the session changes (sign-out, sign-in as a different user), reset.
  const effectiveRole = useMemo<EffectiveRole | null>(() => {
    if (!actualRole) return null;
    if (isAdmin && overrideRole) return overrideRole;
    return actualRole;
  }, [actualRole, isAdmin, overrideRole]);

  const isImpersonating = isAdmin && !!overrideRole && overrideRole !== 'ADMIN';

  const setPerspective = useCallback(
    (role: EffectiveRole) => {
      if (!isAdmin) return;
      // Selecting the Admin's own role clears the override.
      setOverrideRole(role === 'ADMIN' ? null : role);
    },
    [isAdmin],
  );

  const resetPerspective = useCallback(() => {
    setOverrideRole(null);
  }, []);

  const can = useCallback(
    (action: string): boolean => {
      if (!effectiveRole) return false;
      const allowed = PERMISSION_MATRIX[action];
      if (!allowed) return false;
      return allowed.includes(effectiveRole);
    },
    [effectiveRole],
  );

  const value = useMemo<RoleContextValue>(
    () => ({
      actualRole,
      effectiveRole,
      isImpersonating,
      setPerspective,
      resetPerspective,
      can,
    }),
    [actualRole, effectiveRole, isImpersonating, setPerspective, resetPerspective, can],
  );

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

// ─── Hook ───────────────────────────────────────────────────────────────────────

export function useRoleContext() {
  return useContext(RoleContext);
}
