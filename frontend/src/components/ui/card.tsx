'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import { cardHover } from '@/lib/motion';

/** density="compact" → p-3.5 / mb-2; "normal" → p-5 / mb-4 (default) */
type CardDensity = 'compact' | 'normal';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  padding?: boolean;
  density?: CardDensity;
}

export function Card({ children, className, hover = true, padding = true, density = 'normal' }: CardProps) {
  const paddingClass = padding ? (density === 'compact' ? 'p-3.5' : 'p-5') : '';
  const baseClass = cn(
    'bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card',
    paddingClass,
    className
  );

  if (hover) {
    return (
      <motion.div
        initial="rest"
        whileHover="hover"
        variants={cardHover}
        className={baseClass}
      >
        {children}
      </motion.div>
    );
  }

  return (
    <div className={baseClass}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  density?: CardDensity;
}

export function CardHeader({ title, subtitle, action, className, density = 'normal' }: CardHeaderProps) {
  const marginClass = density === 'compact' ? 'mb-2' : 'mb-4';
  return (
    <div className={cn('flex items-center justify-between', marginClass, className)}>
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {subtitle && (
          <p className="text-xs text-ink-3 mt-0.5">{subtitle}</p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}

