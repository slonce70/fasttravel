import Link from 'next/link';
import type { SearchResultItem } from '@/lib/types';
import { Card } from './ui/Card';
import { SafeImage } from './ui/SafeImage';
import { Stars } from './ui/Stars';
import { formatPrice } from '@/lib/format';
import { cn } from '@/lib/utils';

export interface HotelCardProps {
  hotel: SearchResultItem;
  variant?: 'card' | 'row';
}

export function HotelCard({ hotel, variant = 'card' }: HotelCardProps) {
  // Backend returns photos as `photos: [{url, alt?, ...}]`. We display the
  // first one (typically the farvater og:image). Empty array = render a
  // neutral placeholder so the grid keeps its rhythm.
  const photo = hotel.photos?.[0];
  return (
    <Card
      data-card-variant={variant}
      className={cn(
        'group overflow-hidden rounded-xl shadow-[0_18px_45px_-28px_rgba(15,23,42,0.5)] transition-all hover:-translate-y-0.5 hover:shadow-[0_24px_60px_-32px_rgba(15,23,42,0.6)]',
        variant === 'row' ? 'flex' : 'flex h-full flex-col',
      )}
    >
      <Link
        href={`/hotels/${hotel.canonical_slug}`}
        className={cn('flex flex-1', variant === 'row' ? 'flex-col sm:flex-row' : 'flex-col')}
        aria-label={
          hotel.min_price_uah
            ? `${hotel.name_uk}, ціна від ${formatPrice(hotel.min_price_uah)}`
            : hotel.name_uk
        }
      >
        <div
          className={cn(
            'relative overflow-hidden bg-slate-100',
            variant === 'row'
              ? 'h-40 w-full shrink-0 sm:h-auto sm:min-h-36 sm:w-48'
              : 'h-44 w-full',
          )}
        >
          <SafeImage
            src={photo?.url}
            alt={hotel.name_uk}
            className="h-full w-full"
            imgClassName="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        </div>
        <div
          className={cn('flex flex-1 flex-col p-5', variant === 'row' && 'sm:flex-row sm:gap-5')}
        >
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex items-start justify-between gap-2">
              <h3 className="text-base font-semibold leading-tight text-slate-900">
                {hotel.name_uk}
              </h3>
              <Stars count={hotel.stars} className="shrink-0 text-xs" />
            </div>
            {hotel.review_score != null && (
              <p className="mb-3 text-xs text-slate-500">
                <span className="font-semibold text-success-600">
                  {hotel.review_score.toFixed(1)}
                </span>{' '}
                / 10 за відгуками
              </p>
            )}
          </div>
          <div className="mt-auto flex items-end justify-between gap-4 sm:min-w-44 sm:flex-col sm:items-end sm:justify-end">
            <div>
              <p className="text-xs text-slate-500">від</p>
              <p className="text-lg font-bold text-brand-800">{formatPrice(hotel.min_price_uah)}</p>
              {/* Sprint 2.6 — be honest when the price is a duration fallback. */}
              {hotel.nights_fallback && (
                <p className="mt-0.5 text-[10px] uppercase tracking-wide text-amber-600">
                  {hotel.effective_nights
                    ? `ціна за ${hotel.effective_nights} ноч.`
                    : 'інша тривалість'}
                </p>
              )}
              {/* Sprint 2.5 — show price age when it's older than 6h. */}
              {hotel.last_observed_at && _isPriceStale(hotel.last_observed_at) && (
                <p className="mt-0.5 text-[10px] text-slate-500">
                  оновлено {_relativeHours(hotel.last_observed_at)} год тому
                </p>
              )}
            </div>
            <span className="text-sm font-semibold text-teal-700">Переглянути дати →</span>
          </div>
        </div>
      </Link>
    </Card>
  );
}

// Sprint 2.5 helpers — keep tiny + local so date-fns isn't pulled into the
// card bundle. Server-rendered HotelCard runs in node; client hydration
// re-runs in the browser. Both compute the same hours-since-observed
// rounded down, so SSR/CSR don't desync.
function _hoursSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000));
}

function _isPriceStale(iso: string): boolean {
  return _hoursSince(iso) >= 6;
}

function _relativeHours(iso: string): number {
  return _hoursSince(iso);
}
