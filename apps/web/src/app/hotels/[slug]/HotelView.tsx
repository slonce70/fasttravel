'use client';

/**
 * Client wrapper for the hotel page — owns the (nights, meal, selectedDate)
 * state so the calendar and offers list stay in sync.
 *
 * The parent server component handles slug→id resolution and SEO metadata;
 * everything stateful lives here.
 *
 * Behaviors added in #24 / #25:
 *  - Free-form nights selector: preset chips (3/5/7/10/14/21) + custom number
 *    input committed on blur or Enter. `Nights` is now `number` (was a literal
 *    union); see lib/types.ts.
 *  - Background "live refresh": on mount we fire `POST /api/hotels/{id}/refresh`
 *    so the backend re-scrapes farvater.travel for fresh prices. The query
 *    cache picks up the new MV rows on the next refetch (~10–15s). Banner
 *    appears while the refresh is in flight; failures are silent (graceful
 *    fallback if endpoint is 404 or not yet deployed).
 */

import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Hotel, MealPlan, Nights } from '@/lib/types';
import { triggerHotelRefresh } from '@/lib/api-client';
import { PriceCalendar } from '@/components/PriceCalendar';
import { OffersList } from '@/components/OffersList';
import { Card, CardBody } from '@/components/ui/Card';
import { addDays, cn, isoDate } from '@/lib/utils';
import { formatDateLong } from '@/lib/format';

const NIGHT_PRESETS: Nights[] = [3, 5, 7, 10, 14, 21];
const MEAL_OPTIONS: { code: MealPlan; label: string }[] = [
  { code: 'ALL', label: 'Будь-яке' },
  { code: 'AI', label: 'All Inclusive' },
  { code: 'UAI', label: 'Ultra AI' },
  { code: 'HB', label: 'Напівпансіон (HB)' },
  { code: 'BB', label: 'Сніданок (BB)' },
  { code: 'FB', label: 'Повний пансіон (FB)' },
  { code: 'RO', label: 'Без харчування' },
];
const NIGHTS_MIN = 1;
const NIGHTS_MAX = 30;

export function HotelView({ hotel }: { hotel: Hotel }) {
  const [nights, setNights] = useState<Nights>(7);
  const [mealPlan, setMealPlan] = useState<MealPlan>('ALL');
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const todayIso = isoDate(new Date());
  const maxDateIso = isoDate(addDays(new Date(), 180));
  const selectedDateIso = selectedDate ? isoDate(selectedDate) : '';

  // --- Background live refresh (issue #25) ---------------------------------
  const queryClient = useQueryClient();
  const refreshMutation = useMutation({
    mutationFn: () => triggerHotelRefresh(hotel.id),
    onSettled: async (result) => {
      // Even on null (404 / network error) we still refetch — at worst we
      // pay one extra cached query; at best we pick up new MV data.
      if (result?.queued) {
        // Give the backend a moment to write fresh rows before invalidating.
        const wait = Math.min((result.eta_seconds ?? 10) * 1000, 30_000);
        setTimeout(() => {
          void queryClient.invalidateQueries({
            queryKey: ['calendar', hotel.id],
          });
        }, wait);
      }
    },
  });

  useEffect(() => {
    // Fire once per mount; ignore in-flight state for the trigger itself.
    refreshMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotel.id]);

  const showRefreshBanner = refreshMutation.isPending;

  return (
    <div className="space-y-6">
      {showRefreshBanner && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-800 ring-1 ring-brand-200"
        >
          <span
            aria-hidden
            className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand-600"
          />
          Оновлюємо ціни у фоні…
        </div>
      )}

      <Card>
        <CardBody>
          <fieldset className="flex flex-wrap items-center gap-6">
            <legend className="sr-only">Параметри пошуку цін</legend>
            <FilterGroup label="Тривалість">
              {NIGHT_PRESETS.map((n) => (
                <FilterChip
                  key={n}
                  active={n === nights}
                  onClick={() => setNights(n)}
                  label={`${n} ноч.`}
                />
              ))}
              <CustomNightsInput
                value={nights}
                isCustom={!NIGHT_PRESETS.includes(nights)}
                onCommit={setNights}
              />
            </FilterGroup>
            <FilterGroup label="Дата заїзду">
              <input
                type="date"
                value={selectedDateIso}
                min={todayIso}
                max={maxDateIso}
                onChange={(e) => {
                  setSelectedDate(e.target.value ? parseLocalDate(e.target.value) : null);
                }}
                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200"
                aria-label="Дата заїзду"
              />
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
        selectedDate={selectedDate}
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
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function parseLocalDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) return new Date();
  return new Date(year, month - 1, day);
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

/**
 * Numeric input for arbitrary nights. Local draft state so typing doesn't
 * spam upstream refetches; commits on blur or Enter, clamped to [1, 30].
 * Highlights when the parent's `nights` is a custom (non-preset) value.
 */
function CustomNightsInput({
  value,
  isCustom,
  onCommit,
}: {
  value: number;
  isCustom: boolean;
  onCommit: (n: number) => void;
}) {
  const [draft, setDraft] = useState<string>(String(value));

  // Keep draft in sync if parent value changes (e.g. user clicks a preset).
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = () => {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.max(NIGHTS_MIN, Math.min(NIGHTS_MAX, parsed));
    setDraft(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <label
      className={cn(
        'inline-flex h-9 items-center gap-2 rounded-full px-3 text-sm font-medium transition-colors',
        isCustom
          ? 'bg-brand-700 text-white'
          : 'bg-slate-100 text-slate-700',
      )}
    >
      <span className="text-xs uppercase tracking-wide opacity-80">Своя</span>
      <input
        type="number"
        inputMode="numeric"
        min={NIGHTS_MIN}
        max={NIGHTS_MAX}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
            (e.target as HTMLInputElement).blur();
          }
        }}
        aria-label="Своя кількість ночей"
        className={cn(
          'h-7 w-14 rounded-md border border-transparent bg-white/90 px-2 text-center text-slate-900',
          'focus:outline-none focus:ring-2 focus:ring-brand-500',
        )}
      />
    </label>
  );
}
