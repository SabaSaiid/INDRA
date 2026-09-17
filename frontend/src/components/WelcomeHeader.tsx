'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Map, BarChart2, LayoutDashboard } from 'lucide-react';

export type ViewMode = 'mission-control' | 'map-focus' | 'analytics-focus';

interface WelcomeHeaderProps {
  viewMode?: ViewMode;
  onViewModeChange?: (mode: ViewMode) => void;
}

const VIEW_MODES: { id: ViewMode; label: string; icon: React.ReactNode; title: string }[] = [
  {
    id: 'mission-control',
    label: 'Mission Control',
    icon: <LayoutDashboard className="w-3 h-3" />,
    title: 'All panels visible — high-density operational view',
  },
  {
    id: 'map-focus',
    label: 'Map Focus',
    icon: <Map className="w-3 h-3" />,
    title: 'Expanded 3D Globe / Tactical Map for geospatial tracking',
  },
  {
    id: 'analytics-focus',
    label: 'Analytics',
    icon: <BarChart2 className="w-3 h-3" />,
    title: 'Expanded charts and live feed for intelligence reporting',
  },
];

export default function WelcomeHeader({ viewMode = 'mission-control', onViewModeChange }: WelcomeHeaderProps) {
  const [currentTime, setCurrentTime] = useState<string>('');
  const [currentDate, setCurrentDate] = useState<string>('');

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setCurrentTime(
        now.toLocaleTimeString('en-IN', {
          hour: '2-digit', minute: '2-digit', second: '2-digit',
          timeZone: 'Asia/Kolkata', hour12: false,
        })
      );
      setCurrentDate(
        now.toLocaleDateString('en-IN', {
          weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
          timeZone: 'Asia/Kolkata',
        })
      );
    };
    updateClock();
    const interval = setInterval(updateClock, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleViewMode = useCallback((mode: ViewMode) => {
    onViewModeChange?.(mode);
    try { localStorage.setItem('indra_view_mode', mode); } catch { /* ignore */ }
  }, [onViewModeChange]);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      className="flex items-center justify-between mb-2.5 pb-2 border-b border-[#E8E2D4] min-h-[36px]"
    >
      {/* Left — Title + Live dot */}
      <div className="flex items-center gap-2.5">
        {/* Live indicator */}
        <span className="flex items-center gap-1">
          <span className="status-dot w-1.5 h-1.5" />
        </span>
        <span
          className="text-base font-semibold text-ink leading-none"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Situation Overview
        </span>
        <span className="hidden sm:inline text-[10px] font-medium text-[#4C7A5B] bg-[#E7F2EC] border border-[#C5DECE] px-1.5 py-0.5 rounded-full">
          Grid live
        </span>
      </div>

      {/* Centre — View Mode switcher */}
      <div className="hidden md:flex items-center gap-0.5 bg-[#F0EBE0] rounded-md p-0.5 border border-[#E8E2D4]">
        {VIEW_MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => handleViewMode(m.id)}
            title={m.title}
            className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-all ${
              viewMode === m.id
                ? 'bg-[#FDFAF5] text-ink shadow-sm border border-[#E8E2D4]'
                : 'text-[#7A8599] hover:text-ink hover:bg-[#FDFAF5]/60'
            }`}
          >
            {m.icon}
            <span>{m.label}</span>
          </button>
        ))}
      </div>

      {/* Right — Date + IST clock */}
      <div className="hidden sm:flex items-center gap-3">
        <p className="text-[10px] text-[#7A8599]">{currentDate}</p>
        <p
          className="text-xs font-medium text-ink tabular-nums"
          style={{ fontFamily: 'JetBrains Mono, monospace' }}
          suppressHydrationWarning
        >
          {currentTime} <span className="text-[9px] text-[#7A8599]">IST</span>
        </p>
      </div>
    </motion.div>
  );
}

