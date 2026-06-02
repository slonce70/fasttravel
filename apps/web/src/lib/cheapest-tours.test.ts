import { describe, expect, it } from 'vitest';
import type { CheapestTour } from './types';
import { groupByCountry } from './cheapest-tours';

function tour(overrides: Partial<CheapestTour> & Pick<CheapestTour, 'country_iso2' | 'hotel_id'>): CheapestTour {
  return {
    country_name: 'Болгарія',
    hotel_slug: `fv-${overrides.hotel_id}`,
    hotel_name: `Hotel ${overrides.hotel_id}`,
    stars: 3,
    review_score: 8,
    review_count: 5,
    check_in: '2026-06-06',
    nights: 7,
    meal_plan: 'RO',
    price_uah: 18000,
    deep_link: null,
    rank: 1,
    ...overrides,
  };
}

describe('groupByCountry', () => {
  it('groups the flat list by country preserving server order (no re-sort)', () => {
    const flat: CheapestTour[] = [
      tour({ country_iso2: 'BG', country_name: 'Болгарія', hotel_id: 1, rank: 1 }),
      tour({ country_iso2: 'BG', country_name: 'Болгарія', hotel_id: 2, rank: 2 }),
      tour({ country_iso2: 'TR', country_name: 'Туреччина', hotel_id: 3, rank: 1 }),
    ];

    const groups = groupByCountry(flat);

    expect(groups.map((g) => g.country_iso2)).toEqual(['BG', 'TR']);
    expect(groups[0]!.tours.map((t) => t.hotel_id)).toEqual([1, 2]);
    expect(groups[1]!.tours.map((t) => t.hotel_id)).toEqual([3]);
  });

  it('keeps fewer-than-N groups intact (does not pad or slice)', () => {
    const flat: CheapestTour[] = [tour({ country_iso2: 'CY', hotel_id: 9, rank: 1 })];
    const groups = groupByCountry(flat);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.tours).toHaveLength(1);
  });

  it('falls back to the ISO2 code when country_name is null', () => {
    const flat: CheapestTour[] = [tour({ country_iso2: 'XX', country_name: null, hotel_id: 5 })];
    expect(groupByCountry(flat)[0]!.country_name).toBe('XX');
  });

  it('returns an empty array for an empty list', () => {
    expect(groupByCountry([])).toEqual([]);
  });
});
