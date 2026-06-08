'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

export interface SafeImageProps {
  src: string | null | undefined;
  alt: string;
  className?: string;
  imgClassName?: string;
}

export function SafeImage({ src, alt, className, imgClassName }: SafeImageProps) {
  const normalizedSrc = src?.trim() || null;
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    setHasError(false);
  }, [normalizedSrc]);

  if (!normalizedSrc || hasError) {
    return (
      <div
        className={cn(
          'flex items-center justify-center bg-gradient-to-br from-teal-50 via-cyan-50 to-indigo-50 text-teal-800/75',
          className,
        )}
      >
        <div className="flex flex-col items-center gap-2 px-3 text-center text-sm font-medium">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-10 w-10"
          >
            <path d="M3 21h18" />
            <path d="M5 21V5a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v16" />
            <path d="M14 9h4a1 1 0 0 1 1 1v11" />
            <path d="M8 8h2M8 12h2M8 16h2" />
          </svg>
          <span>Фото недоступне</span>
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={normalizedSrc}
        alt={alt}
        loading="lazy"
        decoding="async"
        onError={() => setHasError(true)}
        className={imgClassName}
      />
    </div>
  );
}
