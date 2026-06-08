import { describe, expect, it } from 'vitest';
import {
  PAGE_SIZE,
  localTodayIso,
  searchHref,
  serializeSearchParams,
  toApiSearchParams,
} from './search-params';

describe('localTodayIso', () => {
  it('formats local calendar parts instead of slicing a UTC timestamp', () => {
    expect(localTodayIso(new Date(2026, 0, 9, 23, 59, 0))).toBe('2026-01-09');
  });
});

describe('serializeSearchParams', () => {
  it('drops empty values and escaped amp-prefixed keys while preserving valid values', () => {
    const params = serializeSearchParams({
      country: 'TR',
      checkIn: '',
      nights: '7',
      sort: 'price_desc',
      offset: undefined,
      'amp;offset': '100',
      price_max: null,
    });

    expect(params.toString()).toBe('country=TR&nights=7&sort=price_desc');
  });
});

describe('toApiSearchParams', () => {
  it('drops unsafe numeric URL params instead of forwarding them to the API', () => {
    expect(
      toApiSearchParams({
        nights: '0',
        price_max: '-1',
        stars_min: '9',
        adults: '10',
        kids: '7,nope',
        limit: '999999',
        offset: '-24',
      }),
    ).toEqual({
      sort: 'price_asc',
      limit: PAGE_SIZE,
      offset: 0,
    });
  });

  it('accepts API-supported numeric boundaries from escaped query params', () => {
    expect(
      toApiSearchParams({
        'amp;country': 'tr',
        'amp;check_in_min': '2026-06-15',
        'amp;nights': '30',
        'amp;price_max': '0',
        'amp;stars_min': '5',
        'amp;adults': '9',
        'amp;kids': '1,17',
        'amp;limit': '100',
        'amp;offset': '24',
      }),
    ).toEqual({
      country: 'TR',
      check_in: '2026-06-15',
      nights: 30,
      price_max: 0,
      stars_min: 5,
      adults: 9,
      kids: [1, 17],
      sort: 'price_asc',
      limit: 100,
      offset: 24,
    });
  });

  it('rejects overlong kids lists instead of silently truncating them', () => {
    expect(toApiSearchParams({ kids: '1,2,3,4,5,6,7' }).kids).toBeUndefined();
  });

  it('drops malformed or impossible check-in dates before calling the API', () => {
    expect(toApiSearchParams({ check_in: 'tomorrow' }).check_in).toBeUndefined();
    expect(toApiSearchParams({ check_in: '2026-02-30' }).check_in).toBeUndefined();
    expect(toApiSearchParams({ check_in: '2026-6-5' }).check_in).toBeUndefined();
    expect(toApiSearchParams({ check_in: '2026-06-05' }).check_in).toBe('2026-06-05');
  });

  it('normalizes a hotel-name query and drops unusably short values', () => {
    expect(toApiSearchParams({ q: '  Rixos   Premium  ' }).q).toBe('Rixos Premium');
    expect(toApiSearchParams({ q: 'r' }).q).toBeUndefined();
  });
});

describe('searchHref', () => {
  it('serializes sanitized search params without invalid optional filters', () => {
    const params = toApiSearchParams({
      country: 'eg',
      nights: '7.5',
      price_max: '-5',
      limit: '999',
      offset: '-1',
    });

    expect(searchHref(params, 24)).toBe('/search?country=EG&limit=24&offset=24');
  });

  it('preserves the full normalized search contract for pagination links', () => {
    const params = toApiSearchParams({
      country: 'tr',
      check_in: '2026-06-15',
      nights: '7',
      meal_plan: 'AI',
      price_max: '75000',
      stars_min: '4',
      q: 'Rixos Premium',
      adults: '3',
      kids: '7,12',
      sort: 'rating_desc',
      limit: '48',
    });

    expect(searchHref(params, 96)).toBe(
      '/search?country=TR&check_in=2026-06-15&nights=7&meal_plan=AI&price_max=75000&stars_min=4&q=Rixos+Premium&adults=3&kids=7%2C12&sort=rating_desc&limit=48&offset=96',
    );
  });
});
