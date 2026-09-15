import React from 'react';
import { cn } from '@/lib/utils';

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({ className, style }: SkeletonProps) {
  return (
    <div className={cn('skeleton', className)} style={style} />
  );
}

export function KpiCardSkeleton() {
  return (
    <div className="instrument-strip">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="instrument-reading">
          <Skeleton className="h-8 w-20 mb-2" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-3 w-28" style={{ background: '#E8E2D4' }} />
        </div>
      ))}
    </div>
  );
}

export function MapCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <Skeleton className="h-5 w-48 mb-2" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-3 w-64" style={{ background: '#E8E2D4' }} />
        </div>
        <Skeleton className="h-8 w-32 rounded-md" style={{ background: '#E8E2D4' }} />
      </div>
      <Skeleton className="h-[380px] w-full rounded-md" style={{ background: '#E8E2D4' }} />
    </div>
  );
}

export function ListCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-5">
      <div className="flex items-center justify-between mb-4">
        <Skeleton className="h-5 w-40" style={{ background: '#E8E2D4' }} />
        <Skeleton className="h-4 w-16" style={{ background: '#E8E2D4' }} />
      </div>
      {[...Array(4)].map((_, i) => (
        <div key={i} className="flex items-center gap-3 py-3 border-b border-[#E8E2D4] last:border-0">
          <div className="w-1 self-stretch rounded-full" style={{ background: '#E8E2D4' }} />
          <div className="flex-1">
            <Skeleton className="h-4 w-32 mb-2" style={{ background: '#E8E2D4' }} />
            <Skeleton className="h-3 w-24" style={{ background: '#E8E2D4' }} />
          </div>
          <Skeleton className="h-4 w-14 rounded" style={{ background: '#E8E2D4' }} />
        </div>
      ))}
    </div>
  );
}

export function ChartCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-5">
      <div className="flex items-center justify-between mb-4">
        <Skeleton className="h-5 w-36" style={{ background: '#E8E2D4' }} />
      </div>
      <Skeleton className="h-[200px] w-full rounded-md" style={{ background: '#E8E2D4' }} />
    </div>
  );
}
