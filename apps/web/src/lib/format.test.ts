// Characterization tests for the UA-locale formatting helpers. These lock the
// current user-facing output (prices, pluralization, meal labels, relative
// time) so a refactor or ICU bump can't silently change what every card and
// page renders. Whitespace is normalised because uk-UA uses U+00A0 grouping.
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  formatDateLong,
  formatDateMedium,
  formatMealPlan,
  formatNights,
  formatPrice,
  formatPriceCompact,
  formatRelativeTime,
  plural,
} from './format';

const ws = (s: string) => s.replace(/\s/g, ' '); // U+00A0 → regular space

describe('formatPrice', () => {
  it('renders UAH with grouped thousands + ₴', () => {
    expect(ws(formatPrice(22400))).toBe('22 400 ₴');
    expect(ws(formatPrice(0))).toBe('0 ₴');
    expect(ws(formatPrice(1000000))).toBe('1 000 000 ₴');
  });

  it('shows an em dash for null/undefined', () => {
    expect(formatPrice(null)).toBe('—');
    expect(formatPrice(undefined)).toBe('—');
  });
});

describe('formatPriceCompact', () => {
  it('keeps small prices verbatim and abbreviates thousands', () => {
    expect(formatPriceCompact(800)).toBe('800');
    expect(formatPriceCompact(999)).toBe('999');
    expect(formatPriceCompact(9800).replace(',', '.')).toBe('9.8к'); // < 10к → one decimal
    expect(formatPriceCompact(22400)).toBe('22к'); // ≥ 10к → rounded integer
    expect(formatPriceCompact(105000)).toBe('105к');
  });

  it('shows an em dash for null/undefined', () => {
    expect(formatPriceCompact(null)).toBe('—');
    expect(formatPriceCompact(undefined)).toBe('—');
  });
});

describe('plural (Ukrainian)', () => {
  it('picks one / few / many by the uk rules', () => {
    const p = (n: number) => plural(n, 'one', 'few', 'many');
    expect(p(1)).toBe('one');
    expect(p(21)).toBe('one');
    expect(p(101)).toBe('one');
    expect(p(11)).toBe('many'); // 11–14 are the exception to "one/few"
    expect(p(2)).toBe('few');
    expect(p(4)).toBe('few');
    expect(p(22)).toBe('few');
    expect(p(12)).toBe('many');
    expect(p(5)).toBe('many');
    expect(p(0)).toBe('many');
    expect(p(100)).toBe('many');
    expect(p(111)).toBe('many');
  });
});

describe('formatNights', () => {
  it('agrees the noun with the count', () => {
    expect(formatNights(1)).toBe('1 ніч');
    expect(formatNights(2)).toBe('2 ночі');
    expect(formatNights(5)).toBe('5 ночей');
    expect(formatNights(11)).toBe('11 ночей');
    expect(formatNights(21)).toBe('21 ніч');
  });
});

describe('formatMealPlan', () => {
  it('maps codes to Ukrainian labels, case-insensitively', () => {
    expect(formatMealPlan('AI')).toBe('Все включено');
    expect(formatMealPlan('bb')).toBe('Сніданок');
    expect(formatMealPlan('HB')).toBe('Сніданок + вечеря');
    expect(formatMealPlan('ro')).toBe('Без харчування');
  });

  it('passes through an unknown code unchanged', () => {
    expect(formatMealPlan('XX')).toBe('XX');
  });
});

describe('formatRelativeTime', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('describes the gap with agreed pluralization, then falls back to a date', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-15T12:00:00Z'));

    expect(formatRelativeTime(new Date('2026-06-15T11:59:40Z'))).toBe('щойно');
    expect(formatRelativeTime(new Date('2026-06-15T11:30:00Z'))).toBe('30 хвилин тому');
    expect(formatRelativeTime(new Date('2026-06-15T10:00:00Z'))).toBe('2 години тому');
    expect(formatRelativeTime(new Date('2026-06-12T12:00:00Z'))).toBe('3 дні тому');
    // > 7 days → absolute medium date (not a relative phrase).
    expect(formatRelativeTime(new Date('2026-05-01T12:00:00Z'))).toMatch(/2026/);
  });
});

describe('date formatters', () => {
  // Local-constructed date avoids a UTC-midnight string shifting the day under
  // a negative-offset test machine; assert tokens to stay ICU-format tolerant.
  const d = new Date(2026, 5, 15); // 15 June 2026, local

  it('formats a medium date with day, abbreviated month, year', () => {
    expect(formatDateMedium(d)).toMatch(/15\s+черв.*2026/);
  });

  it('formats a long date with the full month name', () => {
    expect(formatDateLong(d)).toMatch(/15\s+червня\s+2026/);
  });
});
