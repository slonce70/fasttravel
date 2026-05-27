from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    check_in: date | None = None
    nights: int | None = Field(default=None, ge=1, le=30)
    meal_plan: str | None = Field(default=None, max_length=16)
    price_max: int | None = Field(default=None, ge=0)
    stars_min: int | None = Field(default=None, ge=1, le=5)
    adults: int | None = Field(default=None, ge=1, le=9)
    kids: list[int] = Field(default_factory=list)
    sort: str = Field(default="price_asc", max_length=32)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hotel_id: int
    canonical_slug: str
    name_uk: str
    stars: int | None
    destination_id: int | None
    # destination_name: short region/city label (e.g. "Хургада"). Bot card
    # renders this as the "📍 ..." line. None when the hotel has no linked
    # destination row.
    destination_name: str | None = None
    min_price_uah: int | None = None
    deep_link: str | None = None
    requested_nights: int | None = None
    effective_nights: int | None = None
    review_score: float | None = None
    # Mirrors hotels.review_count (integer, NOT NULL, default 0). Used by
    # the bot card to render "⭐ 9.4/10 · 1353 відгуки" — without it, the
    # review row hides entirely even when review_score is populated.
    review_count: int = 0
    # Sprint 2.5 — when the price was last observed by our scraper.
    # Read from `hotel_calendar_prices.last_observed_at` (added in 002).
    # Frontend can render "оновлено N год тому" when this is older than
    # 6 hours; null when no price observation exists.
    last_observed_at: datetime | None = None
    # Sprint 2.6 — true when the user requested a specific nights count
    # but the hotel only has offers for OTHER durations. The current
    # row's `min_price_uah` is then a fallback, not the requested
    # nights' price; the UI should badge it accordingly.
    nights_fallback: bool = False
    # Thumbnail for the search-result card. Returned as the full photos_jsonb
    # list so the frontend can render whichever index it wants (currently
    # picks [0]). Defaults to an empty list rather than None to keep the
    # consumer's Array.map() unguarded — far fewer null-checks downstream.
    photos: list[dict[str, object]] = Field(default_factory=list)


class PaginatedSearchResults(BaseModel):
    items: list[SearchResultItem]
    total: int
    limit: int
    offset: int
    price_basis_adults: int = 2
    price_basis_kids: list[int] = Field(default_factory=list)
    pax_supported: bool = True
    pax_note: str | None = None
