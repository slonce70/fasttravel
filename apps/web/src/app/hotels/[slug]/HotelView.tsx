'use client';

/**
 * Client wrapper for the hotel page — owns the (nights, meal, selectedDate)
 * state so the calendar and offers list stay in sync.
 *
 * The parent server component handles slug→id resolution and SEO metadata;
 * everything stateful lives here.
 */

import { useState } from 'react';
import type { Hotel, MealPlan, Nights } from '@/lib/types';
import { PriceCalendar } from '@/components/PriceCalendar';
import { OffersList } from '@/components/OffersList';
import { Card, CardBody } from '@/components/ui/Card';
import { cn } from '@/lib/utils';
import { formatDateLong } from '@/lib/format';

const NIGHT_OPTIONS: Nights[] = [7, 10, 14];
const MEAL_OPTIONS: { code: MealPlan; label: string }[] = [
  { code: 'AI', label: 'All Inclusive' },
  { code: 'HB', label: 'Напівпансіон (HB)' },
];

export function HotelView({ hotel }: { hotel: Hotel }) {
  const [nights, setNights] = useState<Nights>(7);
  const [mealPlan, setMealPlan] = useState<MealPlan>('AI');
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);

  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <fieldset className="flex flex-wrap items-center gap-6">
            <legend className="sr-only">Параметри пошуку цін</legend>
            <FilterGroup label="Тривалість">
              {NIGHT_OPTIONS.map((n) => (
                <FilterChip
                  key={n}
                  active={n === nights}
                  onClick={() => setNights(n)}
                  label={`${n} ноч.`}
                />
              ))}
            </FilterGroup>
            <FilterGroup label="Харчування">
              {MEAL_OPTIONS.map((m) => (
                <FilterChip
                  key={m.code}
                  active={m.code === mealPlan}
                  onClick={() => setMealPlan(m.code)}
                  label={m.label}
                />
              ))}
            </FilterGroup>
          </fieldset>
        </CardBody>
      </Card>

      <PriceCalendar
        hotelId={hotel.id}
        nights={nights}
        mealPlan={mealPlan}
        onDateSelect={setSelectedDate}
      />

      <section aria-labelledby="offers-heading" className="space-y-3">
        <h2 id="offers-heading" className="text-lg font-semibold text-slate-800">
          Пропозиції операторів
          {selectedDate && (
            <span className="ml-2 text-sm font-normal text-slate-500">
              · заїзд {formatDateLong(selectedDate)}
            </span>
          )}
        </h2>
        <OffersList
          hotelId={hotel.id}
          date={selectedDate}
          nights={nights}
          mealPlan={mealPlan}
        />
      </section>
    </div>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'inline-flex h-9 items-center justify-center rounded-full px-4 text-sm font-medium transition-colors',
        active
          ? 'bg-brand-700 text-white'
          : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
      )}
    >
      {label}
    </button>
  );
}
