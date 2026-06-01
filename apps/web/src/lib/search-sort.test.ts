import { describe, expect, it } from 'vitest';
import { DEFAULT_SEARCH_SORT, SEARCH_SORT_OPTIONS, normalizeSearchSort } from './search-sort';

describe('normalizeSearchSort', () => {
  it('falls back to the default for unknown/garbage/empty/nullish input', () => {
    expect(normalizeSearchSort('garbage')).toBe('price_asc');
    expect(normalizeSearchSort('')).toBe('price_asc');
    expect(normalizeSearchSort(null)).toBe('price_asc');
    expect(normalizeSearchSort(undefined)).toBe('price_asc');
    expect(DEFAULT_SEARCH_SORT).toBe('price_asc');
  });

  it('passes through every allow-listed sort value unchanged', () => {
    for (const option of SEARCH_SORT_OPTIONS) {
      expect(normalizeSearchSort(option.value)).toBe(option.value);
    }
  });
});
