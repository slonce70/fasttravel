/**
 * Thin fetch wrapper around the FastAPI backend at `NEXT_PUBLIC_API_URL`.
 *
 * Conventions:
 *  - Server components / route handlers pass `next: { revalidate }` for ISR.
 *  - Client components use TanStack Query (see providers/query-provider.tsx).
 *  - Error handling: 404 returns `null` for "expected absences" (slug lookup);
 *    everything else throws — TanStack Query / error boundaries surface it.
 */

import type {
  CalendarDay,
  CountryOut,
  Deal,
  Hotel,
  Offer,
  PaginatedDeals,
  PaginatedPromotions,
  PaginatedSearchResults,
  SearchParams,
} from './types';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  // Build-time fallback so OpenNext/Cloudflare Workers builds don't crash if env var is missing.
  'http://localhost:8000';

export class ApiError extends Error {
  constructor(
    public status: number,
    public url: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function userMessageForApiError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 400 || error.status === 422) {
      return 'Перевірте параметри пошуку і спробуйте ще раз.';
    }
    if (error.status === 404) {
      return 'Нічого не знайдено за цим запитом.';
    }
    return 'Сервіс тимчасово недоступний. Спробуйте ще раз за хвилину.';
  }
  if (error instanceof TypeError) {
    return 'Не вдалося зʼєднатися із сервісом. Перевірте інтернет і спробуйте ще раз.';
  }
  if (error instanceof Error && /^API \d{3}\b/.test(error.message)) {
    return 'Сервіс тимчасово недоступний. Спробуйте ще раз за хвилину.';
  }
  return 'Не вдалося завантажити дані. Спробуйте ще раз.';
}

interface FetchOptions {
  /** Pass through to Next.js fetch for ISR; ignored in browser. */
  revalidate?: number;
  /** Explicit cache policy for correctness-sensitive server fetches. */
  cache?: RequestCache;
  /** AbortSignal for client-side cancellation. */
  signal?: AbortSignal;
}

async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const init: RequestInit & { next?: { revalidate?: number } } = {
    cache: opts.cache,
    headers: { Accept: 'application/json' },
    signal: opts.signal,
  };
  if (opts.revalidate !== undefined) {
    init.next = { revalidate: opts.revalidate };
  }

  const res = await fetch(url, init);
  if (!res.ok) {
    throw new ApiError(res.status, url, `API ${res.status} on ${path}`);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Hotels
// ---------------------------------------------------------------------------

/** Resolves slug → full hotel object. Returns null on 404 (SEO-friendly). */
export async function fetchHotel(slug: string, opts: FetchOptions = {}): Promise<Hotel | null> {
  try {
    const fetchOptions = opts.cache ? opts : { revalidate: 3600, ...opts };
    return await apiFetch<Hotel>(`/api/hotels/${encodeURIComponent(slug)}`, {
      ...fetchOptions,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export interface CalendarParams {
  from: string; // ISO date
  to: string;
  /**
   * Optional meal-plan filter forwarded as `?meal=` to the backend (post
   * migration 002). When omitted the response carries the MIN across all
   * meal plans for each day.
   *
   * When `nights` is supplied the backend aggregates exact-duration offers
   * from `current_prices`; otherwise it falls back to the legacy calendar MV.
   * See apps/api/src/services/calendar_service.py.
   */
  mealPlan?: string;
  nights?: number;
}

export async function fetchCalendar(
  hotelId: number,
  params: CalendarParams,
  opts: FetchOptions = {},
): Promise<CalendarDay[]> {
  const qs = new URLSearchParams({ from: params.from, to: params.to });
  if (params.mealPlan) qs.set('meal', params.mealPlan);
  if (params.nights !== undefined) qs.set('nights', String(params.nights));
  return apiFetch<CalendarDay[]>(`/api/hotels/${hotelId}/calendar?${qs.toString()}`, opts);
}

export interface OffersParams {
  date: string; // ISO date — the check-in day
  nights?: number;
  meal?: string; // 'AI' | 'HB' | ...
}

export async function fetchOffers(
  hotelId: number,
  params: OffersParams,
  opts: FetchOptions = {},
): Promise<Offer[]> {
  const qs = new URLSearchParams({ date: params.date });
  if (params.nights !== undefined) qs.set('nights', String(params.nights));
  if (params.meal !== undefined) qs.set('meal', params.meal);
  return apiFetch<Offer[]>(`/api/hotels/${hotelId}/offers?${qs.toString()}`, opts);
}

/**
 * Fire-and-(softly)-forget POST that asks the backend to refetch live prices
 * for a single hotel from farvater.travel. Returns metadata about the queued
 * job (or `null` on any non-2xx — refresh is a best-effort UX nicety, not a
 * blocking dependency).
 *
 * Backend endpoint: `POST /api/hotels/{id}/refresh` (added in #25).
 * If the endpoint isn't deployed yet we get a 404 → caller treats as no-op.
 */
export interface RefreshResponse {
  queued: boolean;
  eta_seconds?: number;
  reason?: string | null;
}

export interface RefreshOptions extends FetchOptions {
  nights?: number;
}

export async function triggerHotelRefresh(
  hotelId: number,
  opts: RefreshOptions = {},
): Promise<RefreshResponse | null> {
  const qs = new URLSearchParams();
  if (opts.nights !== undefined) qs.set('nights', String(opts.nights));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const url = `${API_BASE}/api/hotels/${hotelId}/refresh${suffix}`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      signal: opts.signal,
    });
    if (!res.ok) return null;
    return (await res.json()) as RefreshResponse;
  } catch {
    // Network error, abort, CORS — refresh is best-effort, swallow.
    return null;
  }
}

// ---------------------------------------------------------------------------
// Deals
// ---------------------------------------------------------------------------

export interface DealsParams {
  limit?: number;
  offset?: number;
  country?: string;
}

export async function fetchDeals(
  params: DealsParams = {},
  opts: FetchOptions = {},
): Promise<PaginatedDeals> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.country) qs.set('country', params.country);
  const path = qs.toString() ? `/api/deals?${qs.toString()}` : '/api/deals';
  return apiFetch<PaginatedDeals>(path, opts);
}

export async function fetchDealById(id: number, opts: FetchOptions = {}): Promise<Deal | null> {
  try {
    return await apiFetch<Deal>(`/api/deals/${id}`, opts);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Promotions (Sprint 1E) — operator-flagged farvater offers, distinct from
// algorithmic Deals. Same paginated shape; extra filters for bucket/discount.
// ---------------------------------------------------------------------------

export interface PromotionsParams {
  limit?: number;
  offset?: number;
  country?: string;
  bucket?: string;
  min_discount_pct?: number;
}

export async function fetchPromotions(
  params: PromotionsParams = {},
  opts: FetchOptions = {},
): Promise<PaginatedPromotions> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.country) qs.set('country', params.country);
  if (params.bucket) qs.set('bucket', params.bucket);
  if (params.min_discount_pct !== undefined)
    qs.set('min_discount_pct', String(params.min_discount_pct));
  const path = qs.toString() ? `/api/promotions?${qs.toString()}` : '/api/promotions';
  return apiFetch<PaginatedPromotions>(path, opts);
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export async function searchHotels(
  params: SearchParams = {},
  opts: FetchOptions = {},
): Promise<PaginatedSearchResults> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    // Arrays (e.g. `kids: [5,7,9]`) → "5,7,9". Empty arrays are skipped
    // to keep URLs clean.
    if (Array.isArray(v)) {
      if (v.length === 0) continue;
      qs.set(k, v.join(','));
    } else {
      qs.set(k, String(v));
    }
  }
  const path = qs.toString() ? `/api/search?${qs.toString()}` : '/api/search';
  return apiFetch<PaginatedSearchResults>(path, opts);
}

// ---------------------------------------------------------------------------
// Destinations (countries + regions)
// ---------------------------------------------------------------------------

/**
 * Catalog of all countries with their regions + hotel counts. Used by:
 *  - SearchForm country selector
 *  - Footer "Популярні напрямки" list
 *  - generateStaticParams for /destinations/[country]
 *
 * Content is stable for hours — ISR (1h) by default to keep API load near zero.
 */
export async function fetchDestinations(opts: FetchOptions = {}): Promise<CountryOut[]> {
  return apiFetch<CountryOut[]>('/api/destinations', {
    revalidate: 3600,
    ...opts,
  });
}

/** One country by URL slug ('turkey', 'egypt', ...). Returns null on 404. */
export async function fetchDestination(
  slug: string,
  opts: FetchOptions = {},
): Promise<CountryOut | null> {
  try {
    return await apiFetch<CountryOut>(`/api/destinations/${encodeURIComponent(slug)}`, {
      revalidate: 3600,
      ...opts,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
