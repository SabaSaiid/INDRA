'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';

export default function WelcomeHeader() {
  const [currentTime, setCurrentTime] = useState<string>('');
  const [currentDate, setCurrentDate] = useState<string>('');

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      const timeStr = now.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'Asia/Kolkata',
        hour12: false,
      });
      const dateStr = now.toLocaleDateString('en-IN', {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        timeZone: 'Asia/Kolkata',
      });
      setCurrentTime(timeStr);
      setCurrentDate(dateStr);
    };

    updateClock();
    const interval = setInterval(updateClock, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6 pb-4 border-b border-[#E8E2D4]"
    >
      {/* Left — Situation heading */}
      <div>
        <p className="text-[11px] font-medium text-[#7A8599] uppercase tracking-[0.1em] mb-1">
          National Weather Intelligence
        </p>
        <h2
          className="text-3xl font-semibold text-ink leading-tight"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Situation Overview
        </h2>
      </div>

      {/* Right — Quiet status strip */}
      <div className="flex items-center gap-5">
        {/* Live indicator */}
        <div className="flex items-center gap-1.5">
          <span className="status-dot" />
          <span className="text-xs font-medium text-[#4C7A5B]">Grid live</span>
        </div>

        {/* Date + IST clock */}
        <div className="text-right hidden sm:block">
          <p className="text-xs text-[#7A8599]">{currentDate}</p>
          <p
            className="text-sm font-medium text-ink tabular-nums"
            style={{ fontFamily: 'JetBrains Mono, monospace' }}
            suppressHydrationWarning
          >
            {currentTime} <span className="text-[10px] text-[#7A8599]">IST</span>
          </p>
        </div>
      </div>
    </motion.div>
  );
}
