'use client';

import React, { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { MapCardSkeleton } from '@/components/ui/skeleton';
import { mapMarkers, severityConfig, type MapMarker } from '@/lib/mock-data';
import {
  CloudRain,
  Waves,
  Zap,
  Wind,
  CloudFog,
  AlertTriangle,
} from 'lucide-react';

// Dynamically import Leaflet (no SSR)
const MapContainer = dynamic(
  () => import('react-leaflet').then((mod) => mod.MapContainer),
  { ssr: false }
);
const TileLayer = dynamic(
  () => import('react-leaflet').then((mod) => mod.TileLayer),
  { ssr: false }
);
const MarkerComponent = dynamic(
  () => import('react-leaflet').then((mod) => mod.Marker),
  { ssr: false }
);
const Popup = dynamic(
  () => import('react-leaflet').then((mod) => mod.Popup),
  { ssr: false }
);

// Severity-based marker colors
const severityMarkerColors: Record<string, string> = {
  critical: '#EF4444',
  high: '#F59E0B',
  moderate: '#3B82F6',
  low: '#64748B',
};

// Event type icons for the legend
const eventTypeIcons: { type: string; color: string; Icon: React.ComponentType<{ className?: string }> }[] = [
  { type: 'Severe Rainfall', color: '#EF4444', Icon: CloudRain },
  { type: 'Flood', color: '#F59E0B', Icon: Waves },
  { type: 'Thunderstorm', color: '#8B5CF6', Icon: Zap },
  { type: 'Strong Winds', color: '#2563EB', Icon: Wind },
  { type: 'Fog', color: '#64748B', Icon: CloudFog },
];

function createMarkerIcon(severity: string) {
  if (typeof window === 'undefined') return undefined;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const L = require('leaflet');

  const color = severityMarkerColors[severity] || '#64748B';
  const isPulsing = severity === 'critical' || severity === 'high';

  const pulseRing = isPulsing
    ? `<span class="pulse-ring pulse-ring-${severity}" style="width:32px;height:32px;top:-4px;left:-4px;"></span>`
    : '';

  return L.divIcon({
    className: 'custom-marker',
    html: `
      <div style="position:relative;width:24px;height:24px;">
        ${pulseRing}
        <div style="
          width:24px;height:24px;border-radius:50%;
          background:${color};
          border:3px solid white;
          box-shadow:0 2px 8px rgba(0,0,0,0.3);
          position:relative;z-index:2;
        "></div>
      </div>
    `,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

export default function EventMap() {
  const [mounted, setMounted] = useState(false);
  const [timeRange, setTimeRange] = useState('24h');

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <MapCardSkeleton />;
  }

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.35 }}
    >
      <Card hover={false} className="overflow-hidden">
        <CardHeader
          title="Live Weather Events — India"
          subtitle="Real-time view of verified and unverified weather events"
          action={
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value)}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
              aria-label="Time range"
            >
              <option value="24h">Last 24 hours</option>
              <option value="48h">Last 48 hours</option>
              <option value="7d">Last 7 days</option>
            </select>
          }
        />

        <div className="relative rounded-xl overflow-hidden" style={{ height: '380px' }}>
          <link
            rel="stylesheet"
            href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          />
          <MapContainer
            center={[22.5, 82.0]}
            zoom={5}
            style={{ height: '100%', width: '100%' }}
            zoomControl={true}
            scrollWheelZoom={true}
            attributionControl={false}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {mapMarkers.map((marker) => (
              <MarkerComponent
                key={marker.id}
                position={[marker.lat, marker.lng]}
                icon={createMarkerIcon(marker.severity)}
              >
                <Popup>
                  <div className="min-w-[180px]">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span style={{ color: severityConfig[marker.severity].color }}>
                        <AlertTriangle className="w-3.5 h-3.5" />
                      </span>
                      <span
                        className="text-xs font-semibold px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: severityConfig[marker.severity].bg,
                          color: severityConfig[marker.severity].textColor,
                        }}
                      >
                        {severityConfig[marker.severity].label}
                      </span>
                    </div>
                    <p className="font-semibold text-sm">
                      {marker.city}, {marker.state}
                    </p>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {marker.eventType}
                    </p>
                    <p className="text-xs text-slate-600 mt-1">
                      {marker.description}
                    </p>
                  </div>
                </Popup>
              </MarkerComponent>
            ))}
          </MapContainer>

          {/* Floating Legend */}
          <div className="absolute bottom-4 right-4 z-[1000] bg-white/95 backdrop-blur-sm rounded-xl shadow-lg p-3 border border-slate-100">
            <div className="space-y-1.5">
              {eventTypeIcons.map(({ type, color, Icon }) => (
                <div key={type} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <Icon className="w-3 h-3 text-slate-500" />
                  <span className="text-[10px] text-slate-600">{type}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
