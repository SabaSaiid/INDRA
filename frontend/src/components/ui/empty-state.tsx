'use client';

import React from 'react';
import { cn } from '@/lib/utils';

/**
 * The honest alternative to mock data.
 *
 * Before 21 Sep every panel fell back to invented rows when its request failed
 * *or came back empty*, so an empty database and a dead backend both rendered a
 * full, confident dashboard. These two states replace that: one says there is
 * nothing to show yet, the other says the backend could not be reached. They are
 * visually distinct on purpose — an operator has to be able to tell "no floods
 * reported" from "I am not receiving data".
 *
 * Styling follows the existing card language (#FDFAF5 paper, #E8E2D4 borders,
 * muted ink) so a panel in either state still looks like part of the dashboard.
 */

interface EmptyStateProps {
  /** One short line: what is absent. */
  title: string;
  /** Optional second line: why that is normal, or what to do. */
  hint?: string;
  icon?: React.ReactNode;
  className?: string;
  compact?: boolean;
}

export function EmptyState({ title, hint, icon, className, compact = false }: EmptyStateProps) {
  return (
    <div
      data-testid="empty-state"
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'py-6 px-3' : 'py-10 px-4',
        className
      )}
    >
      {icon && <div className="mb-2 text-[#B8AE99]">{icon}</div>}
      <p className={cn('font-medium text-[#6B6355]', compact ? 'text-xs' : 'text-sm')}>
        {title}
      </p>
      {hint && (
        <p className={cn('mt-1 max-w-[30ch] text-[#9A917F]', compact ? 'text-[10px]' : 'text-xs')}>
          {hint}
        </p>
      )}
    </div>
  );
}

interface ErrorStateProps {
  /** What could not be loaded, in the operator's words ("live events"). */
  label: string;
  /** The thrown error, if there is one. Its message is shown verbatim. */
  error?: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}

export function ErrorState({ label, error, onRetry, className, compact = false }: ErrorStateProps) {
  const detail =
    error instanceof Error ? error.message : typeof error === 'string' ? error : null;

  return (
    <div
      data-testid="error-state"
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'py-6 px-3' : 'py-10 px-4',
        className
      )}
    >
      <div
        className={cn(
          'mb-2 flex items-center justify-center rounded-full bg-[#FEE2E2]',
          compact ? 'h-7 w-7' : 'h-9 w-9'
        )}
      >
        <svg
          width={compact ? 14 : 18}
          height={compact ? 14 : 18}
          viewBox="0 0 24 24"
          fill="none"
          stroke="#DC2626"
          strokeWidth="2.2"
          strokeLinecap="round"
        >
          <path d="M12 8v5" />
          <circle cx="12" cy="16.5" r="0.6" fill="#DC2626" stroke="none" />
          <path d="M10.3 3.9 2.6 17.2A1.9 1.9 0 0 0 4.3 20h15.4a1.9 1.9 0 0 0 1.7-2.8L13.7 3.9a1.9 1.9 0 0 0-3.4 0Z" />
        </svg>
      </div>
      <p className={cn('font-medium text-[#B91C1C]', compact ? 'text-xs' : 'text-sm')}>
        Could not load {label}
      </p>
      {detail && (
        <p className={cn('mt-1 max-w-[34ch] text-[#9A917F]', compact ? 'text-[10px]' : 'text-xs')}>
          {detail}
        </p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={cn(
            'mt-2.5 rounded-md border border-[#E8E2D4] bg-white px-3 py-1 font-medium',
            'text-[#6B6355] transition-colors hover:bg-[#F7F3EA]',
            compact ? 'text-[10px]' : 'text-xs'
          )}
        >
          Retry
        </button>
      )}
    </div>
  );
}
