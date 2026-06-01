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

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, Destination, Hotel
from src.schemas.deal import DealOut, PaginatedDeals

# Deals older than this aren't shown on /api/deals. The active detector
# writes date-dip deals from current_prices; historical/imported deal
# rows stay visible only while they are fresh. Past 48h the deep_link is
# likely to 404 or quote a different price on Farvater.
DEAL_FRESHNESS_HOURS = 48


def _select_deal_columns() -> tuple[Any, ...]:
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
        Deal.detection_method,
        Hotel.canonical_slug.label("hotel_slug"),
        Hotel.name_uk.label("hotel_name_uk"),
        Hotel.stars.label("hotel_stars"),
        Hotel.photos_jsonb[0]["url"].astext.label("hotel_photo_url"),
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
        detection_method=row.detection_method,
        hotel_slug=row.hotel_slug,
        hotel_name_uk=row.hotel_name_uk,
        hotel_stars=row.hotel_stars,
        hotel_photo_url=row.hotel_photo_url,
        destination_name=row.destination_name,
    )


# Whitelist of provenances that may be shown publicly. Mirrors the
# filter applied by post_deals (Telegram broadcast). Anything outside
# this set — synthetic seeds, legacy NULL — stays internal.
_REAL_DEAL_SOURCES = ("farvater_scrape", "live_refresh", "ittour")


_VALID_SORTS = ("discount", "newest", "price")


async def list_deals(
    session: AsyncSession,
    country_iso2: str | None = None,
    nights_min: int | None = None,
    nights_max: int | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "discount",
) -> PaginatedDeals:
    base = (
        select(*_select_deal_columns())
        .join(Hotel, Hotel.id == Deal.hotel_id)
        .outerjoin(Destination, Destination.id == Hotel.destination_id)
        # Public-only: hide synthetic / legacy deals. Same predicate the
        # Telegram broadcaster uses, so the UI feed and the channel
        # stay in sync.
        .where(Deal.source.in_(_REAL_DEAL_SOURCES))
        # Public deals must be measurable discounts. Operator bucket membership
        # without a strike-through belongs in /api/promotions, not here.
        .where(Deal.discount_pct > 0)
        # Sprint 2.4 — drop deals whose underlying price observation has
        # likely aged out of `current_prices` (14-day window). 48h keeps
        # UI honest about offer freshness without burning users on dead
        # deep_links.
        .where(Deal.detected_at >= func.now() - text(f"INTERVAL '{DEAL_FRESHNESS_HOURS} hours'"))
    )
    if country_iso2:
        # When filtering by country we need destination to exist + match,
        # so promote the outerjoin condition to a WHERE that excludes NULLs.
        base = base.where(Destination.country_iso2 == country_iso2.upper())
    if nights_min is not None:
        base = base.where(Deal.nights >= nights_min)
    if nights_max is not None:
        base = base.where(Deal.nights <= nights_max)

    # Product default is "biggest steal first". `newest` was the legacy
    # default but it buried 40% promos under fresh 15% ones; the product
    # claim is "we find the deals", so the deal goes first.
    # Append Deal.id as the final ORDER BY key in every branch so
    # limit/offset paging is deterministic. detect_deals inserts a batch
    # via one INSERT...SELECT, so server_default func.now() gives every
    # deal in a tick an identical detected_at; without a unique tail key
    # those fully-tied rows have no stable order across the separate
    # statements backing consecutive pages — rows can duplicate or be
    # skipped. The PK only disambiguates exact ties; primary ranking is
    # unchanged. Mirrors search_service (appends h.id) and promo_service
    # (appends ranked.c.id).
    if sort == "newest":
        base = base.order_by(Deal.detected_at.desc(), Deal.id.desc())
    elif sort == "price":
        base = base.order_by(Deal.price_uah.asc(), Deal.discount_pct.desc(), Deal.id.desc())
    else:
        # "discount" + tie-break by freshness so the same deal isn't
        # always at the top while a newer matching deal exists.
        base = base.order_by(Deal.discount_pct.desc(), Deal.detected_at.desc(), Deal.id.desc())

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
        .where(Deal.source.in_(_REAL_DEAL_SOURCES))
        .where(Deal.discount_pct > 0)
        .where(Deal.detected_at >= func.now() - text(f"INTERVAL '{DEAL_FRESHNESS_HOURS} hours'"))
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return _row_to_dealout(row)
