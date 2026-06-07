'use client';

/**
 * PriceCalendar — the moat component.
 *
 * Renders react-day-picker (v9) with a custom `DayButton` that paints each
 * cell with a HSL-heatmap color derived from per-window price percentile and
 * shows the per-night minimum price as a compact label (e.g. "22к", or
 * "9,8к" with the uk-UA decimal comma). Days flagged as locally interesting
 * dates get a compact marker.
 *
 * API contract: GET /api/hotels/{id}/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD[&meal=AI][&nights=7]
 *   - `mealPlan` is forwarded as `?meal=` so the backend narrows the MV to
 *     that meal-plan (post migration 002). Omitting it returns the
 *     across-plans MIN per day.
 *   - `nights` is forwarded so the backend can aggregate exact-duration
 *     offers from `current_prices`; hotel-detail UI exposes the same 7..14
 *     night window that Farvater snapshots collect.
 *   - See apps/api/src/routers/hotels.py + services/calendar_service.py.
 */

import { useMemo, useState, type CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DayPicker, type DayButtonProps } from 'react-day-picker';
import { uk } from 'date-fns/locale';

import { fetchCalendar } from '@/lib/api-client';
import type { CalendarDay, MealPlan, Nights } from '@/lib/types';
import { addDays, cn, isoDate } from '@/lib/utils';
import {
  formatMealPlan,
  formatPriceCompact,
  formatRelativeTime,
  formatDateLong,
} from '@/lib/format';
import { buildPriceScale, colorForPrice, priceColor, type ColorScale } from '@/lib/deal-color';
import { Skeleton } from './ui';

import 'react-day-picker/style.css';

const DAY_PICKER_TOUCH_TARGET_STYLE = {
  '--rdp-nav_button-height': '2.75rem',
  '--rdp-nav_button-width': '2.75rem',
} as CSSProperties;

export interface PriceCalendarProps {
  hotelId: number;
  nights: Nights;
  mealPlan: MealPlan;
  selectedDate?: Date | null;
  /** How many days forward to render. Default = 90 (MVP window). */
  horizonDays?: number;
  onDateSelect?: (date: Date) => void;
  onRefreshPrices?: () => void;
  isRefreshingPrices?: boolean;
  refreshNotice?: string | null;
}

export function PriceCalendar({
  hotelId,
  nights,
  mealPlan,
  selectedDate,
  horizonDays = 90,
  onDateSelect,
  onRefreshPrices,
  isRefreshingPrices = false,
  refreshNotice,
}: PriceCalendarProps) {
  const [selected, setSelected] = useState<Date | undefined>();

  const today = useMemo(() => stripTime(new Date()), []);
  const to = useMemo(() => addDays(today, horizonDays), [today, horizonDays]);
  const fromIso = isoDate(today);
  const toIso = isoDate(to);
  const effectiveMealPlan = mealPlan === 'ALL' ? undefined : mealPlan;
  const mealLabel = mealPlan === 'ALL' ? 'будь-яке харчування' : formatMealPlan(mealPlan);

  const { data, isLoading, isFetching, isError, refetch, dataUpdatedAt } = useQuery({
    // mealPlan participates in the queryKey so toggling AI↔HB refetches
    // (otherwise TanStack would serve the cached AI prices when the user
    // flips to HB and the heatmap would lie).
    queryKey: ['calendar', hotelId, fromIso, toIso, nights, effectiveMealPlan ?? 'ALL'],
    queryFn: ({ signal }) =>
      fetchCalendar(
        hotelId,
        { from: fromIso, to: toIso, mealPlan: effectiveMealPlan, nights },
        { signal },
      ),
    // Short staleTime so the on-mount background refresh (HotelView triggers
    // a fresh farvater scrape via POST .../refresh) can pull updated prices
    // into the UI without a hard reload. See #25.
    staleTime: 30_000,
  });

  const { byDate, scale } = useMemo(() => buildDayIndex(data ?? [], nights), [data, nights]);

  return (
    <section
      aria-label="Календар цін на тури"
      className="max-w-full overflow-hidden rounded-2xl bg-slate-100/60 p-3 ring-1 ring-slate-200 sm:p-4"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-800">
          Календар цін{' '}
          <span className="text-sm font-normal text-slate-500">
            ({nights} ночей, {mealLabel})
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
          style={DAY_PICKER_TOUCH_TARGET_STYLE}
          startMonth={today}
          endMonth={to}
          disabled={[{ before: today }, { after: to }]}
          selected={selectedDate ?? selected}
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
          {refreshNotice ??
            (dataUpdatedAt > 0 ? `Оновлено ${formatRelativeTime(new Date(dataUpdatedAt))}` : '')}
        </span>
        <button
          type="button"
          onClick={() => {
            if (onRefreshPrices) {
              onRefreshPrices();
              return;
            }
            void refetch();
          }}
          disabled={isRefreshingPrices || isFetching}
          className="inline-flex min-h-11 items-center rounded-lg px-3 font-medium hover:bg-slate-200 disabled:cursor-wait disabled:opacity-60"
        >
          {isRefreshingPrices || isFetching ? 'Оновлюємо…' : 'Оновити'}
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

function PriceDayButton({
  day,
  modifiers,
  byDate,
  scale,
  nights,
  ...buttonProps
}: PriceDayButtonProps) {
  const key = isoDate(day.date);
  const row = byDate.get(key);
  const price = pickPriceForNights(row, nights);
  const bg = colorForPrice(scale, price ?? null);
  const priceHint = getServerDateDipHint(row);
  const isDeal = priceHint != null;
  const isOutside = modifiers.outside;
  const isDisabled = modifiers.disabled;

  // The 🔥 deal marker's own aria-label is discarded by the accessible-name
  // algorithm because this button supplies an explicit aria-label. So when the
  // day is an interesting date, append the EXISTING honest dip wording (the
  // exact text getServerDateDipHint already produces, also shown in the title)
  // to the button's own label so screen readers get the same signal.
  const baseLabel =
    price != null
      ? `${formatDateLong(day.date)}: від ${formatPriceCompact(price)} гривень`
      : `${formatDateLong(day.date)}: цін немає`;
  const ariaLabel = priceHint ? `${baseLabel}. ${priceHint.title}` : baseLabel;

  return (
    <button
      {...buttonProps}
      type="button"
      disabled={isDisabled}
      aria-label={ariaLabel}
      title={priceHint?.title}
      className={cn(
        'group relative flex h-11 w-11 flex-col items-center justify-center rounded-lg border border-transparent text-xs transition-all sm:h-14 sm:w-14',
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
      <span className="mt-1 text-[10px] font-medium leading-none text-slate-700">
        {price != null ? formatPriceCompact(price) : '—'}
      </span>
      {isDeal && (
        <span
          className="pointer-events-none absolute right-0.5 top-0.5 text-xs"
          aria-label="цікава дата"
          title="цікава дата"
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

/**
 * Pick the exact selected-nights min price from a calendar row.
 *
 * Backend returns `prices_by_night` keyed by stringified night count
 * (e.g. `{"7": 50000, "8": 52000, "14": 47000}`). The calendar header
 * names a specific duration, so cross-nights `min_price_uah` must not be
 * displayed as if it were an exact offer for that duration.
 */
function pickPriceForNights(row: CalendarDay | undefined, nights: Nights): number | null {
  if (!row) return null;
  return row.prices_by_night?.[String(nights)] ?? null;
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

function getServerDateDipHint(row: CalendarDay | undefined): { title: string } | null {
  const price = row?.date_dip_price_uah ?? null;
  const baseline = row?.date_dip_baseline_uah ?? null;
  const pct = row?.date_dip_discount_pct ?? null;
  if (baseline == null || pct == null || pct <= 0) return null;
  const priceText = price != null ? `Є варіант за ${formatPriceCompact(price)}. ` : '';
  return {
    title: `${priceText}На ${pct}% нижче за орієнтир сусідніх дат ${formatPriceCompact(baseline)}`,
  };
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
          // Generate the swatch stops from priceColor() so the legend tracks
          // the exact gradient the cells paint (the rank-0.5 mid-tone is hsl
          // 72.5, not the warmer hsl 45 a hardcoded stop used to advertise).
          background: `linear-gradient(to right, ${priceColor(0)}, ${priceColor(0.5)}, ${priceColor(1)})`,
        }}
      />
      <span>дорого</span>
    </div>
  );
}

function CalendarSkeleton() {
  // Mirror the real DayPicker breakpoints (months stack on mobile, side-by-side
  // at md+; cells h-11 growing to sm:h-14) so the load→loaded swap doesn't shift
  // layout. One status live-region wraps the whole skeleton — the Skeleton
  // tiles themselves are decorative.
  return (
    <div role="status" aria-live="polite" aria-label="Завантаження календаря цін">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {[0, 1].map((m) => (
          <div key={m} className="rounded-xl bg-white p-3 shadow-sm">
            <Skeleton className="mb-3 h-5 w-32" />
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: 35 }).map((_, i) => (
                <Skeleton key={i} className="h-11 w-full sm:h-14" />
              ))}
            </div>
          </div>
        ))}
      </div>
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
      <p className="text-base font-medium text-danger-600">Не вдалося завантажити ціни</p>
      <p className="mt-2 text-sm text-slate-500">
        Перевірте з'єднання або спробуйте ще раз через декілька секунд.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex h-11 items-center justify-center rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
      >
        Спробувати ще раз
      </button>
    </div>
  );
}
