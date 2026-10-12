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

// Semantic theme token bindings
const variantStyles: Record<BadgeVariant, string> = {
  critical:       'bg-severity-critical-soft text-severity-critical border-severity-critical/30',
  high:           'bg-severity-high-soft text-severity-high border-severity-high/30',
  moderate:       'bg-severity-moderate-soft text-severity-moderate border-severity-moderate/30',
  low:            'bg-severity-low-soft text-severity-low border-severity-low/30',
  verified:       'bg-status-verified-soft text-status-verified border-status-verified/30',
  'under-review': 'bg-status-pending-soft text-status-pending border-status-pending/30',
  default:        'bg-surface-raised text-text-secondary border-border',
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
        'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium border',
        variantStyles[variant],
        className
      )}
    >
      {children}
    </Component>
  );
}
