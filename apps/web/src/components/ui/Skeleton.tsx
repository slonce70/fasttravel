import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

/**
 * Decorative shimmer placeholder rectangle. Provide an explicit width/height
 * via className. Intentionally silent to assistive tech (aria-hidden): a
 * placeholder is not a status. Loading groups that tile this primitive own the
 * single role="status" aria-live="polite" announcement around the group.
 */
export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('skeleton', className)} {...rest} />;
}
