import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a number with commas: 8421 → "8,421"
 */
export function formatNumber(num: number): string {
  return num.toLocaleString('en-IN');
}

/**
 * Get relative time string: "2 hours ago", "5 minutes ago"
 */
export function getRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
}

const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const IST_DAY = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: 'numeric',
  month: 'short',
});
const IST_DATE_KEY = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/**
 * An instant as an operator in India reads it: "20:27" today, "21 Sep 20:27"
 * on any other day. The dashboard used to print the UTC clock time of a report
 * with no date, so a three-day-old report looked like it had just arrived.
 * Returns '' for a missing or unparseable value.
 */
export function formatIst(at?: string | Date | null): string {
  if (!at) return '';
  const d = at instanceof Date ? at : new Date(at);
  if (isNaN(d.getTime())) return '';
  const time = IST_TIME.format(d);
  return IST_DATE_KEY.format(d) === IST_DATE_KEY.format(new Date())
    ? time
    : `${IST_DAY.format(d)} ${time}`;
}

/** "just now", "12m ago", "3h ago", "2d ago" — or '' when there is no instant. */
export function formatAgo(at?: string | Date | null): string {
  if (!at) return '';
  const d = at instanceof Date ? at : new Date(at);
  if (isNaN(d.getTime())) return '';
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
