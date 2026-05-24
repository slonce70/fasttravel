"""Hotel search endpoint.

Contract (May 2026 — Phase 2 P0-1):

    GET /api/search
      ?country=tr             optional ISO2
      &check_in=2026-06-15    optional, ISO date — narrows to that day
      &nights=7               optional, picks min_<n>n column when 7/10/14
      &meal_plan=AI           optional, filters MV rows
      &price_max=50000        optional, UAH ceiling
      &stars_min=4            optional
      &adults=2&kids=7,9      optional; MVP returns 2-adult price-basis metadata
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


def _pick(primary, html_escaped):  # type: ignore[no-untyped-def]
    return primary if primary is not None else html_escaped


def _parse_kids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        try:
            age = int(part.strip())
        except ValueError:
            continue
        if 1 <= age <= 17:
            out.append(age)
    return out[:6]


@router.get("", response_model=PaginatedSearchResults)
async def search(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    amp_country: str | None = Query(default=None, alias="amp;country", min_length=2, max_length=2),
    check_in: date | None = Query(default=None),
    amp_check_in: date | None = Query(default=None, alias="amp;check_in"),
    nights: int | None = Query(default=None, ge=1, le=30),
    amp_nights: int | None = Query(default=None, alias="amp;nights", ge=1, le=30),
    meal_plan: str | None = Query(default=None, max_length=16),
    amp_meal_plan: str | None = Query(default=None, alias="amp;meal_plan", max_length=16),
    price_max: int | None = Query(default=None, ge=0),
    amp_price_max: int | None = Query(default=None, alias="amp;price_max", ge=0),
    stars_min: int | None = Query(default=None, ge=1, le=5),
    amp_stars_min: int | None = Query(default=None, alias="amp;stars_min", ge=1, le=5),
    adults: int | None = Query(default=None, ge=1, le=9),
    amp_adults: int | None = Query(default=None, alias="amp;adults", ge=1, le=9),
    kids: str | None = Query(default=None),
    amp_kids: str | None = Query(default=None, alias="amp;kids"),
    limit: int | None = Query(default=None, ge=1, le=100),
    amp_limit: int | None = Query(default=None, alias="amp;limit", ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    amp_offset: int | None = Query(default=None, alias="amp;offset", ge=0),
    session: AsyncSession = Depends(get_db),
) -> PaginatedSearchResults:
    return await search_hotels(
        session,
        country=_pick(country, amp_country),
        check_in=_pick(check_in, amp_check_in),
        nights=_pick(nights, amp_nights),
        meal_plan=_pick(meal_plan, amp_meal_plan),
        price_max=_pick(price_max, amp_price_max),
        stars_min=_pick(stars_min, amp_stars_min),
        adults=_pick(adults, amp_adults),
        kids=_parse_kids(_pick(kids, amp_kids)),
        limit=_pick(limit, amp_limit) or 20,
        offset=_pick(offset, amp_offset) or 0,
    )
