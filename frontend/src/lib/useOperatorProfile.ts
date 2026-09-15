'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  type UserProfile,
  type DutyStatus,
  mockUserProfile,
  mockProfilesMap,
} from './mock-data';
import { fetchUserProfile, updateUserProfile } from './api';

const OPERATOR_STORAGE_KEY = 'indra_current_role';

export function useOperatorProfile() {
  const [selectedRole, setSelectedRoleState] = useState<string>(() => {
    if (typeof window === 'undefined') return 'commander';
    try {
      return localStorage.getItem(OPERATOR_STORAGE_KEY) || 'commander';
    } catch {
      return 'commander';
    }
  });

  const [profile, setProfile] = useState<UserProfile>(() => {
    return mockProfilesMap[selectedRole] || mockUserProfile;
  });

  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);

  // Sync profile when role changes
  const switchRole = useCallback(async (role: string) => {
    setSelectedRoleState(role);
    try {
      localStorage.setItem(OPERATOR_STORAGE_KEY, role);
    } catch {
      // ignore
    }

    try {
      const data = await fetchUserProfile(role);
      const newProfile = data || mockProfilesMap[role] || mockUserProfile;
      setProfile(newProfile);
      window.dispatchEvent(
        new CustomEvent('indra-operator-change', {
          detail: { role, profile: newProfile },
        })
      );
    } catch {
      const fallback = mockProfilesMap[role] || mockUserProfile;
      setProfile(fallback);
      window.dispatchEvent(
        new CustomEvent('indra-operator-change', {
          detail: { role, profile: fallback },
        })
      );
    }
  }, []);

  const updateDuty = useCallback(
    async (newStatus: DutyStatus) => {
      if (newStatus === profile.duty_status) return;
      setIsUpdatingStatus(true);
      const updated = { ...profile, duty_status: newStatus };
      setProfile(updated);

      window.dispatchEvent(
        new CustomEvent('indra-operator-change', {
          detail: { role: selectedRole, profile: updated },
        })
      );

      try {
        await updateUserProfile({ duty_status: newStatus }, selectedRole);
      } catch (err) {
        console.warn('Failed to persist duty status', err);
      } finally {
        setIsUpdatingStatus(false);
      }
    },
    [profile, selectedRole]
  );

  // Listen for custom events from other components
  useEffect(() => {
    const handleOperatorChange = (e: Event) => {
      const detail = (e as CustomEvent<{ role: string; profile: UserProfile }>).detail;
      if (detail && detail.profile) {
        setSelectedRoleState(detail.role);
        setProfile(detail.profile);
      }
    };

    window.addEventListener('indra-operator-change', handleOperatorChange);
    return () => {
      window.removeEventListener('indra-operator-change', handleOperatorChange);
    };
  }, []);

  return {
    profile,
    selectedRole,
    switchRole,
    updateDuty,
    isUpdatingStatus,
  };
}
