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
  Deal,
  Hotel,
  Offer,
  PaginatedDeals,
  PaginatedSearchResults,
  SearchParams,
} from './types';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  // Build-time fallback so Cloudflare Pages doesn't crash if env var missing.
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

interface FetchOptions {
  /** Pass through to Next.js fetch for ISR; ignored in browser. */
  revalidate?: number;
  /** AbortSignal for client-side cancellation. */
  signal?: AbortSignal;
}

async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const init: RequestInit & { next?: { revalidate?: number } } = {
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
export async function fetchHotel(slug: string): Promise<Hotel | null> {
  try {
    return await apiFetch<Hotel>(`/api/hotels/${encodeURIComponent(slug)}`, {
      revalidate: 3600,
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
   * NOTE: the backend `/calendar` endpoint does NOT accept `nights` or
   * `meal` filters on MVP (see apps/api/src/routers/hotels.py). The response
   * carries min_7n/min_10n/min_14n columns and the UI picks the right one.
   * Meal-plan filtering happens only at the offers endpoint.
   */
}

export async function fetchCalendar(
  hotelId: number,
  params: CalendarParams,
  opts: FetchOptions = {},
): Promise<CalendarDay[]> {
  const qs = new URLSearchParams({ from: params.from, to: params.to }).toString();
  return apiFetch<CalendarDay[]>(`/api/hotels/${hotelId}/calendar?${qs}`, opts);
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

/**
 * Permalink lookup. There is NO `/api/deals/{id}` endpoint on MVP; we paginate
 * through `/api/deals?limit=200` and filter client-side. This is acceptable
 * for the deal volume we expect (low hundreds/day). Backend follow-up:
 * add `GET /api/deals/{id}` for proper SEO permalinks.
 */
export async function fetchDealById(id: number, opts: FetchOptions = {}): Promise<Deal | null> {
  const page = await fetchDeals({ limit: 200 }, { revalidate: 300, ...opts });
  return page.items.find((d) => d.id === id) ?? null;
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
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const path = qs.toString() ? `/api/search?${qs.toString()}` : '/api/search';
  return apiFetch<PaginatedSearchResults>(path, opts);
}
