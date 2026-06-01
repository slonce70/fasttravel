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
      &sort=price_asc         optional; price_asc|price_desc|rating_desc|name_asc|stars_desc
      &limit=20 &offset=0

Returns hotels with a real `min_price_uah` from `hotel_calendar_prices`
sorted by the requested whitelisted order.

Business logic lives in `services.search_service.search_hotels`; this
router is a thin HTTP wrapper.

Audit #1.3 fix: the previous version doubled every Query() to also
accept `?amp;param=…` (HTML-escape leakage from some crawlers). That's
now handled by `src.infra.middleware.AmpQueryParamMiddleware` which
rewrites the raw query string before route matching. Router stays clean.
"""

from __future__ import annotations

from datetime import date
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.search import PaginatedSearchResults
from src.services.search_service import search_hotels

router = APIRouter(prefix="/api/search", tags=["search"])

_HTTP_422_INVALID_QUERY = HTTPStatus.UNPROCESSABLE_ENTITY
_MAX_KIDS = 6


def _parse_kids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise HTTPException(
                status_code=_HTTP_422_INVALID_QUERY,
                detail="kids must be a comma-separated list of ages 1..17",
            )
        try:
            age = int(value)
        except ValueError:
            raise HTTPException(
                status_code=_HTTP_422_INVALID_QUERY,
                detail="kids must be a comma-separated list of ages 1..17",
            ) from None
        if not 1 <= age <= 17:
            raise HTTPException(
                status_code=_HTTP_422_INVALID_QUERY,
                detail="kids ages must be between 1 and 17",
            )
        out.append(age)
        if len(out) > _MAX_KIDS:
            raise HTTPException(
                status_code=_HTTP_422_INVALID_QUERY,
                detail="kids must include no more than 6 ages",
            )
    return out


@router.get("", response_model=PaginatedSearchResults)
async def search(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    check_in: date | None = Query(default=None),
    check_in_min: date | None = Query(default=None),
    check_in_max: date | None = Query(default=None),
    nights: int | None = Query(default=None, ge=1, le=30),
    meal_plan: str | None = Query(default=None, max_length=16),
    price_max: int | None = Query(default=None, ge=0),
    stars_min: int | None = Query(default=None, ge=1, le=5),
    adults: int | None = Query(default=None, ge=1, le=9),
    kids: str | None = Query(default=None),
    sort: str | None = Query(default=None, max_length=32),
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_db),
) -> PaginatedSearchResults:
    # Date semantics (backward compatible):
    #  * `check_in` (or a lone legacy `check_in_min` with no max) → exact-day
    #    match, used by the web date-picker. The lone-`check_in_min` collapse
    #    preserves the original vestigial behaviour.
    #  * `check_in_min` AND `check_in_max` together → an inclusive range, used
    #    by the bot "when" buckets which advertise a window, not one day.
    has_range = check_in_min is not None and check_in_max is not None
    exact_check_in = check_in if has_range else (check_in or check_in_min)
    return await search_hotels(
        session,
        country=country,
        check_in=exact_check_in,
        check_in_min=check_in_min if has_range else None,
        check_in_max=check_in_max if has_range else None,
        nights=nights,
        meal_plan=meal_plan,
        price_max=price_max,
        stars_min=stars_min,
        adults=adults,
        kids=_parse_kids(kids),
        sort=sort or "price_asc",
        limit=limit or 20,
        offset=offset or 0,
    )
