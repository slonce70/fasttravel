import Link from 'next/link';
import type { SearchResultItem } from '@/lib/types';
import { Card } from './ui/Card';
import { Stars } from './ui/Stars';
import { formatPrice } from '@/lib/format';

export interface HotelCardProps {
  hotel: SearchResultItem;
}

export function HotelCard({ hotel }: HotelCardProps) {
  // Backend returns photos as `photos: [{url, alt?, ...}]`. We display the
  // first one (typically the farvater og:image). Empty array = render a
  // neutral placeholder so the grid keeps its rhythm.
  const photo = hotel.photos?.[0];
  return (
    <Card className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md">
      <Link
        href={`/hotels/${hotel.canonical_slug}`}
        className="flex flex-1 flex-col"
        aria-label={
          hotel.min_price_uah
            ? `${hotel.name_uk}, ціна від ${formatPrice(hotel.min_price_uah)}`
            : hotel.name_uk
        }
      >
        <div className="relative h-44 w-full overflow-hidden bg-slate-100">
          {photo?.url ? (
            // Cloudflare Pages does not run Next image optimization here; plain <img>
            // is intentional. Lazy-loaded so off-screen cards don't fetch.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={photo.url}
              alt={hotel.name_uk}
              loading="lazy"
              decoding="async"
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-3xl text-slate-300">
              🏨
            </div>
          )}
        </div>
        <div className="flex flex-1 flex-col p-5">
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
          <div className="mt-auto flex items-end justify-between">
            <div>
              <p className="text-xs text-slate-500">від</p>
              <p className="text-lg font-bold text-brand-800">
                {formatPrice(hotel.min_price_uah)}
              </p>
            </div>
            <span className="text-sm font-medium text-brand-700">Дивитись →</span>
          </div>
        </div>
      </Link>
    </Card>
  );
}
