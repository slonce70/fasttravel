import Link from 'next/link';
import type { CheapestTour } from '@/lib/types';
import { Card, CardBody } from './ui/Card';
import { Stars } from './ui/Stars';
import { formatPrice, formatDateMedium, formatNights, formatMealPlan, plural } from '@/lib/format';

export interface CheapestTourCardProps {
  tour: CheapestTour;
}

/**
 * Compact card for the «Найдешевші тури» page. This is an absolute-cheap tour,
 * NOT a discount: the ONLY price claim is «ціна від {price_uah}» — never a
 * baseline, «−X%», or strike-through. Links to the hotel page (not the
 * operator deep link).
 */
export function CheapestTourCard({ tour }: CheapestTourCardProps) {
  const href = `/hotels/${tour.hotel_slug}`;
  return (
    <Card className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md">
      <Link
        href={href}
        className="flex flex-1 flex-col"
        aria-label={`${tour.hotel_name}, ціна від ${formatPrice(tour.price_uah)}`}
      >
        <CardBody className="flex flex-1 flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold leading-tight text-slate-900">
              {tour.hotel_name}
            </h3>
            <Stars count={tour.stars} className="shrink-0 text-xs" />
          </div>
          {tour.review_score != null && (
            <p className="text-xs text-slate-500">
              <span className="font-semibold text-success-600">{tour.review_score.toFixed(1)}</span>{' '}
              / 10 за {tour.review_count}{' '}
              {plural(tour.review_count, 'відгуком', 'відгуками', 'відгуками')}
            </p>
          )}
          <ul className="space-y-1 text-sm text-slate-600">
            <li>
              📅 заїзд {formatDateMedium(tour.check_in)} · {formatNights(tour.nights)}
            </li>
            <li>🍽 {formatMealPlan(tour.meal_plan)}</li>
          </ul>
          <div className="mt-auto">
            <p className="text-xs text-slate-500">ціна від</p>
            <p className="text-2xl font-bold text-brand-800">{formatPrice(tour.price_uah)}</p>
          </div>
        </CardBody>
      </Link>
    </Card>
  );
}
