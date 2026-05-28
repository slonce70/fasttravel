import { normalizeSearchSort } from './search-sort';
import type { SearchParams } from './types';

export const PAGE_SIZE = 24;

export type RouteSearchParams = {
  country?: string;
  check_in?: string;
  check_in_min?: string;
  nights?: string;
  meal_plan?: string;
  price_max?: string;
  stars_min?: string;
  adults?: string;
  kids?: string;
  sort?: string;
  limit?: string;
  offset?: string;
  [key: string]: string | undefined;
};

const MAX_KIDS = 6;

export function readParam(sp: RouteSearchParams, key: string): string | undefined {
  return sp[key] ?? sp[`amp;${key}`];
}

function parseBoundedInt(
  raw: string | undefined,
  { min, max }: { min: number; max?: number },
): number | undefined {
  if (!raw) return undefined;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return undefined;
  const n = Number(trimmed);
  if (!Number.isSafeInteger(n) || n < min) return undefined;
  if (max !== undefined && n > max) return undefined;
  return n;
}

function parseCountry(raw: string | undefined): string | undefined {
  if (!raw) return undefined;
  const country = raw.trim().toUpperCase();
  return /^[A-Z]{2}$/.test(country) ? country : undefined;
}

function parseIsoDate(raw: string | undefined): string | undefined {
  if (!raw) return undefined;
  const value = raw.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return undefined;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return undefined;
  }
  return value;
}

function parseKids(raw: string | undefined): number[] | undefined {
  if (!raw) return undefined;
  const parts = raw.split(',').map((s) => s.trim());
  if (parts.length === 0 || parts.length > MAX_KIDS) return undefined;
  const ages = parts.map((part) => parseBoundedInt(part, { min: 1, max: 17 }));
  return ages.every((age): age is number => age !== undefined) ? ages : undefined;
}

export function toApiSearchParams(sp: RouteSearchParams): SearchParams {
  return {
    country: parseCountry(readParam(sp, 'country')),
    check_in: parseIsoDate(readParam(sp, 'check_in') || readParam(sp, 'check_in_min')),
    nights: parseBoundedInt(readParam(sp, 'nights'), { min: 1, max: 30 }),
    meal_plan: readParam(sp, 'meal_plan') || undefined,
    price_max: parseBoundedInt(readParam(sp, 'price_max'), { min: 0 }),
    stars_min: parseBoundedInt(readParam(sp, 'stars_min'), { min: 1, max: 5 }),
    adults: parseBoundedInt(readParam(sp, 'adults'), { min: 1, max: 9 }),
    kids: parseKids(readParam(sp, 'kids')),
    sort: normalizeSearchSort(readParam(sp, 'sort')),
    limit: parseBoundedInt(readParam(sp, 'limit'), { min: 1, max: 100 }) ?? PAGE_SIZE,
    offset: parseBoundedInt(readParam(sp, 'offset'), { min: 0 }) ?? 0,
  };
}

export function searchHref(params: SearchParams, offset: number): string {
  const qs = new URLSearchParams();
  if (params.country) qs.set('country', params.country);
  if (params.check_in) qs.set('check_in', params.check_in);
  if (params.nights !== undefined) qs.set('nights', String(params.nights));
  if (params.meal_plan) qs.set('meal_plan', params.meal_plan);
  if (params.price_max !== undefined) qs.set('price_max', String(params.price_max));
  if (params.stars_min !== undefined) qs.set('stars_min', String(params.stars_min));
  if (params.adults !== undefined) qs.set('adults', String(params.adults));
  if (params.kids && params.kids.length > 0) qs.set('kids', params.kids.join(','));
  if (params.sort && params.sort !== 'price_asc') qs.set('sort', params.sort);
  qs.set('limit', String(params.limit ?? PAGE_SIZE));
  if (offset > 0) qs.set('offset', String(offset));
  return `/search?${qs.toString()}`;
}
