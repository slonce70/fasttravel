"""Public response schemas for /api/promotions."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class PromotionOut(BaseModel):
    """One operator-flagged promo offer, joined with hotel + destination
    context so the frontend can render a card without an extra hotel
    lookup. The shape intentionally mirrors `DealOut` where possible —
    the UI can share a single card component."""

    # promo_offer row
    id: int
    observed_at: datetime
    bucket_slug: str  # 'gorjashhie-tury' | 'rannee-bronirovanie' | ...
    system_key: str
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    red_price_uah: int | None  # null when farvater emits no strike-through
    discount_pct: float  # computed from red/price (0 when no strike-through)
    has_real_discount: bool
    is_hot: bool
    is_early: bool
    is_best_deal: bool
    is_recommended: bool
    is_choice_farvater: bool
    is_otp: bool
    is_last_seats: bool
    is_black_friday: bool
    is_vip: bool
    operator_name: str | None
    promotion_end_date: date | None

    # deep link reconstructed server-side so the client can link directly.
    deep_link: str

    # joined hotel context
    hotel_id: int
    hotel_slug: str
    hotel_name_uk: str
    hotel_stars: int | None
    hotel_photo_url: str | None

    # joined destination context (nullable — some hotels have no
    # destination_id set yet).
    destination_name: str | None
    country_iso2: str | None


class PaginatedPromotions(BaseModel):
    items: list[PromotionOut]
    total: int
    limit: int
    offset: int
