"""Promotion listing service backing GET /api/promotions.

Reads from `promo_offers` (written by the static_tours_sweep job) and
joins hotels + destinations so a single round-trip gives the frontend
everything a card needs.

Freshness: only rows observed in the last 24 hours surface. Older
promo_offers stay in the table for forensics but aren't shown.

DISTINCT ON (system_key, bucket_slug): a tour seen in multiple sweeps
within 24h shows only the most recent observation, so the page doesn't
balloon with near-duplicates.
"""

from __future__ import annotations

from typing import Any

from shared.deal_detection import PROMO_MAX_DISCOUNT_PCT
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Destination, Hotel
from src.models.promo_offer import PromoOffer
from src.schemas.promotion import PaginatedPromotions, PromotionOut

# Window in hours for the public promotions feed.
FRESHNESS_WINDOW_HOURS = 24


def _select_columns() -> tuple[Any, ...]:
    return (
        PromoOffer.id,
        PromoOffer.observed_at,
        PromoOffer.bucket_slug,
        PromoOffer.system_key,
        PromoOffer.check_in,
        PromoOffer.nights,
        PromoOffer.meal_plan,
        PromoOffer.price_uah,
        PromoOffer.red_price_uah,
        PromoOffer.is_hot,
        PromoOffer.is_early,
        PromoOffer.is_best_deal,
        PromoOffer.is_recommended,
        PromoOffer.is_choice_farvater,
        PromoOffer.is_otp,
        PromoOffer.is_last_seats,
        PromoOffer.is_black_friday,
        PromoOffer.is_vip,
        PromoOffer.operator_name,
        PromoOffer.promotion_end_date,
        PromoOffer.hotel_id,
        Hotel.canonical_slug.label("hotel_slug"),
        Hotel.name_uk.label("hotel_name_uk"),
        Hotel.stars.label("hotel_stars"),
        Hotel.photos_jsonb[0]["url"].astext.label("hotel_photo_url"),
        Destination.name_uk.label("destination_name"),
        Destination.country_iso2.label("country_iso2"),
    )


def _row_to_out(row) -> PromotionOut:  # type: ignore[no-untyped-def]
    # discount_pct: real strike-through only; bucket membership alone is not a discount.
    has_real_discount = (
        row.red_price_uah is not None and row.red_price_uah > row.price_uah and row.price_uah > 0
    )
    discount_pct = (
        round(100 * (1 - row.price_uah / row.red_price_uah), 2) if has_real_discount else 0.0
    )

    # An implausibly deep strike-through is an inflated anchor, not a real
    # saving (same honest line the scheduler detector draws with
    # PROMO_MAX_DISCOUNT_PCT). Degrade it to the no-discount state so the feed
    # lists the tour without vouching for a fake "-90%".
    if has_real_discount and discount_pct > PROMO_MAX_DISCOUNT_PCT:
        has_real_discount = False
        discount_pct = 0.0

    # Reconstruct the public Farvater deep link from catalog fields.
    if row.country_iso2 and row.hotel_slug:
        slug_tail = row.hotel_slug
        if slug_tail.startswith(f"fv-{row.country_iso2.lower()}-"):
            slug_tail = slug_tail[len(f"fv-{row.country_iso2.lower()}-") :]
        deep_link = (
            f"https://farvater.travel/uk/hotel/"
            f"{row.country_iso2.lower()}/{slug_tail}?q={row.system_key}"
        )
    else:
        deep_link = "https://farvater.travel"

    return PromotionOut(
        id=row.id,
        observed_at=row.observed_at,
        bucket_slug=row.bucket_slug,
        system_key=row.system_key,
        check_in=row.check_in,
        nights=row.nights,
        meal_plan=row.meal_plan,
        price_uah=row.price_uah,
        red_price_uah=row.red_price_uah,
        discount_pct=discount_pct,
        has_real_discount=has_real_discount,
        is_hot=row.is_hot,
        is_early=row.is_early,
        is_best_deal=row.is_best_deal,
        is_recommended=row.is_recommended,
        is_choice_farvater=row.is_choice_farvater,
        is_otp=row.is_otp,
        is_last_seats=row.is_last_seats,
        is_black_friday=row.is_black_friday,
        is_vip=row.is_vip,
        operator_name=row.operator_name,
        promotion_end_date=row.promotion_end_date,
        deep_link=deep_link,
        hotel_id=row.hotel_id,
        hotel_slug=row.hotel_slug,
        hotel_name_uk=row.hotel_name_uk,
        hotel_stars=row.hotel_stars,
        hotel_photo_url=row.hotel_photo_url,
        destination_name=row.destination_name,
        country_iso2=row.country_iso2,
    )


async def list_promotions(
    session: AsyncSession,
    *,
    bucket: str | None = None,
    country: str | None = None,
    min_discount_pct: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedPromotions:
    """Paginated list of promo offers, optionally filtered."""
    row_number = (
        func.row_number()
        .over(
            partition_by=(PromoOffer.system_key, PromoOffer.bucket_slug),
            order_by=(PromoOffer.observed_at.desc(), PromoOffer.id.desc()),
        )
        .label("rn")
    )
    base = (
        select(*_select_columns())
        .add_columns(row_number)
        .join(Hotel, Hotel.id == PromoOffer.hotel_id)
        .outerjoin(Destination, Destination.id == Hotel.destination_id)
        .where(
            PromoOffer.observed_at
            >= func.now() - text(f"INTERVAL '{FRESHNESS_WINDOW_HOURS} hours'")
        )
    )
    if bucket:
        base = base.where(PromoOffer.bucket_slug == bucket)
    if country:
        base = base.where(Destination.country_iso2 == country.upper())
    if min_discount_pct is not None and min_discount_pct > 0:
        # discount_pct computed in the SELECT; use raw expression so the
        # filter applies in SQL rather than post-query. Keep this aligned
        # with `_row_to_out`: implausibly deep anchors are not real discounts.
        base = base.where(
            text(
                "promo_offers.red_price_uah IS NOT NULL "
                "AND promo_offers.red_price_uah > promo_offers.price_uah "
                "AND promo_offers.price_uah > 0 "
                "AND ROUND(100 * (1 - promo_offers.price_uah::numeric / "
                "promo_offers.red_price_uah), 2) >= :min_pct "
                "AND ROUND(100 * (1 - promo_offers.price_uah::numeric / "
                "promo_offers.red_price_uah), 2) <= :max_pct"
            ).bindparams(min_pct=min_discount_pct, max_pct=PROMO_MAX_DISCOUNT_PCT)
        )

    ranked = base.subquery()
    public_columns = [c for c in ranked.c if c.key != "rn"]
    page = (
        select(*public_columns)
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.observed_at.desc(), ranked.c.id.desc())
    )

    total = await session.scalar(select(func.count()).select_from(page.subquery())) or 0
    rows = (await session.execute(page.limit(limit).offset(offset))).all()

    return PaginatedPromotions(
        items=[_row_to_out(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )
