import { cn } from '@/lib/utils';

/** Pure-CSS 5-star indicator. Accessible label as a sibling sr-only span. */
export function Stars({ count, className }: { count: number | null; className?: string }) {
  if (count == null) return null;
  const safe = Math.max(1, Math.min(5, Math.round(count)));
  return (
    <span className={cn('inline-flex items-center text-accent-500', className)} aria-hidden>
      {'★'.repeat(safe)}
      <span className="ml-1 text-xs text-slate-400">{'☆'.repeat(5 - safe)}</span>
      <span className="sr-only">{safe} зірок</span>
    </span>
  );
}
