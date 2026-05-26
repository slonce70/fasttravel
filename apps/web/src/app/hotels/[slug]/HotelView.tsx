'use client';

/**
 * Client wrapper for the hotel page — owns the (nights, meal, selectedDate)
 * state so the calendar and offers list stay in sync.
 *
 * The parent server component handles slug→id resolution and SEO metadata;
 * everything stateful lives here.
 *
 * Behaviors added in #24 / #25:
 *  - Preset nights mirror the scheduled Farvater ingest exactly: 7..14 nights.
 *    A custom duration is still allowed and queues an exact live refresh for
 *    that value so the calendar can fill from real data instead of pretending.
 *  - Background "live refresh": on mount we fire `POST /api/hotels/{id}/refresh`
 *    so the backend re-scrapes farvater.travel for fresh prices. The query
 *    cache picks up the new MV rows on the next refetch (~10–15s). Banner
 *    appears while the refresh is in flight; failures are silent (graceful
 *    fallback if endpoint is 404 or not yet deployed).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { PRECOMPUTED_NIGHTS, type Hotel, type MealPlan, type Nights } from '@/lib/types';
import { triggerHotelRefresh, type RefreshResponse } from '@/lib/api-client';
import { PriceCalendar } from '@/components/PriceCalendar';
import { OffersList } from '@/components/OffersList';
import { Card, CardBody } from '@/components/ui/Card';
import { addDays, cn, isoDate } from '@/lib/utils';
import { formatDateLong } from '@/lib/format';

const NIGHT_PRESETS: readonly Nights[] = PRECOMPUTED_NIGHTS;
const CUSTOM_NIGHTS_MIN = 1;
const CUSTOM_NIGHTS_MAX = 30;
const MEAL_OPTIONS: { code: MealPlan; label: string }[] = [
  { code: 'ALL', label: 'Будь-яке' },
  { code: 'AI', label: 'All Inclusive' },
  { code: 'UAI', label: 'Ultra AI' },
  { code: 'HB', label: 'Напівпансіон (HB)' },
  { code: 'BB', label: 'Сніданок (BB)' },
  { code: 'FB', label: 'Повний пансіон (FB)' },
  { code: 'RO', label: 'Без харчування' },
];
const AUTO_REFRESH_COOLDOWN_MS = 15 * 60 * 1000;
const AUTO_REFRESH_STORAGE_KEY_PREFIX = 'ft:hotel-refresh:last-at';

type RefreshIntent = {
  source: 'auto' | 'manual' | 'custom';
  nights?: number;
};

export function HotelView({ hotel }: { hotel: Hotel }) {
  const [nights, setNights] = useState<Nights>(7);
  const [mealPlan, setMealPlan] = useState<MealPlan>('ALL');
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const customRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const todayIso = isoDate(new Date());
  const maxDateIso = isoDate(addDays(new Date(), 180));
  const selectedDateIso = selectedDate ? isoDate(selectedDate) : '';

  // --- Background live refresh (issue #25) ---------------------------------
  const queryClient = useQueryClient();
  const invalidateCalendar = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: ['calendar', hotel.id],
      }),
    [hotel.id, queryClient],
  );

  const showTemporaryNotice = useCallback((message: string, ms = 8000) => {
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    setRefreshNotice(message);
    noticeTimerRef.current = setTimeout(() => {
      setRefreshNotice(null);
      noticeTimerRef.current = null;
    }, ms);
  }, []);

  useEffect(
    () => () => {
      if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
      if (customRefreshTimerRef.current) clearTimeout(customRefreshTimerRef.current);
    },
    [],
  );

  const refreshMutation = useMutation({
    mutationFn: (intent: RefreshIntent) => triggerHotelRefresh(hotel.id, { nights: intent.nights }),
    onMutate: (intent) => {
      if (intent.source === 'manual' || intent.source === 'custom') {
        setRefreshNotice(refreshStartingMessage(intent.nights));
      }
    },
    onSettled: async (result: RefreshResponse | null | undefined, _error, intent) => {
      if (result?.queued) {
        // Give the backend a moment to write fresh rows before invalidating.
        const wait = Math.min((result.eta_seconds ?? 10) * 1000, 30_000);
        if (intent.source === 'manual' || intent.source === 'custom') {
          setRefreshNotice(refreshQueuedMessage(intent.nights, Math.ceil(wait / 1000)));
        }
        setTimeout(() => {
          void invalidateCalendar();
          if (intent.source === 'manual' || intent.source === 'custom') {
            showTemporaryNotice('Календар перечитано з live-джерела');
          }
        }, wait);
        return;
      }

      await invalidateCalendar();
      if (intent.source !== 'manual' && intent.source !== 'custom') return;

      if (result?.reason === 'recently_refreshed') {
        showTemporaryNotice('Ціни вже щойно оновлювались, календар перечитано');
      } else if (result?.reason === 'hotel_not_mapped_to_farvater') {
        showTemporaryNotice('Для цього готелю live-оновлення Farvater недоступне');
      } else {
        showTemporaryNotice('Live-оновлення недоступне, календар перечитано');
      }
    },
  });

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_DISABLE_HOTEL_REFRESH === '1') return;
    const storageKey = `${AUTO_REFRESH_STORAGE_KEY_PREFIX}:${hotel.id}`;
    try {
      const lastAttempt = Number(window.sessionStorage.getItem(storageKey));
      if (Number.isFinite(lastAttempt) && Date.now() - lastAttempt < AUTO_REFRESH_COOLDOWN_MS) {
        return;
      }
      window.sessionStorage.setItem(storageKey, String(Date.now()));
    } catch {
      // Storage can be unavailable in privacy modes; refresh remains best-effort.
    }
    // Fire at most once per cooldown window; ignore in-flight state for the trigger itself.
    refreshMutation.mutate({ source: 'auto' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotel.id]);

  const showRefreshBanner = refreshMutation.isPending;
  const handleRefreshPrices = useCallback(() => {
    if (refreshMutation.isPending) return;
    refreshMutation.mutate({ source: 'manual', nights });
  }, [nights, refreshMutation]);

  const queueCustomRefresh = useCallback(
    (nextNights: number, delayMs = 700) => {
      if (customRefreshTimerRef.current) clearTimeout(customRefreshTimerRef.current);
      customRefreshTimerRef.current = setTimeout(() => {
        customRefreshTimerRef.current = null;
        if (refreshMutation.isPending) return;
        refreshMutation.mutate({ source: 'custom', nights: nextNights });
      }, delayMs);
    },
    [refreshMutation],
  );

  const handleCustomNightsChange = useCallback(
    (nextNights: number) => {
      setNights(nextNights);
      queueCustomRefresh(nextNights);
    },
    [queueCustomRefresh],
  );

  const handleCustomNightsCommit = useCallback(
    (nextNights: number) => {
      if (customRefreshTimerRef.current) {
        clearTimeout(customRefreshTimerRef.current);
        customRefreshTimerRef.current = null;
      }
      setNights(nextNights);
      refreshMutation.mutate({ source: 'custom', nights: nextNights });
    },
    [refreshMutation],
  );

  return (
    <div className="space-y-6">
      {showRefreshBanner && (
        <div
          role="status"
          aria-live="polite"
          className="ring-brand-200 flex items-center gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-800 ring-1"
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
                onChange={handleCustomNightsChange}
                onCommit={handleCustomNightsCommit}
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
                className="focus:ring-brand-200 h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2"
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
        onRefreshPrices={handleRefreshPrices}
        isRefreshingPrices={refreshMutation.isPending}
        refreshNotice={refreshNotice}
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
        <OffersList hotelId={hotel.id} date={selectedDate} nights={nights} mealPlan={mealPlan} />
      </section>
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</span>
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
        active ? 'bg-brand-700 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
      )}
    >
      {label}
    </button>
  );
}

/**
 * Manual nights input. Presets are scheduled 7..14, custom values queue an
 * exact live refresh and then the calendar reads the exact `?nights=...` data.
 */
function CustomNightsInput({
  value,
  onChange,
  onCommit,
}: {
  value: number;
  onChange: (n: number) => void;
  onCommit: (n: number) => void;
}) {
  const [draft, setDraft] = useState<string>(String(value));
  const lastSubmittedRef = useRef<number>(value);

  useEffect(() => {
    setDraft(String(value));
    lastSubmittedRef.current = value;
  }, [value]);

  const commit = () => {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.max(CUSTOM_NIGHTS_MIN, Math.min(CUSTOM_NIGHTS_MAX, parsed));
    setDraft(String(clamped));
    if (clamped !== lastSubmittedRef.current) {
      lastSubmittedRef.current = clamped;
      onCommit(clamped);
    }
  };

  return (
    <label className="inline-flex h-9 items-center gap-2 rounded-full bg-slate-100 px-3 text-sm font-medium text-slate-700 transition-colors">
      <span className="text-xs uppercase tracking-wide opacity-80">Своя</span>
      <input
        type="number"
        inputMode="numeric"
        min={CUSTOM_NIGHTS_MIN}
        max={CUSTOM_NIGHTS_MAX}
        value={draft}
        onChange={(e) => {
          const nextDraft = e.target.value;
          setDraft(nextDraft);
          const parsed = Number.parseInt(nextDraft, 10);
          if (!Number.isNaN(parsed) && parsed >= CUSTOM_NIGHTS_MIN && parsed <= CUSTOM_NIGHTS_MAX) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
            (e.target as HTMLInputElement).blur();
          }
        }}
        aria-label="Своя кількість ночей"
        className="h-7 w-14 rounded-md border border-transparent bg-white/90 px-2 text-center text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
    </label>
  );
}

function refreshStartingMessage(nights?: number): string {
  return nights ? `Парсимо live-ціни для ${nights} ночей...` : 'Запускаємо live-оновлення цін...';
}

function refreshQueuedMessage(nights: number | undefined, seconds: number): string {
  const scope = nights ? `для ${nights} ночей ` : '';
  return `Ціни ${scope}оновлюються, календар перечитається за ${seconds} с`;
}
