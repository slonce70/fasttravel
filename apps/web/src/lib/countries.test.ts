// Characterization tests for the country helpers: Ukrainian accusative-case
// labels ("Знайти тури в <country>") with a nominative fallback, and ISO
// dedup that collapses the same country carried under multiple operators.
import { describe, expect, it } from 'vitest';
import type { CountryOut } from '@/lib/types';
import { accusativeCountry, uniqueCountriesByIso } from './countries';

describe('accusativeCountry', () => {
  it('returns the accusative form for known countries', () => {
    expect(accusativeCountry('Туреччина')).toBe('Туреччину');
    expect(accusativeCountry('Греція')).toBe('Грецію');
    expect(accusativeCountry('Домініканська Республіка')).toBe('Домініканську Республіку');
  });

  it('falls back to the given name when unmapped or already invariant', () => {
    expect(accusativeCountry('Франція')).toBe('Франція'); // unmapped
    expect(accusativeCountry('Єгипет')).toBe('Єгипет'); // same in accusative
  });
});

describe('uniqueCountriesByIso', () => {
  const make = (iso: string, name: string): CountryOut => ({
    id: 0,
    country_iso2: iso,
    country_slug: name.toLowerCase(),
    name_uk: name,
    name_en: null,
    hotel_count: 0,
    regions: [],
  });

  it('keeps the first occurrence per ISO (case-insensitive) and preserves order', () => {
    const result = uniqueCountriesByIso([
      make('TR', 'Туреччина'),
      make('tr', 'Turkey dup'),
      make('EG', 'Єгипет'),
      make('Tr', 'Turkey dup 2'),
    ]);
    expect(result.map((c) => c.name_uk)).toEqual(['Туреччина', 'Єгипет']);
  });

  it('returns an empty list unchanged', () => {
    expect(uniqueCountriesByIso([])).toEqual([]);
  });
});
