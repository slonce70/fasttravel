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


class PaginatedSearchResults(BaseModel):
    items: list[SearchResultItem]
    total: int
    limit: int
    offset: int
