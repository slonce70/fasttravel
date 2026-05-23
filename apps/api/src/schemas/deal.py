from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DealOut(BaseModel):
    """Detected price-anomaly row, enriched with hotel + destination context.

    The hotel_* and destination_name fields are denormalised joins so the
    DealCard on the frontend doesn't need a second round-trip per row.
    `hotel_stars` is nullable because `hotels.stars` is nullable in the
    schema (not every operator emits a star count).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    hotel_id: int
    operator_id: int
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    baseline_p50: int
    discount_pct: float
    deep_link: str | None = None
    detected_at: datetime
    posted_at: datetime | None = None

    # Joined hotel fields (always present — deals.hotel_id FK is NOT NULL).
    hotel_slug: str
    hotel_name_uk: str
    hotel_stars: int | None = None

    # Joined destination name (NULL if the hotel has no destination_id,
    # which is allowed by the schema: hotels.destination_id is nullable).
    destination_name: str | None = None


class PaginatedDeals(BaseModel):
    items: list[DealOut]
    total: int
    limit: int
    offset: int
