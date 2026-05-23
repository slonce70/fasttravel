"""Hotel search endpoint."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models import Destination, Hotel
from src.schemas.search import PaginatedSearchResults, SearchResultItem

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=PaginatedSearchResults)
async def search(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    check_in_min: date | None = None,
    check_in_max: date | None = None,
    price_max: int | None = Query(default=None, ge=0),
    stars_min: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> PaginatedSearchResults:
    """Search hotels by basic facets.

    Price filtering uses `hotel_calendar_prices` MV when date range given;
    when no date is given we fall back to "any hotel with active records".

    NOTE: filtering by price/date is stubbed — implementation lands once
    the MV is populated. For now this endpoint returns hotels matching
    country and stars facets only.
    """
    _ = (check_in_min, check_in_max, price_max)  # placeholders for later

    conditions = [Hotel.is_active.is_(True)]
    base = select(Hotel)

    if country:
        base = base.join(Destination, Destination.id == Hotel.destination_id)
        conditions.append(Destination.country_iso2 == country.upper())

    if stars_min is not None:
        conditions.append(Hotel.stars >= stars_min)

    base = base.where(and_(*conditions)).order_by(Hotel.review_score.desc().nullslast())

    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await session.execute(base.limit(limit).offset(offset))).scalars().all()

    items = [
        SearchResultItem(
            hotel_id=h.id,
            canonical_slug=h.canonical_slug,
            name_uk=h.name_uk,
            stars=h.stars,
            destination_id=h.destination_id,
            min_price_uah=None,
            review_score=float(h.review_score) if h.review_score is not None else None,
        )
        for h in rows
    ]

    return PaginatedSearchResults(items=items, total=int(total), limit=limit, offset=offset)
