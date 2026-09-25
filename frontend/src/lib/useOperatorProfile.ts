'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  type UserProfile,
  type DutyStatus,
} from './ui-config';
import {
  fetchUserProfile,
  updateUserProfile,
} from './api';
import { useSession } from './auth';

/** Carries a duty or profile edit to every other chrome component in the tab. */
const OPERATOR_CHANGE_EVENT = 'indra-operator-change';

interface OperatorChange {
  username: string;
  profile: UserProfile;
}

function broadcast(username: string, profile: UserProfile) {
  window.dispatchEvent(
    new CustomEvent<OperatorChange>(OPERATOR_CHANGE_EVENT, { detail: { username, profile } })
  );
}

/**
 * The signed-in operator: the session, their role as the backend issued it, and
 * their profile from GET /api/profile/me. Signed out, there is no role and no
 * profile, and nothing is fetched.
 */
export function useOperatorProfile() {
  const session = useSession();
  const username = session?.username ?? null;
  const token = session?.accessToken ?? null;

  // null until the backend answers. There is no locally invented operator to
  // fall back to: an identity the server does not know about is not an identity.
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileError, setProfileError] = useState<unknown>(null);

  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [isSavingProfile, setIsSavingProfile] = useState(false);

  // Fetch the profile whenever the session changes, and drop it on sign-out.
  useEffect(() => {
    setProfile(null);
    setProfileError(null);
    if (!token) return;
    let cancelled = false;
    fetchUserProfile()
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch((err) => {
        if (!cancelled) setProfileError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const updateDuty = useCallback(
    async (newStatus: DutyStatus) => {
      if (!username || !profile || newStatus === profile.duty_status) return;
      setIsUpdatingStatus(true);
      const updated: UserProfile = { ...profile, duty_status: newStatus };
      setProfile(updated);
      broadcast(username, updated);

      try {
        await updateUserProfile({ duty_status: newStatus });
      } catch (err) {
        // A failed write reverts the optimistic edit rather than leaving it on
        // screen: an operator who sees "STANDBY" must be able to trust it.
        console.warn('Failed to persist duty status', err);
        setProfile(profile);
        broadcast(username, profile);
      } finally {
        setIsUpdatingStatus(false);
      }
    },
    [profile, username]
  );

  const updateProfile = useCallback(
    async (formData: Partial<UserProfile>): Promise<UserProfile> => {
      if (!username || !profile) throw new Error('No operator profile loaded');
      setIsSavingProfile(true);
      const initials = formData.full_name
        ? formData.full_name
            .trim()
            .split(/\s+/)
            .map((p) => p[0])
            .slice(0, 2)
            .join('')
            .toUpperCase()
        : profile.avatar_initials;

      const updated: UserProfile = {
        ...profile,
        ...formData,
        avatar_initials: initials || profile.avatar_initials,
      };

      setProfile(updated);
      broadcast(username, updated);

      try {
        const res = await updateUserProfile(formData);
        const finalProfile = { ...updated, ...res };
        setProfile(finalProfile);
        return finalProfile;
      } catch (err) {
        // This used to log "cached locally" and return the edit as if it had
        // been saved. Put the server's version back and let the caller say why.
        setProfile(profile);
        broadcast(username, profile);
        throw err;
      } finally {
        setIsSavingProfile(false);
      }
    },
    [profile, username]
  );

  // Edits made through another component's copy of this hook.
  useEffect(() => {
    const handleOperatorChange = (e: Event) => {
      const detail = (e as CustomEvent<OperatorChange>).detail;
      if (detail && detail.profile && detail.username === username) {
        setProfile(detail.profile);
      }
    };

    window.addEventListener(OPERATOR_CHANGE_EVENT, handleOperatorChange);
    return () => {
      window.removeEventListener(OPERATOR_CHANGE_EVENT, handleOperatorChange);
    };
  }, [username]);

  return {
    session,
    /** The session's role as the backend issued it, or null when signed out. */
    role: session?.role ?? null,
    // Guarded again here: for the one render between sign-out and the effect
    // above, the old profile must not show.
    profile: session ? profile : null,
    profileError: session ? profileError : null,
    updateDuty,
    updateProfile,
    isUpdatingStatus,
    isSavingProfile,
  };
}
