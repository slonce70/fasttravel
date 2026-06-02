/**
 * TypeScript shapes mirrored from apps/api Pydantic schemas.
 *
 * Keep these in sync with:
 *  - apps/api/src/schemas/hotel.py
 *  - apps/api/src/schemas/calendar.py
 *  - apps/api/src/schemas/deal.py
 *  - apps/api/src/schemas/search.py
 *
 * NOTE: The backend uses snake_case field names; we preserve those here to
 * avoid a translation layer. Components convert at the render boundary only.
 */

import type { SearchSort } from './search-sort';

/**
 * Number of nights for a tour package. The calendar endpoint accepts this
 * value and aggregates exact-duration offers from current_prices.
 */
export type Nights = number;

/** Scheduled Farvater price snapshots are collected for these nights. */
export const PRECOMPUTED_NIGHTS = [7, 8, 9, 10, 11, 12, 13, 14] as const;
export type PrecomputedNights = (typeof PRECOMPUTED_NIGHTS)[number];

export type MealPlan = 'ALL' | 'AI' | 'UAI' | 'HB' | 'BB' | 'FB' | 'RO';

/** apps/api/src/schemas/hotel.py :: HotelOut */
export interface HotelPhoto {
  url: string;
  alt?: string | null;
  width?: number;
  height?: number;
  /** future: tag like "exterior" | "room" | "beach" */
  category?: string;
}

export interface Hotel {
  id: number;
  canonical_slug: string;
  name_uk: string;
  name_en: string | null;
  stars: number | null;
  destination_id: number | null;
  review_score: number | null;
  review_count: number;
  photos_jsonb: HotelPhoto[] | null;
  amenities: string[] | null;
  description_uk: string | null;
  last_updated: string | null;
  is_active: boolean;
}

/** apps/api/src/schemas/calendar.py :: CalendarDay
 *  One row per hotel/check-in date. With `?nights=`, `min_price_uah` is the
 *  exact-duration minimum from current_prices and `prices_by_night` contains
 *  a single entry for that duration. Without `?nights=`, the API returns the
 *  full MV shape — `prices_by_night` is a map keyed by stringified night
 *  count (e.g. `{"7": 50000, "8": 52000, "10": 49000, "14": 47000}`), and
 *  `min_price_uah` is the cross-nights minimum used as a fallback.
 *  `meal_plan` echoes a raw meal code when not re-aggregated, and null when
 *  the backend aggregates across meal plans.
 */
export interface CalendarDay {
  check_in: string; // ISO date (YYYY-MM-DD)
  meal_plan: string | null;
  min_price_uah: number | null;
  /** Keyed by stringified night count. Empty when no nights matched. */
  prices_by_night: Record<string, number>;
  observed_at: string | null; // ISO datetime
  /**
   * Server-side date-dip annotation for the displayed minimum exact-nights
   * window. Null when the row is only a heatmap value, or when no exact offer
   * on that date passes the production detector's local comparable-date gates.
   */
  date_dip_price_uah?: number | null;
  date_dip_baseline_uah?: number | null;
  date_dip_discount_pct?: number | null;
  date_dip_sample_n?: number | null;
}

/** apps/api/src/schemas/calendar.py :: OfferOut */
export interface Offer {
  operator_id: number;
  operator_code: string;
  check_in: string;
  nights: number;
  meal_plan: string;
  room_category: string | null;
  price_uah: number;
  price_original: number | null;
  currency: string;
  deep_link: string | null;
  observed_at: string;
}

/** apps/api/src/schemas/deal.py :: DealOut */
export interface Deal {
  id: number;
  hotel_id: number;
  operator_id: number;
  check_in: string;
  nights: number;
  meal_plan: string;
  price_uah: number;
  baseline_p50: number;
  discount_pct: number;
  deep_link: string | null;
  detected_at: string;
  posted_at: string | null;
  // Why detect_deals flagged this row — used by the UI to render an
  // explanation badge ("аномально дешева дата", "знижка оператора").
  // Defaults to "percentile" on legacy rows.
  detection_method: string;
  // Added in backend-fixes follow-up — JOIN with hotels + destinations
  // so the card can render a real name + clickable slug instead of "Готель #42".
  hotel_slug: string;
  hotel_name_uk: string;
  hotel_stars: number | null;
  hotel_photo_url: string | null;
  destination_name: string | null;
}

export interface PaginatedDeals {
  items: Deal[];
  total: number;
  limit: number;
  offset: number;
}

/** apps/api/src/schemas/promotion.py :: PromotionOut */
export interface Promotion {
  id: number;
  observed_at: string;
  bucket_slug: string;
  system_key: string;
  check_in: string;
  nights: number;
  meal_plan: string;
  price_uah: number;
  red_price_uah: number | null;
  discount_pct: number;
  has_real_discount: boolean;
  is_hot: boolean;
  is_early: boolean;
  is_best_deal: boolean;
  is_recommended: boolean;
  is_choice_farvater: boolean;
  is_otp: boolean;
  is_last_seats: boolean;
  is_black_friday: boolean;
  is_vip: boolean;
  operator_name: string | null;
  promotion_end_date: string | null;
  deep_link: string;
  hotel_id: number;
  hotel_slug: string;
  hotel_name_uk: string;
  hotel_stars: number | null;
  hotel_photo_url: string | null;
  destination_name: string | null;
  country_iso2: string | null;
}

export interface PaginatedPromotions {
  items: Promotion[];
  total: number;
  limit: number;
  offset: number;
}

/** apps/api/src/schemas/search.py :: SearchResultItem */
export interface SearchResultItem {
  hotel_id: number;
  canonical_slug: string;
  name_uk: string;
  stars: number | null;
  destination_id: number | null;
  min_price_uah: number | null;
  deep_link: string | null;
  requested_nights: number | null;
  effective_nights: number | null;
  review_score: number | null;
  /** Sprint 2.5 — server timestamp of the last price observation. */
  last_observed_at: string | null;
  /**
   * Sprint 2.6 — true when the user requested a specific nights count
   * but only OTHER durations have prices; the row's min_price_uah is a
   * fallback, not the exact requested duration's price. Card should
   * badge this so users aren't misled.
   */
  nights_fallback: boolean;
  // Thumbnail set, same shape as HotelOut.photos_jsonb. The card picks
  // photos[0]; empty array → placeholder graphic.
  photos: HotelPhoto[];
}

export interface PaginatedSearchResults {
  items: SearchResultItem[];
  total: number;
  limit: number;
  offset: number;
  price_basis_adults: number;
  price_basis_kids: number[];
  pax_supported: boolean;
  pax_note: string | null;
}

export interface SearchParams {
  country?: string;
  /** ISO date (YYYY-MM-DD) — narrows results to hotels with prices on this day. */
  check_in?: string;
  /** Tour duration used for exact-price filtering. */
  nights?: number;
  /** Meal plan code (`AI`, `HB`, `BB`, ...) — see migration 002. */
  meal_plan?: string;
  price_max?: number;
  stars_min?: number;
  /**
   * #28 pax composition. Adults defaults to 2 in the form; kids is an array
   * of ages (1-17). The MVP backend reports whether the requested pax matches
   * the current price snapshot basis via `pax_supported`.
   */
  adults?: number;
  kids?: number[];
  sort?: SearchSort;
  limit?: number;
  offset?: number;
}

/** apps/api/src/schemas/cheapest_tour.py :: CheapestTourOut
 *  Absolute-cheapest upcoming tour per hotel, ranked within each country.
 *  Distinct from Deal/Promotion: this is "ціна від", NOT a discount — there is
 *  no baseline / discount_pct / strike-through field by design.
 *  The API returns a FLAT list ordered by country_name → rank → hotel_id;
 *  clients group by country_iso2 (see groupByCountry in lib/cheapest-tours).
 */
export interface CheapestTour {
  country_iso2: string;
  country_name: string | null;
  hotel_id: number;
  hotel_slug: string;
  hotel_name: string;
  stars: number; // always >= 3 (server filters NULL/<3 out)
  review_score: number | null;
  review_count: number;
  check_in: string; // ISO date (YYYY-MM-DD)
  nights: number;
  meal_plan: string;
  price_uah: number; // the ONLY price claim — «ціна від»
  deep_link: string | null;
  rank: number; // 1..per_country, per-country ranking key
}

/** apps/api/src/schemas/destination.py :: RegionOut */
export interface RegionOut {
  id: number;
  region_slug: string;
  name_uk: string;
  name_en: string | null;
  hotel_count: number;
}

/** apps/api/src/schemas/destination.py :: CountryOut
 *  A country with its regions and hotel counts. Drives the country selector
 *  and statically-generated /destinations/[country] pages.
 */
export interface CountryOut {
  id: number;
  country_iso2: string;
  country_slug: string;
  name_uk: string;
  name_en: string | null;
  hotel_count: number;
  regions: RegionOut[];
}
