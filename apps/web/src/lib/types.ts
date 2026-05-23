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

export type Nights = 7 | 10 | 14;
export type MealPlan = 'AI' | 'HB';

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
 *  One row per (hotel, check_in_date) with min-price buckets for each
 *  nights duration. UI selects which bucket to render from `nights` prop.
 */
export interface CalendarDay {
  check_in: string; // ISO date (YYYY-MM-DD)
  min_price_uah: number | null;
  min_7n: number | null;
  min_10n: number | null;
  min_14n: number | null;
  observed_at: string | null; // ISO datetime
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
  // Added in backend-fixes follow-up — JOIN with hotels + destinations
  // so the card can render a real name + clickable slug instead of "Готель #42".
  hotel_slug: string;
  hotel_name_uk: string;
  hotel_stars: number | null;
  destination_name: string | null;
}

export interface PaginatedDeals {
  items: Deal[];
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
  review_score: number | null;
}

export interface PaginatedSearchResults {
  items: SearchResultItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SearchParams {
  country?: string;
  check_in_min?: string;
  check_in_max?: string;
  price_max?: number;
  stars_min?: number;
  limit?: number;
  offset?: number;
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
