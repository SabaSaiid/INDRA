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

// Low Pressure palette — muted, not neon
const variantStyles: Record<BadgeVariant, string> = {
  critical:       'bg-[#F5E8E7] text-[#8C2F26] border-[#D4A9A6]',
  high:           'bg-[#FBF2E4] text-[#8A611E] border-[#D4B87A]',
  moderate:       'bg-[#E6EFF1] text-[#4A6670] border-[#A4BDC5]',
  low:            'bg-[#F3F4F6] text-[#4B5563] border-[#D1D5DB]',
  verified:       'bg-[#E7F2EC] text-[#3A5E46] border-[#9EC4AE]',
  'under-review': 'bg-[#FBF2E4] text-[#8A611E] border-[#D4B87A]',
  default:        'bg-[#F3F4F6] text-[#4B5563] border-[#D1D5DB]',
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
