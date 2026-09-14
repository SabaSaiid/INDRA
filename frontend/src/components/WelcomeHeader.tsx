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
        second: undefined,
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
      setCurrentTime(timeStr + ' IST');
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
      className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6"
    >
      {/* Left */}
      <div>
        <h2 className="text-2xl font-bold text-text-primary">
          Welcome to INDRA
        </h2>
        <p className="text-sm text-text-secondary mt-0.5">
          Real-time insights. Verified information. A safer India.
        </p>
      </div>

      {/* Right */}
      <div className="flex items-center gap-4">
        {/* System Online pill */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200">
          <span className="status-dot" />
          <span className="text-xs font-medium text-emerald-700">System Online</span>
        </div>

        {/* Clock */}
        <div className="text-right hidden sm:block">
          <p className="text-sm font-medium text-text-primary tabular-nums">
            {currentDate}
          </p>
          <p className="text-xs text-text-muted tabular-nums">
            {currentTime}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
