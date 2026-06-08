'use client';

import { useState } from 'react';
import type { HotelPhoto } from '@/lib/types';
import { SafeImage } from './ui/SafeImage';
import { cn } from '@/lib/utils';

export interface HotelPhotoCarouselProps {
  photos: HotelPhoto[] | null;
  alt: string;
}

/**
 * Simple swipeable carousel. We avoid pulling in a 3rd-party carousel lib
 * on MVP — native scroll-snap gives most of the value at zero kB.
 */
export function HotelPhotoCarousel({ photos, alt }: HotelPhotoCarouselProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  if (!photos || photos.length === 0) {
    return (
      <div
        className="flex aspect-[16/7] w-full items-center justify-center rounded-2xl bg-slate-200 text-slate-400"
        role="img"
        aria-label="Фото готелю недоступне"
      >
        Фото готелю недоступні
      </div>
    );
  }

  const safeIndex = activeIndex < photos.length ? activeIndex : 0;
  const main = photos[safeIndex] ?? photos[0]!;

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-2 overflow-hidden">
      <div className="relative aspect-[16/7] w-full overflow-hidden rounded-2xl bg-slate-100">
        <SafeImage
          src={main.url}
          alt={main.alt ?? alt}
          className="h-full w-full"
          imgClassName="h-full w-full object-cover"
        />
        {photos.length > 1 && (
          <span
            className="absolute bottom-2 right-2 rounded-md bg-slate-900/70 px-2 py-0.5 text-xs font-medium text-white"
            aria-hidden
          >
            {safeIndex + 1} / {photos.length}
          </span>
        )}
      </div>
      {photos.length > 1 && (
        <ul
          className="flex w-full max-w-full snap-x snap-mandatory gap-2 overflow-x-auto pb-1"
          aria-label="Інші фото"
        >
          {photos.map((p, i) => {
            const isActive = safeIndex === i;
            return (
              <li key={p.url} className="shrink-0 snap-start">
                <button
                  type="button"
                  onClick={() => setActiveIndex(i)}
                  aria-label={`Фото ${i + 1} з ${photos.length}`}
                  aria-current={isActive ? 'true' : undefined}
                  className={cn(
                    'relative block h-16 w-24 shrink-0 overflow-hidden rounded-lg transition-all',
                    // Non-color cue: the active thumb gets a thicker inset ring
                    // (ring-4 vs ring-1) so the selection reads in high-contrast
                    // / grayscale, not by hue alone.
                    isActive ? 'ring-4 ring-inset ring-brand-700' : 'ring-1 ring-slate-300',
                  )}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.url} alt="" className="h-full w-full object-cover" loading="lazy" />
                  {isActive && (
                    <span
                      className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-brand-700 text-[10px] font-bold leading-none text-white"
                      aria-hidden
                    >
                      ✓
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
