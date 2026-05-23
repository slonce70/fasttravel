'use client';

import { useState } from 'react';
import type { HotelPhoto } from '@/lib/types';
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

  const main = photos[activeIndex] ?? photos[0]!;

  return (
    <div className="flex flex-col gap-2">
      <div className="relative aspect-[16/7] w-full overflow-hidden rounded-2xl bg-slate-100">
        {/* Using a plain <img> — Cloudflare Pages ships images via the
            CDN directly; next/image optimization needs Sharp which isn't
            on edge runtime. See next.config.mjs `images.unoptimized`. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={main.url}
          alt={main.alt ?? alt}
          className="h-full w-full object-cover"
          loading="eager"
        />
      </div>
      {photos.length > 1 && (
        <ul
          className="flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1"
          aria-label="Інші фото"
        >
          {photos.map((p, i) => (
            <li key={p.url} className="snap-start">
              <button
                type="button"
                onClick={() => setActiveIndex(i)}
                aria-label={`Фото ${i + 1} з ${photos.length}`}
                className={cn(
                  'block h-16 w-24 shrink-0 overflow-hidden rounded-lg ring-2 transition-all',
                  activeIndex === i ? 'ring-brand-700' : 'ring-transparent',
                )}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={p.url}
                  alt=""
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
