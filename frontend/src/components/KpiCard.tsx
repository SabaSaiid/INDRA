'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { formatNumber } from '@/lib/utils';
import { KpiItem } from '@/lib/ui-config';

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
  // A zero delta is neither a rise nor a fall. Folding it into the "else"
  // branch painted "Verified Events 0" and "Active Alerts 45" with a red
  // downward arrow, which reads as a decline that never happened — and two of
  // these readings carry a hardcoded delta of 0 because they have no
  // comparison window at all.
  const hasWindow = item.delta !== null;
  const delta = item.delta ?? 0;
  const isPositive = delta > 0;
  const isFlat = delta === 0;

  return (
    <motion.div
      className="instrument-reading"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.3, ease: 'easeOut' }}
    >
      {/* Left: value + label stacked */}
      <div className="instrument-reading-values">
        <p
          className="text-xl font-semibold text-ink tabular-nums leading-none"
          style={{ fontFamily: 'JetBrains Mono, monospace' }}
        >
          {formatNumber(animatedValue)}
        </p>
        <p className="text-[10px] text-[#7A8599] leading-normal truncate py-0.5">
          {item.label}
        </p>
      </div>

      {/* Right: delta badge */}
      <div className="instrument-reading-delta">
        {/* A figure with no comparison window shows its label alone, never "0%". */}
        {hasWindow && (
          <p
            className="text-[9px] tabular-nums leading-normal"
            style={{ fontFamily: 'JetBrains Mono, monospace' }}
          >
            <span
              className={
                isFlat
                  ? 'text-[#7A8599]'
                  : isPositive
                    ? 'text-[#4C7A5B]'
                    : 'text-[#8C2F26]'
              }
            >
              {isFlat ? '' : isPositive ? '↑' : '↓'}
              {Math.abs(delta)}%
            </span>
          </p>
        )}
        {/* Truncates before the reading's own label does: the label is the
            thing an operator reads. */}
        <p className="text-[8px] text-[#B0A898] leading-normal mt-0.5 whitespace-nowrap truncate max-w-[95px]" title={item.deltaLabel}>
          {item.deltaLabel}
        </p>
      </div>
    </motion.div>
  );
}

// ─── KpiCard — one instrument reading cell ────────────────────────────────────

interface KpiCardProps {
  item: KpiItem;
  index: number;
}

/**
 * KpiCard renders as a compact single-row instrument reading within the
 * `.instrument-strip` CSS grid defined in globals.css.
 */
export default function KpiCard({ item, index }: KpiCardProps) {
  return <Reading item={item} index={index} />;
}
