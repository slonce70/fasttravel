'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchOffers } from '@/lib/api-client';
import type { MealPlan, Nights, Offer } from '@/lib/types';
import { isoDate } from '@/lib/utils';
import { Card, CardBody } from './ui/Card';
import { Skeleton } from './ui/Skeleton';
import { Badge } from './ui/Badge';
import { formatPrice, formatMealPlan, formatRelativeTime, plural } from '@/lib/format';

export interface OffersListProps {
  hotelId: number;
  date: Date | null;
  nights: Nights;
  mealPlan: MealPlan;
}

/**
 * Renders offers from different operators for the selected check-in date.
 * Each row is one operator with its deep_link. The "Buy" link opens in a new
 * tab with rel="nofollow sponsored" per ADR convention (we're an affiliate).
 */
export function OffersList({ hotelId, date, nights, mealPlan }: OffersListProps) {
  const enabled = date != null;
  const dateIso = date ? isoDate(date) : '';

  const { data, isLoading, isError } = useQuery({
    queryKey: ['offers', hotelId, dateIso, nights, mealPlan],
    queryFn: ({ signal }) =>
      fetchOffers(
        hotelId,
        { date: dateIso, nights, meal: mealPlan === 'ALL' ? undefined : mealPlan },
        { signal },
      ),
    enabled,
    staleTime: 60 * 1000,
  });

  if (!enabled) {
    return (
      <Card>
        <CardBody className="text-center text-sm text-slate-500">
          Оберіть дату в календарі вище, щоб побачити пропозиції операторів.
        </CardBody>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div role="status" aria-live="polite" aria-label="Завантаження пропозицій">
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardBody role="status" aria-live="polite" className="text-center text-sm text-danger-600">
          Не вдалося завантажити пропозиції. Спробуйте оновити сторінку.
        </CardBody>
      </Card>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Card>
        <CardBody role="status" aria-live="polite" className="text-center text-sm text-slate-500">
          На цю дату пропозицій немає. Оберіть іншу дату.
        </CardBody>
      </Card>
    );
  }

  const sorted = [...data].sort((a, b) => a.price_uah - b.price_uah);
  const cheapest = sorted[0]?.price_uah ?? 0;

  return (
    <div aria-live="polite" aria-atomic="true">
      <p className="sr-only">
        {sorted.length} {plural(sorted.length, 'пропозиція', 'пропозиції', 'пропозицій')}
      </p>
      <ul className="space-y-2" aria-label="Пропозиції операторів">
        {sorted.map((offer) => (
          <li key={offerKey(offer)}>
            <OfferRow offer={offer} isCheapest={offer.price_uah === cheapest} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function offerKey(offer: Offer): string {
  return [
    offer.operator_id,
    offer.check_in,
    offer.nights,
    offer.meal_plan,
    offer.room_category || '',
    offer.price_uah,
    offer.deep_link || '',
  ].join('|');
}

function OfferRow({ offer, isCheapest }: { offer: Offer; isCheapest: boolean }) {
  return (
    <Card className="flex items-center gap-4 p-4 sm:p-5">
      <div className="flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-sm font-semibold uppercase text-slate-700">
            {offer.operator_code}
          </span>
          {isCheapest && <Badge variant="success">Найнижча ціна</Badge>}
        </div>
        <p className="text-xs text-slate-500">
          {offer.nights} ноч. · {formatMealPlan(offer.meal_plan)}
          {offer.room_category ? ` · ${offer.room_category}` : ''}
        </p>
        <p className="mt-1 text-[11px] text-slate-500">
          оновлено {formatRelativeTime(offer.observed_at)}
        </p>
      </div>
      <div className="text-right">
        <p className="text-xl font-bold text-brand-800">{formatPrice(offer.price_uah)}</p>
        {offer.price_original != null && offer.currency !== 'UAH' && (
          <p className="text-xs text-slate-500">
            {offer.price_original} {offer.currency}
          </p>
        )}
      </div>
      {offer.deep_link ? (
        <div className="flex flex-col items-end gap-0.5">
          <a
            href={offer.deep_link}
            target="_blank"
            rel="nofollow sponsored noopener"
            className="inline-flex h-10 items-center justify-center rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-700"
          >
            Купити →
          </a>
          {/* Visible sponsorship marker — see DealCard for rationale. */}
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Спонсорське посилання
          </span>
        </div>
      ) : null}
    </Card>
  );
}
