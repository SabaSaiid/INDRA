'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { cn, formatNumber } from '@/lib/utils';
import { KpiItem } from '@/lib/mock-data';
import {
  FileBarChart2,
  ShieldCheck,
  AlertTriangle,
  Users,
  ArrowUpRight,
} from 'lucide-react';

const iconMap = {
  reports: FileBarChart2,
  verified: ShieldCheck,
  critical: AlertTriangle,
  citizens: Users,
};

// ─── Animated counter hook ───────────────────────────────────────────────────

function useCountUp(target: number, duration: number = 800) {
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

// ─── KPI Card Component ─────────────────────────────────────────────────────

interface KpiCardProps {
  item: KpiItem;
  index: number;
}

export default function KpiCard({ item, index }: KpiCardProps) {
  const Icon = iconMap[item.icon];
  const animatedValue = useCountUp(item.value, 800 + index * 100);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: index * 0.07 }}
      whileHover={{
        y: -4,
        boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.08), 0 4px 6px -4px rgb(0 0 0 / 0.04)',
        transition: { duration: 0.25, ease: 'easeOut' },
      }}
      className="bg-white rounded-2xl border border-slate-100 shadow-card p-5 cursor-default"
    >
      <div className="flex items-start gap-3">
        {/* Icon chip */}
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: item.bgColor }}
        >
          <span style={{ color: item.color }}>
            <Icon className="w-5 h-5" />
          </span>
        </div>

        {/* Value + label */}
        <div className="flex-1 min-w-0">
          <p className="text-2xl font-bold text-text-primary tabular-nums leading-none">
            {formatNumber(animatedValue)}
          </p>
          <p className="text-xs text-text-secondary mt-1.5">{item.label}</p>
        </div>

        {/* Delta badge */}
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.4 + index * 0.07, duration: 0.3 }}
          className={cn(
            'flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-medium',
            item.delta > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
          )}
        >
          <ArrowUpRight className="w-3 h-3" />
          <span>{item.delta}%</span>
        </motion.div>
      </div>
      <p className="text-[10px] text-text-muted mt-1 text-right">({item.deltaLabel})</p>
    </motion.div>
  );
}
