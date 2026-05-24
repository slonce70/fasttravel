from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    check_in: date | None = None
    nights: int | None = Field(default=None, ge=1, le=30)
    meal_plan: str | None = Field(default=None, max_length=16)
    price_max: int | None = Field(default=None, ge=0)
    stars_min: int | None = Field(default=None, ge=1, le=5)
    adults: int | None = Field(default=None, ge=1, le=9)
    kids: list[int] = []
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hotel_id: int
    canonical_slug: str
    name_uk: str
    stars: int | None
    destination_id: int | None
    min_price_uah: int | None = None
    review_score: float | None = None
    # Thumbnail for the search-result card. Returned as the full photos_jsonb
    # list so the frontend can render whichever index it wants (currently
    # picks [0]). Defaults to an empty list rather than None to keep the
    # consumer's Array.map() unguarded — far fewer null-checks downstream.
    photos: list[dict] = []


class PaginatedSearchResults(BaseModel):
    items: list[SearchResultItem]
    total: int
    limit: int
    offset: int
    price_basis_adults: int = 2
    price_basis_kids: list[int] = []
    pax_supported: bool = True
    pax_note: str | None = None
