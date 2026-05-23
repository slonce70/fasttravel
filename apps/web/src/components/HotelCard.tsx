import Link from 'next/link';
import type { SearchResultItem } from '@/lib/types';
import { Card } from './ui/Card';
import { Stars } from './ui/Stars';
import { formatPrice } from '@/lib/format';

export interface HotelCardProps {
  hotel: SearchResultItem;
}

export function HotelCard({ hotel }: HotelCardProps) {
  return (
    <Card className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md">
      <Link
        href={`/hotels/${hotel.canonical_slug}`}
        className="flex flex-1 flex-col p-5"
      >
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
      </Link>
    </Card>
  );
}
