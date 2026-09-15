'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import { cardHover } from '@/lib/motion';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  padding?: boolean;
}

export function Card({ children, className, hover = true, padding = true }: CardProps) {
  if (hover) {
    return (
      <motion.div
        initial="rest"
        whileHover="hover"
        variants={cardHover}
        className={cn(
          'bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card',
          padding && 'p-5',
          className
        )}
      >
        {children}
      </motion.div>
    );
  }

  return (
    <div
      className={cn(
        'bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card',
        padding && 'p-5',
        className
      )}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, action, className }: CardHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between mb-4', className)}>
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
