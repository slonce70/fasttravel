"""Hotel search endpoint.

Contract (May 2026 — Phase 2 P0-1):

    GET /api/search
      ?country=tr             optional ISO2
      &check_in=2026-06-15    optional, ISO date — narrows to that day
      &nights=7               optional, picks min_<n>n column when 7/10/14
      &meal_plan=AI           optional, filters MV rows
      &price_max=50000        optional, UAH ceiling
      &stars_min=4            optional
      &limit=20 &offset=0

Returns hotels with a real `min_price_uah` from `hotel_calendar_prices`
sorted cheapest-first. The pre-Phase-2 stub returned NULL prices and
sorted by review score — that broke the "find best price" promise.

Business logic lives in `services.search_service.search_hotels`; this
router is a thin HTTP wrapper.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.search import PaginatedSearchResults
from src.services.search_service import search_hotels

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=PaginatedSearchResults)
async def search(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    check_in: date | None = Query(default=None),
    nights: int | None = Query(default=None, ge=1, le=30),
    meal_plan: str | None = Query(default=None, max_length=16),
    price_max: int | None = Query(default=None, ge=0),
    stars_min: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> PaginatedSearchResults:
    return await search_hotels(
        session,
        country=country,
        check_in=check_in,
        nights=nights,
        meal_plan=meal_plan,
        price_max=price_max,
        stars_min=stars_min,
        limit=limit,
        offset=offset,
    )
