'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  type UserProfile,
  type DutyStatus,
  mockUserProfile,
  mockProfilesMap,
} from './mock-data';
import { fetchUserProfile, updateUserProfile, getAuthToken, clearAuthToken } from './api';

const OPERATOR_STORAGE_KEY = 'indra_current_role';

export interface OperatorPersonaOption {
  id: string;
  label: string;
  name: string;
  agency: string;
  badge: string;
  role: string;
  avatar: string;
  tagline: string;
}

export const AVAILABLE_OPERATOR_PERSONAS: OperatorPersonaOption[] = [
  {
    id: 'commander',
    label: 'Operations Director',
    name: 'Rajesh K. Verma',
    agency: 'SEOC Bihar / NDMA',
    badge: 'SEOC-PAT-091',
    role: 'COMMANDER',
    avatar: 'RV',
    tagline: 'Emergency operations leadership & disaster response coordination',
  },
  {
    id: 'analyst',
    label: 'Meteorological Analyst',
    name: 'Dr. Vikram Sethi',
    agency: 'IMD Nowcasting Cell',
    badge: 'IMD-MET-552',
    role: 'ANALYST',
    avatar: 'VS',
    tagline: 'Doppler radar calibration & Bayesian prior synthesis',
  },
  {
    id: 'admin',
    label: 'Platform Administrator',
    name: 'Saba Saeed',
    agency: 'NDMA National Grid',
    badge: 'NDMA-DIR-001',
    role: 'ADMIN',
    avatar: 'SS',
    tagline: 'Root governance, node gateways & national architecture',
  },
  {
    id: 'citizen',
    label: 'Citizen Volunteer',
    name: 'Meenal Sinha',
    agency: 'Community Weather Watch',
    badge: 'CIT-REP-06',
    role: 'CITIZEN',
    avatar: 'MS',
    tagline: 'Ground-truth waterlogging reports & public crowdsourcing',
  },
];

export function useOperatorProfile() {
  const [selectedRole, setSelectedRoleState] = useState<string>('commander');
  const [profile, setProfile] = useState<UserProfile>(() => mockProfilesMap['commander'] || mockUserProfile);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [isSavingProfile, setIsSavingProfile] = useState(false);

  // Auto-authenticate for the current persona on mount and role changes
  useEffect(() => {
    let cancelled = false;
    getAuthToken(selectedRole).then((token) => {
      if (!cancelled) setIsAuthenticated(!!token);
    });
    return () => { cancelled = true; };
  }, [selectedRole]);

  // Sync stored role from localStorage after initial client hydration to avoid hydration mismatch
  useEffect(() => {
    try {
      const stored = localStorage.getItem(OPERATOR_STORAGE_KEY);
      if (stored && stored !== 'commander') {
        setSelectedRoleState(stored);
        if (mockProfilesMap[stored]) {
          setProfile(mockProfilesMap[stored]);
        }
      }
    } catch {
      // ignore
    }
  }, []);

  // Fetch profile data on mount or role change
  useEffect(() => {
    let cancelled = false;
    fetchUserProfile(selectedRole)
      .then((data) => {
        if (!cancelled && data) {
          setProfile(data);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedRole]);

  // Sync profile when role changes
  const switchRole = useCallback(async (role: string) => {
    setSelectedRoleState(role);
    setIsAuthenticated(false);
    clearAuthToken(role);
    try {
      localStorage.setItem(OPERATOR_STORAGE_KEY, role);
    } catch {
      // ignore
    }

    // Pre-warm auth token for the new persona
    getAuthToken(role).then((token) => setIsAuthenticated(!!token));

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
      const updated: UserProfile = { ...profile, duty_status: newStatus };
      setProfile(updated);
      if (mockProfilesMap[selectedRole]) {
        mockProfilesMap[selectedRole].duty_status = newStatus;
      }

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

  const updateProfile = useCallback(
    async (formData: Partial<UserProfile>): Promise<UserProfile> => {
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
      if (mockProfilesMap[selectedRole]) {
        Object.assign(mockProfilesMap[selectedRole], updated);
      }

      window.dispatchEvent(
        new CustomEvent('indra-operator-change', {
          detail: { role: selectedRole, profile: updated },
        })
      );

      try {
        const res = await updateUserProfile(formData, selectedRole);
        if (res) {
          const finalProfile = { ...updated, ...res };
          setProfile(finalProfile);
          return finalProfile;
        }
      } catch (err) {
        console.warn('Failed to persist profile to server, cached locally', err);
      } finally {
        setIsSavingProfile(false);
      }

      return updated;
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
    updateProfile,
    isUpdatingStatus,
    isSavingProfile,
    isAuthenticated,
    availablePersonas: AVAILABLE_OPERATOR_PERSONAS,
  };
}
