'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useMemo, useState, type FormEvent } from 'react';
import { Button } from './ui/Button';
import { PaxPicker, paxFromSearchParams, paxToSearchParams, type PaxValue } from './PaxPicker';
import { toApiSearchParams, type RouteSearchParams } from '@/lib/search-params';
import { DEFAULT_SEARCH_SORT, normalizeSearchSort } from '@/lib/search-sort';
import { PRECOMPUTED_NIGHTS, type CountryOut } from '@/lib/types';

/**
 * Search form rendered on home, /search, and /destinations/[country].
 *
 * The list of countries is owned by the parent server component (it can
 * `await fetchDestinations()` cheaply with ISR), so the form stays a thin
 * client component with no data-loading waterfall.
 *
 * `defaultCountry` (ISO2) prefills the selector — used on the
 * /destinations/[country] page so the filter survives navigation.
 *
 * #28: removed the "Більше фільтрів" toggle (it was wired to state with no
 * conditional render — pure dead UI). All filters are now inline, matching
 * farvater.travel's single-row form pattern. On mobile the grid collapses
 * to two columns and wraps; on desktop everything sits on one row.
 */
export interface SearchFormProps {
  countries?: CountryOut[];
  defaultCountry?: string;
}

const MEAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Будь-яке' },
  { value: 'AI', label: 'Все включено (AI)' },
  { value: 'UAI', label: 'Ultra AI' },
  { value: 'FB', label: 'Повний пансіон (FB)' },
  { value: 'HB', label: 'Напівпансіон (HB)' },
  { value: 'BB', label: 'Сніданок (BB)' },
  { value: 'RO', label: 'Без харчування' },
];

const NIGHT_OPTIONS = PRECOMPUTED_NIGHTS;

export function SearchForm({ countries = [], defaultCountry }: SearchFormProps) {
  const router = useRouter();
  const params = useSearchParams();
  const selectableCountries = useMemo(() => uniqueCountriesByIso(countries), [countries]);
  const sanitizedInitial = useMemo(
    () =>
      toApiSearchParams({
        country: readSearchParam(params, 'country') ?? undefined,
        check_in: readSearchParam(params, 'check_in') ?? undefined,
        check_in_min: readSearchParam(params, 'check_in_min') ?? undefined,
        nights: readSearchParam(params, 'nights') ?? undefined,
        meal_plan: readSearchParam(params, 'meal_plan') ?? undefined,
        price_max: readSearchParam(params, 'price_max') ?? undefined,
        stars_min: readSearchParam(params, 'stars_min') ?? undefined,
        adults: readSearchParam(params, 'adults') ?? undefined,
        kids: readSearchParam(params, 'kids') ?? undefined,
        sort: readSearchParam(params, 'sort') ?? undefined,
      }),
    [params],
  );

  // URL ?country wins over the prop default — keeps state across refresh.
  const initialCountry = (sanitizedInitial.country ?? defaultCountry ?? '').toUpperCase();

  const [country, setCountry] = useState(initialCountry);
  // Phase 2 P0-1 collapsed the old date range (check_in_min/max) into a
  // single check_in. The backend now narrows to that specific day via
  // INNER JOIN on hotel_calendar_prices(hotel_id, check_in). Read either
  // the new `check_in` param or the legacy `check_in_min` to preserve
  // bookmarks while old URLs cycle out.
  const [checkIn, setCheckIn] = useState(sanitizedInitial.check_in ?? '');
  const [nights, setNights] = useState(
    sanitizedInitial.nights !== undefined ? String(sanitizedInitial.nights) : '',
  );
  const [mealPlan, setMealPlan] = useState(sanitizedInitial.meal_plan ?? '');
  const [priceMax, setPriceMax] = useState(
    sanitizedInitial.price_max !== undefined ? String(sanitizedInitial.price_max) : '',
  );
  const [starsMin, setStarsMin] = useState(
    sanitizedInitial.stars_min !== undefined ? String(sanitizedInitial.stars_min) : '',
  );
  const [pax, setPax] = useState<PaxValue>(() =>
    paxFromSearchParams((k) => readSearchParam(params, k)),
  );

  // Stable lookup so we can show "Знайти тури в {country}" without re-scanning.
  const countryByIso = useMemo(() => {
    const map = new Map<string, CountryOut>();
    for (const c of selectableCountries) map.set(c.country_iso2.toUpperCase(), c);
    return map;
  }, [selectableCountries]);

  const selectedCountry = country ? countryByIso.get(country) : undefined;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const qs = new URLSearchParams();
    const currentSort = normalizeSearchSort(readSearchParam(params, 'sort'));
    const raw: RouteSearchParams = {
      country,
      check_in: checkIn,
      nights,
      meal_plan: mealPlan,
      price_max: priceMax,
      stars_min: starsMin,
      adults: String(pax.adults),
      kids: pax.kids.length > 0 ? pax.kids.join(',') : undefined,
      sort: currentSort,
    };
    const sanitized = toApiSearchParams(raw);
    if (sanitized.country) qs.set('country', sanitized.country);
    if (sanitized.check_in) qs.set('check_in', sanitized.check_in);
    if (sanitized.nights !== undefined) qs.set('nights', String(sanitized.nights));
    if (sanitized.meal_plan) qs.set('meal_plan', sanitized.meal_plan);
    if (sanitized.price_max !== undefined) qs.set('price_max', String(sanitized.price_max));
    if (sanitized.stars_min !== undefined) qs.set('stars_min', String(sanitized.stars_min));
    if (sanitized.sort && sanitized.sort !== DEFAULT_SEARCH_SORT) qs.set('sort', sanitized.sort);
    paxToSearchParams(qs, {
      adults: sanitized.adults ?? pax.adults,
      kids: sanitized.kids ?? [],
    });
    const query = qs.toString();
    router.push(query ? `/search?${query}` : '/search');
  }

  // Ukrainian accusative for the button label. Falls back to nominative for
  // countries we haven't taught (won't happen often — list is short).
  const accusative: Record<string, string> = {
    Туреччина: 'Туреччину',
    Єгипет: 'Єгипет',
    ОАЕ: 'ОАЕ',
    Греція: 'Грецію',
    Іспанія: 'Іспанію',
    Болгарія: 'Болгарію',
    Чорногорія: 'Чорногорію',
    Хорватія: 'Хорватію',
    Кіпр: 'Кіпр',
    Таїланд: 'Таїланд',
    Мальдіви: 'Мальдіви',
    Італія: 'Італію',
    Туніс: 'Туніс',
    'Домініканська Республіка': 'Домініканську Республіку',
    Україна: 'Україну',
  };

  const submitLabel = selectedCountry
    ? `Знайти тури в ${accusative[selectedCountry.name_uk] ?? selectedCountry.name_uk}`
    : 'Знайти тури';

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl bg-white p-4 shadow-lg ring-1 ring-slate-200 sm:p-6"
    >
      {/* Grid: 2 cols mobile, 3 cols sm, 7 cols xl. On lg/xl all fields
          sit on a single row matching farvater's layout. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
        <Field label="Країна" className="col-span-2 sm:col-span-1">
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="input"
            aria-label="Країна призначення"
          >
            <option value="">Будь-яка країна</option>
            {selectableCountries.map((c) => (
              <option key={`${c.country_iso2}-${c.id}`} value={c.country_iso2}>
                {c.name_uk}
                {c.hotel_count > 0 ? ` (${c.hotel_count})` : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Дата заїзду">
          <input
            type="date"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Ночей">
          <select
            value={nights}
            onChange={(e) => setNights(e.target.value)}
            className="input"
            aria-label="Кількість ночей"
          >
            <option value="">Будь-яка</option>
            {NIGHT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Туристи">
          <PaxPicker value={pax} onChange={setPax} />
        </Field>
        <Field label="Харчування">
          <select
            value={mealPlan}
            onChange={(e) => setMealPlan(e.target.value)}
            className="input"
            aria-label="Тип харчування"
          >
            {MEAL_OPTIONS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Бюджет, ₴">
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1000}
            placeholder="50 000"
            value={priceMax}
            onChange={(e) => setPriceMax(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Зірок, не менше">
          <select value={starsMin} onChange={(e) => setStarsMin(e.target.value)} className="input">
            <option value="">Будь-яких</option>
            <option value="3">3★+</option>
            <option value="4">4★+</option>
            <option value="5">5★</option>
          </select>
        </Field>
      </div>
      <div className="mt-4 flex justify-end">
        <Button type="submit" size="lg" className="w-full sm:w-auto">
          {submitLabel}
        </Button>
      </div>
      {/* Inline utility class for inputs (Tailwind doesn't allow `.input` in
          base layer without a plugin; we ship a tiny inline style instead).
          Shared with PaxPicker — both live inside this form. */}
      <style>{`
        .input {
          width: 100%;
          height: 2.5rem;
          padding: 0 0.75rem;
          border-radius: 0.5rem;
          border: 1px solid rgb(203 213 225);
          background: white;
          font-size: 0.875rem;
          color: rgb(15 23 42);
        }
        .input:focus {
          outline: 2px solid rgb(37 99 235);
          outline-offset: 1px;
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </form>
  );
}

function readSearchParam(params: ReturnType<typeof useSearchParams>, key: string): string | null {
  return params.get(key) ?? params.get(`amp;${key}`);
}

function uniqueCountriesByIso(countries: CountryOut[]): CountryOut[] {
  const seen = new Set<string>();
  const result: CountryOut[] = [];
  for (const country of countries) {
    const iso = country.country_iso2.toUpperCase();
    if (seen.has(iso)) continue;
    seen.add(iso);
    result.push(country);
  }
  return result;
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 text-xs font-medium text-slate-600 ${className ?? ''}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}
