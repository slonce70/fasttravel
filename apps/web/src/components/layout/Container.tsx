import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function Container({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={cn('container mx-auto max-w-7xl', className)} {...rest}>
      {children}
    </div>
  );
}
