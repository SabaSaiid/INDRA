'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { MapCardSkeleton } from '@/components/ui/skeleton';

// Dynamically import 3D Globe Event Map without SSR
const GlobeEventMap = dynamic(() => import('@/components/GlobeEventMap'), {
  ssr: false,
  loading: () => <MapCardSkeleton />,
});

export default function EventMap() {
  return <GlobeEventMap />;
}
