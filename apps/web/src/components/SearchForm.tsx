'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { Button } from './ui/Button';

/**
 * Skeleton search form. Three fields on MVP — country (fixed = TR for now),
 * dates window, max budget. Submits via URL params; /search reads them
 * server-side and calls the API.
 */
export function SearchForm({ defaultExpanded = false }: { defaultExpanded?: boolean }) {
  const router = useRouter();
  const params = useSearchParams();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [checkInMin, setCheckInMin] = useState(params.get('check_in_min') ?? '');
  const [checkInMax, setCheckInMax] = useState(params.get('check_in_max') ?? '');
  const [priceMax, setPriceMax] = useState(params.get('price_max') ?? '');
  const [starsMin, setStarsMin] = useState(params.get('stars_min') ?? '');

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const qs = new URLSearchParams();
    qs.set('country', 'TR');
    if (checkInMin) qs.set('check_in_min', checkInMin);
    if (checkInMax) qs.set('check_in_max', checkInMax);
    if (priceMax) qs.set('price_max', priceMax);
    if (starsMin) qs.set('stars_min', starsMin);
    router.push(`/search?${qs.toString()}`);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl bg-white p-4 shadow-lg ring-1 ring-slate-200 sm:p-6"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
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
          Знайти тури в Туреччину
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
