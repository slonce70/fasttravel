'use client';

/**
 * PriceCalendar — the moat component.
 *
 * Renders react-day-picker (v9) with a custom `DayButton` that paints each
 * cell with a HSL-heatmap color derived from per-window price percentile and
 * shows the per-night minimum price as a compact label (e.g. "22.4к"). Days
 * flagged as deals get a 🔥 emoji indicator.
 *
 * API contract: GET /api/hotels/{id}/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD
 *   - Backend does NOT filter by nights/mealPlan on this endpoint (it returns
 *     min_7n/min_10n/min_14n columns); we pick the field based on the
 *     `nights` prop. `mealPlan` is reserved for the offers fetch.
 *   - See apps/api/src/routers/hotels.py.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DayPicker, type DayButtonProps } from 'react-day-picker';
import { uk } from 'date-fns/locale';

import { fetchCalendar } from '@/lib/api-client';
import type { CalendarDay, MealPlan, Nights } from '@/lib/types';
import { addDays, cn, isoDate } from '@/lib/utils';
import { formatPriceCompact, formatRelativeTime, formatDateLong } from '@/lib/format';
import { buildPriceScale, colorForPrice, type ColorScale } from '@/lib/deal-color';
import { Skeleton } from './ui';

import 'react-day-picker/style.css';

export interface PriceCalendarProps {
  hotelId: number;
  nights: Nights;
  /**
   * Reserved for the offers fetch (we pass it through `onDateSelect` consumers).
   * The calendar endpoint itself does NOT filter by meal plan on MVP.
   */
  mealPlan: MealPlan;
  /** How many days forward to render. Default = 90 (MVP window). */
  horizonDays?: number;
  onDateSelect?: (date: Date) => void;
}

export function PriceCalendar({
  hotelId,
  nights,
  mealPlan: _mealPlan,
  horizonDays = 90,
  onDateSelect,
}: PriceCalendarProps) {
  const [selected, setSelected] = useState<Date | undefined>();

  const today = useMemo(() => stripTime(new Date()), []);
  const to = useMemo(() => addDays(today, horizonDays), [today, horizonDays]);
  const fromIso = isoDate(today);
  const toIso = isoDate(to);

  const { data, isLoading, isError, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['calendar', hotelId, fromIso, toIso],
    queryFn: ({ signal }) =>
      fetchCalendar(hotelId, { from: fromIso, to: toIso }, { signal }),
    staleTime: 5 * 60 * 1000,
  });

  const { byDate, scale } = useMemo(() => buildDayIndex(data ?? [], nights), [data, nights]);

  return (
    <section
      aria-label="Календар цін на тури"
      className="rounded-2xl bg-slate-100/60 p-4 ring-1 ring-slate-200"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-800">
          Календар цін{' '}
          <span className="text-sm font-normal text-slate-500">
            ({nights} ночей, {_mealPlan})
          </span>
        </h2>
        <Legend />
      </div>

      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : isLoading ? (
        <CalendarSkeleton />
      ) : !data || data.length === 0 ? (
        <EmptyState />
      ) : (
        <DayPicker
          mode="single"
          locale={uk}
          numberOfMonths={2}
          weekStartsOn={1}
          showOutsideDays={false}
          startMonth={today}
          endMonth={to}
          disabled={[{ before: today }, { after: to }]}
          selected={selected}
          onSelect={(d) => {
            if (!d) return;
            setSelected(d);
            onDateSelect?.(d);
          }}
          components={{
            DayButton: (props) => (
              <PriceDayButton {...props} byDate={byDate} scale={scale} nights={nights} />
            ),
          }}
          classNames={{
            months: 'flex flex-col gap-4 md:flex-row md:gap-6',
            day: 'p-0',
          }}
        />
      )}

      <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
        <span aria-live="polite">
          {dataUpdatedAt > 0 ? `Оновлено ${formatRelativeTime(new Date(dataUpdatedAt))}` : ''}
        </span>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded px-2 py-1 hover:bg-slate-200"
        >
          Оновити
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// DayButton — custom renderer
// ---------------------------------------------------------------------------

interface PriceDayButtonProps extends DayButtonProps {
  byDate: Map<string, CalendarDay>;
  scale: ColorScale;
  nights: Nights;
}

function PriceDayButton({ day, modifiers, byDate, scale, nights, ...buttonProps }: PriceDayButtonProps) {
  const key = isoDate(day.date);
  const row = byDate.get(key);
  const price = pickPriceForNights(row, nights);
  const bg = colorForPrice(scale, price ?? null);
  const isDeal = isDealCandidate(row, scale, nights);
  const isOutside = modifiers.outside;
  const isDisabled = modifiers.disabled;

  // Hover hint: discount estimate if price < scale median.
  const median = scale.sorted[Math.floor(scale.sorted.length / 2)];
  const discountHint =
    price != null && median && price < median
      ? `Знижка -${Math.round((1 - price / median) * 100)}% від звичайної ${formatPriceCompact(median)}`
      : undefined;

  return (
    <button
      {...buttonProps}
      type="button"
      disabled={isDisabled}
      aria-label={
        price != null
          ? `${formatDateLong(day.date)}: від ${formatPriceCompact(price)} гривень`
          : `${formatDateLong(day.date)}: цін немає`
      }
      title={discountHint}
      className={cn(
        'group relative flex h-14 w-14 flex-col items-center justify-center rounded-lg border border-transparent text-xs transition-all',
        'focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-1',
        isDisabled && 'cursor-not-allowed opacity-40',
        !isDisabled && price != null && 'hover:scale-105 hover:border-slate-400 hover:shadow-md',
        modifiers.selected && 'border-2 border-brand-700 shadow-md',
        isOutside && 'opacity-30',
      )}
      style={{ backgroundColor: bg ?? undefined }}
    >
      <span
        className={cn(
          'text-sm font-semibold leading-none',
          price != null ? 'text-slate-900' : 'text-slate-400',
        )}
      >
        {day.date.getDate()}
      </span>
      <span className="mt-1 leading-none text-[10px] font-medium text-slate-700">
        {price != null ? formatPriceCompact(price) : '—'}
      </span>
      {isDeal && (
        <span
          className="pointer-events-none absolute right-0.5 top-0.5 text-xs"
          aria-label="гаряча знижка"
          title="гаряча знижка"
        >
          🔥
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stripTime(d: Date): Date {
  const c = new Date(d);
  c.setHours(0, 0, 0, 0);
  return c;
}

function pickPriceForNights(row: CalendarDay | undefined, nights: Nights): number | null {
  if (!row) return null;
  if (nights === 7) return row.min_7n ?? row.min_price_uah ?? null;
  if (nights === 10) return row.min_10n ?? row.min_price_uah ?? null;
  if (nights === 14) return row.min_14n ?? row.min_price_uah ?? null;
  return row.min_price_uah ?? null;
}

function buildDayIndex(rows: CalendarDay[], nights: Nights) {
  const byDate = new Map<string, CalendarDay>();
  const prices: (number | null)[] = [];
  for (const r of rows) {
    byDate.set(r.check_in, r);
    prices.push(pickPriceForNights(r, nights));
  }
  return { byDate, scale: buildPriceScale(prices) };
}

/**
 * Local "is this a deal?" approximation: price falls in the lowest 15% of
 * visible-window observations AND is at least 15% below median. This mirrors
 * the backend percentile-rule heuristic (ADR-006) at the display layer so
 * the 🔥 emoji appears even when the `deals` table hasn't been populated yet.
 */
function isDealCandidate(
  row: CalendarDay | undefined,
  scale: ColorScale,
  nights: Nights,
): boolean {
  const price = pickPriceForNights(row, nights);
  if (price == null || scale.sorted.length < 8) return false;
  const p15Index = Math.floor(scale.sorted.length * 0.15);
  const p50Index = Math.floor(scale.sorted.length / 2);
  const p15 = scale.sorted[p15Index];
  const p50 = scale.sorted[p50Index];
  if (p15 == null || p50 == null) return false;
  return price <= p15 && price <= p50 * 0.85;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Legend() {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500" aria-hidden>
      <span>дешево</span>
      <span
        className="h-3 w-32 rounded"
        style={{
          background:
            'linear-gradient(to right, hsl(140 70% 88%), hsl(45 70% 82%), hsl(5 70% 76%))',
        }}
      />
      <span>дорого</span>
    </div>
  );
}

function CalendarSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4">
      {[0, 1].map((m) => (
        <div key={m} className="rounded-xl bg-white p-3 shadow-sm">
          <Skeleton className="mb-3 h-5 w-32" />
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: 35 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl bg-white p-12 text-center text-slate-500 ring-1 ring-slate-200">
      <p className="text-base font-medium">Немає доступних турів на ці дати</p>
      <p className="mt-2 text-sm">
        Спробуйте іншу тривалість або харчування, або поверніться пізніше.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-xl bg-white p-12 text-center text-slate-700 ring-1 ring-slate-200">
      <p className="text-base font-medium text-danger-600">
        Не вдалося завантажити ціни
      </p>
      <p className="mt-2 text-sm text-slate-500">
        Перевірте з'єднання або спробуйте ще раз через декілька секунд.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex h-9 items-center justify-center rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
      >
        Спробувати ще раз
      </button>
    </div>
  );
}

