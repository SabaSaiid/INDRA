'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import { scaleIn } from '@/lib/motion';

type BadgeVariant = 'critical' | 'high' | 'moderate' | 'low' | 'verified' | 'under-review' | 'default';

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  animated?: boolean;
}

const variantStyles: Record<BadgeVariant, string> = {
  critical: 'bg-red-50 text-red-700 border-red-200',
  high: 'bg-amber-50 text-amber-700 border-amber-200',
  moderate: 'bg-blue-50 text-blue-700 border-blue-200',
  low: 'bg-slate-100 text-slate-600 border-slate-200',
  verified: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  'under-review': 'bg-amber-50 text-amber-600 border-amber-200',
  default: 'bg-slate-100 text-slate-600 border-slate-200',
};

export function Badge({ variant = 'default', children, className, animated = true }: BadgeProps) {
  const Component = animated ? motion.span : 'span';
  const animationProps = animated
    ? { variants: scaleIn, initial: 'hidden', animate: 'visible' }
    : {};

  return (
    <Component
      {...animationProps}
      className={cn(
        'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        variantStyles[variant],
        className
      )}
    >
      {children}
    </Component>
  );
}
