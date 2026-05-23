"""Deal listing service.

Reads Deals enriched with their joined Hotel + Destination context so
the DealCard frontend has slug/name/stars/destination in a single
round-trip (avoids the "Готель #42" placeholder on first paint).

Implementation choice: explicit SQL column selection + outerjoin on
destinations, then build `DealOut` instances field-by-field. We picked
this over SQLAlchemy `relationship()` + `selectinload()` because:

  * `Deal` has no `hotel` relationship today; adding one is fine but
    selectinload issues a second IN-query per relationship, while a
    plain JOIN keeps us at one round-trip (the list endpoint already
    runs a COUNT, two queries is enough).
  * The columns we need are flat — there's no benefit to hydrating full
    Hotel / Destination ORM objects.
  * Mirrors the pattern already established in `routers/search.py`
    (build response item explicitly from selected columns).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, Destination, Hotel
from src.schemas.deal import DealOut, PaginatedDeals


def _select_deal_columns() -> tuple:
    """The flat column tuple used by both list_deals and get_deal_by_id."""
    return (
        Deal.id,
        Deal.hotel_id,
        Deal.operator_id,
        Deal.check_in,
        Deal.nights,
        Deal.meal_plan,
        Deal.price_uah,
        Deal.baseline_p50,
        Deal.discount_pct,
        Deal.deep_link,
        Deal.detected_at,
        Deal.posted_at,
        Hotel.canonical_slug.label("hotel_slug"),
        Hotel.name_uk.label("hotel_name_uk"),
        Hotel.stars.label("hotel_stars"),
        Destination.name_uk.label("destination_name"),
    )


def _row_to_dealout(row) -> DealOut:  # type: ignore[no-untyped-def]
    return DealOut(
        id=row.id,
        hotel_id=row.hotel_id,
        operator_id=row.operator_id,
        check_in=row.check_in,
        nights=row.nights,
        meal_plan=row.meal_plan,
        price_uah=row.price_uah,
        baseline_p50=row.baseline_p50,
        discount_pct=float(row.discount_pct),
        deep_link=row.deep_link,
        detected_at=row.detected_at,
        posted_at=row.posted_at,
        hotel_slug=row.hotel_slug,
        hotel_name_uk=row.hotel_name_uk,
        hotel_stars=row.hotel_stars,
        destination_name=row.destination_name,
    )


async def list_deals(
    session: AsyncSession,
    country_iso2: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedDeals:
    base = (
        select(*_select_deal_columns())
        .join(Hotel, Hotel.id == Deal.hotel_id)
        .outerjoin(Destination, Destination.id == Hotel.destination_id)
    )
    if country_iso2:
        # When filtering by country we need destination to exist + match,
        # so promote the outerjoin condition to a WHERE that excludes NULLs.
        base = base.where(Destination.country_iso2 == country_iso2.upper())

    base = base.order_by(Deal.detected_at.desc())

    # COUNT over the same JOIN topology so filters apply uniformly.
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await session.execute(base.limit(limit).offset(offset))).all()

    return PaginatedDeals(
        items=[_row_to_dealout(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


async def get_deal_by_id(session: AsyncSession, deal_id: int) -> DealOut | None:
    """Return a single deal enriched with hotel + destination context.

    None means not found — the router translates that to 404.
    """
    stmt = (
        select(*_select_deal_columns())
        .join(Hotel, Hotel.id == Deal.hotel_id)
        .outerjoin(Destination, Destination.id == Hotel.destination_id)
        .where(Deal.id == deal_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return _row_to_dealout(row)
