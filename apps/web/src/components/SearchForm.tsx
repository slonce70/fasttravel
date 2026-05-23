'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useMemo, useState, type FormEvent } from 'react';
import { Button } from './ui/Button';
import type { CountryOut } from '@/lib/types';

/**
 * Search form rendered on home, /search, and /destinations/[country].
 *
 * The list of countries is owned by the parent server component (it can
 * `await fetchDestinations()` cheaply with ISR), so the form stays a thin
 * client component with no data-loading waterfall.
 *
 * `defaultCountry` (ISO2) prefills the selector — used on the
 * /destinations/[country] page so the filter survives navigation.
 */
export interface SearchFormProps {
  defaultExpanded?: boolean;
  countries?: CountryOut[];
  defaultCountry?: string;
}

export function SearchForm({
  defaultExpanded = false,
  countries = [],
  defaultCountry,
}: SearchFormProps) {
  const router = useRouter();
  const params = useSearchParams();
  const [expanded, setExpanded] = useState(defaultExpanded);

  // URL ?country wins over the prop default — keeps state across refresh.
  const initialCountry = (params.get('country') ?? defaultCountry ?? '').toUpperCase();

  const [country, setCountry] = useState(initialCountry);
  const [checkInMin, setCheckInMin] = useState(params.get('check_in_min') ?? '');
  const [checkInMax, setCheckInMax] = useState(params.get('check_in_max') ?? '');
  const [priceMax, setPriceMax] = useState(params.get('price_max') ?? '');
  const [starsMin, setStarsMin] = useState(params.get('stars_min') ?? '');

  // Stable lookup so we can show "Знайти тури в {country}" without re-scanning.
  const countryByIso = useMemo(() => {
    const map = new Map<string, CountryOut>();
    for (const c of countries) map.set(c.country_iso2.toUpperCase(), c);
    return map;
  }, [countries]);

  const selectedCountry = country ? countryByIso.get(country) : undefined;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const qs = new URLSearchParams();
    if (country) qs.set('country', country);
    if (checkInMin) qs.set('check_in_min', checkInMin);
    if (checkInMax) qs.set('check_in_max', checkInMax);
    if (priceMax) qs.set('price_max', priceMax);
    if (starsMin) qs.set('stars_min', starsMin);
    const query = qs.toString();
    router.push(query ? `/search?${query}` : '/search');
  }

  // Ukrainian accusative for the button label. Falls back to nominative for
  // countries we haven't taught (won't happen often — list is short).
  const accusative: Record<string, string> = {
    Туреччина: 'Туреччину',
    Єгипет: 'Єгипет',
    'ОАЕ': 'ОАЕ',
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
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Країна">
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="input"
            aria-label="Країна призначення"
          >
            <option value="">Будь-яка країна</option>
            {countries.map((c) => (
              <option key={c.country_iso2} value={c.country_iso2}>
                {c.name_uk}
                {c.hotel_count > 0 ? ` (${c.hotel_count})` : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Заїзд від">
          <input
            type="date"
            value={checkInMin}
            onChange={(e) => setCheckInMin(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Заїзд до">
          <input
            type="date"
            value={checkInMax}
            onChange={(e) => setCheckInMax(e.target.value)}
            className="input"
          />
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
          <select
            value={starsMin}
            onChange={(e) => setStarsMin(e.target.value)}
            className="input"
          >
            <option value="">Будь-яких</option>
            <option value="3">3★+</option>
            <option value="4">4★+</option>
            <option value="5">5★</option>
          </select>
        </Field>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          {expanded ? 'Згорнути фільтри' : 'Більше фільтрів'}
        </button>
        <Button type="submit" size="lg">
          {submitLabel}
        </Button>
      </div>
      {/* Inline utility class for inputs (Tailwind doesn't allow `.input` in
          base layer without a plugin; we ship a tiny inline style instead). */}
      <style>{`
        .input {
          width: 100%;
          height: 2.5rem;
          padding: 0 0.75rem;
          border-radius: 0.5rem;
          border: 1px solid rgb(203 213 225);
          background: white;
          font-size: 0.875rem;
        }
        .input:focus {
          outline: 2px solid rgb(37 99 235);
          outline-offset: 1px;
        }
      `}</style>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
      <span>{label}</span>
      {children}
    </label>
  );
}
