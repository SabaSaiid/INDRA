'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { formatNumber } from '@/lib/utils';
import { KpiItem } from '@/lib/mock-data';

// ─── Animated counter hook ────────────────────────────────────────────────────

function useCountUp(target: number, duration: number = 900) {
  const [count, setCount] = useState(0);
  const startRef = useRef<number | null>(null);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    startRef.current = null;

    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

    const animate = (timestamp: number) => {
      if (startRef.current === null) startRef.current = timestamp;
      const elapsed = timestamp - startRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeOutCubic(progress);

      setCount(Math.round(easedProgress * target));

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      }
    };

    frameRef.current = requestAnimationFrame(animate);

    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [target, duration]);

  return count;
}

// ─── Single reading in the strip ─────────────────────────────────────────────

interface ReadingProps {
  item: KpiItem;
  index: number;
}

function Reading({ item, index }: ReadingProps) {
  const animatedValue = useCountUp(item.value, 900 + index * 80);
  const isPositive = item.delta > 0;

  return (
    <motion.div
      className="instrument-reading"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.35, ease: 'easeOut' }}
    >
      {/* Instrument value */}
      <p
        className="text-2xl font-semibold text-ink tabular-nums leading-none"
        style={{ fontFamily: 'JetBrains Mono, monospace' }}
      >
        {formatNumber(animatedValue)}
      </p>

      {/* Label */}
      <p className="text-xs text-[#7A8599] mt-1 leading-tight">
        {item.label}
      </p>

      {/* Delta */}
      <p className="text-[10px] tabular-nums mt-1.5" style={{ fontFamily: 'JetBrains Mono, monospace' }}>
        <span
          className={isPositive ? 'text-[#4C7A5B]' : 'text-[#8C2F26]'}
        >
          {isPositive ? '↑' : '↓'}{Math.abs(item.delta)}%
        </span>
        <span className="text-[#B0A898] ml-1">{item.deltaLabel}</span>
      </p>
    </motion.div>
  );
}

// ─── Instrument Strip ─────────────────────────────────────────────────────────

interface KpiCardProps {
  item: KpiItem;
  index: number;
}

/**
 * KpiCard is kept for API compatibility but renders as part of the
 * InstrumentStrip layout via CSS grid (`.instrument-strip` class on the
 * parent in page.tsx). Each KpiCard IS one instrument reading cell.
 */
export default function KpiCard({ item, index }: KpiCardProps) {
  return <Reading item={item} index={index} />;
}
