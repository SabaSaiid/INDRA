'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { type MapMarker } from '@/lib/mock-data';

// Dynamically import 3D Globe Event Map without SSR
const GlobeEventMap = dynamic(() => import('@/components/client-only/GlobeEventMap'), {
  ssr: false,
  loading: () => <MapCardSkeleton />,
});

export default function EventMap({
  selectedEventId,
  onEventSelect,
  variant = 'preview',
}: {
  selectedEventId?: string;
  onEventSelect?: (marker: MapMarker | null) => void;
  variant?: 'full' | 'preview';
}) {
  return (
    <GlobeEventMap
      selectedEventId={selectedEventId}
      onEventSelect={onEventSelect}
      variant={variant}
    />
  );
}
