import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

/** Shimmer placeholder rectangle. Provide an explicit width/height via className. */
export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="status"
      aria-label="Завантаження"
      className={cn('skeleton', className)}
      {...rest}
    />
  );
}
