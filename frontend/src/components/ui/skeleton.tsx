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

// KPI instrument strip — compact horizontal rail (~54px total)
export function KpiCardSkeleton() {
  return (
    <div className="instrument-strip" style={{ marginBottom: '0.625rem' }}>
      {[...Array(4)].map((_, i) => (
        <div key={i} className="instrument-reading">
          <div className="instrument-reading-values">
            <Skeleton className="h-5 w-16 mb-1" style={{ background: '#E8E2D4' }} />
            <Skeleton className="h-2.5 w-20" style={{ background: '#E8E2D4' }} />
          </div>
          <div className="instrument-reading-delta">
            <Skeleton className="h-3 w-12" style={{ background: '#E8E2D4' }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// Map card skeleton — compact header + 275px canvas
export function MapCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-3.5">
      {/* Single-line compact header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-4 rounded-full" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-4 w-40" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-4 w-14 rounded-full" style={{ background: '#E8E2D4' }} />
        </div>
        <div className="flex items-center gap-1">
          <Skeleton className="h-7 w-20 rounded-md" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-7 w-28 rounded-md" style={{ background: '#E8E2D4' }} />
        </div>
      </div>
      {/* Canvas: matches compact preview height */}
      <Skeleton className="h-[275px] w-full rounded-md" style={{ background: '#E8E2D4' }} />
    </div>
  );
}

// Recent events list skeleton — compact rows
export function ListCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-3.5 h-full max-h-[318px] flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-2">
          <Skeleton className="h-4 w-32" style={{ background: '#E8E2D4' }} />
          <Skeleton className="h-3 w-12" style={{ background: '#E8E2D4' }} />
        </div>
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex items-center gap-2.5 py-1.5 border-b border-[#E8E2D4] last:border-0">
            <div className="w-0.5 h-8 rounded-full flex-shrink-0" style={{ background: '#E8E2D4' }} />
            <div className="flex-1">
              <Skeleton className="h-3.5 w-28 mb-1" style={{ background: '#E8E2D4' }} />
              <Skeleton className="h-2.5 w-20" style={{ background: '#E8E2D4' }} />
            </div>
            <Skeleton className="h-3.5 w-12 rounded" style={{ background: '#E8E2D4' }} />
          </div>
        ))}
      </div>
      <div className="pt-2 border-t border-[#E8E2D4] flex items-center justify-between">
        <Skeleton className="h-3 w-24" style={{ background: '#E8E2D4' }} />
        <Skeleton className="h-3 w-20" style={{ background: '#E8E2D4' }} />
      </div>
    </div>
  );
}

// Analytics/feed card skeleton — compact chart height ~145-235px total
export function ChartCardSkeleton() {
  return (
    <div className="bg-[#FDFAF5] rounded-lg border border-[#E8E2D4] shadow-card p-3.5">
      <div className="flex items-center justify-between mb-2">
        <Skeleton className="h-4 w-32" style={{ background: '#E8E2D4' }} />
        <Skeleton className="h-5 w-16 rounded" style={{ background: '#E8E2D4' }} />
      </div>
      <Skeleton className="h-[155px] w-full rounded-md" style={{ background: '#E8E2D4' }} />
    </div>
  );
}

