"""Hotel-related endpoints.

NOTE on slug vs id: external URLs use the canonical_slug (better for SEO).
Calendar and offers endpoints take the numeric id since they're typically
called from JS already in possession of the hotel row. The web app should
resolve slug -> id via GET /api/hotels/{slug} and reuse the id thereafter.

Audit #1.3 cleanup:
  * "GET /api/hotels/{id}/calendar mutates Redis state" — the GET handler
    used to fire-and-forget a `hot:hotel:{id}` INCR every read. That
    broke HTTP semantics (GETs aren't supposed to mutate), prevented
    CDN caching, and grew an unbounded module-level task set on Redis
    outages. The hot-priority signal now comes from a POST /hot-ping
    endpoint clients call deliberately (or — easier path — the
    scheduler reads access logs / API metrics for the same signal).
  * "routers/hotels.py 4 concerns" — the persistent refresh queue
    moved to services/refresh_queue.py. The router is now a thin
    HTTP-shape wrapper.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.infra.cache import get_redis
from src.infra.limiter import limiter
from src.infra.logging import get_logger
from src.models import Hotel, HotelSlugAlias
from src.schemas.calendar import CalendarDay, OfferOut
from src.schemas.hotel import HotelOut
from src.services.calendar_service import get_calendar, get_offers
from src.services.refresh_queue import (
    REFRESH_QUEUE_KEY,
    EnqueueResult,
    QueueFullError,
    QueueUnavailableError,
    enqueue_refresh,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api/hotels", tags=["hotels"])


@router.get("/{slug}", response_model=HotelOut)
async def get_hotel(slug: str, session: AsyncSession = Depends(get_db)) -> HotelOut:
    hotel = await session.scalar(
        select(Hotel).where(Hotel.canonical_slug == slug, Hotel.is_active.is_(True))
    )
    if hotel is None:
        hotel = await session.scalar(
            select(Hotel)
            .join(HotelSlugAlias, HotelSlugAlias.hotel_id == Hotel.id)
            .where(HotelSlugAlias.source_slug == slug, Hotel.is_active.is_(True))
        )
    if hotel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    return HotelOut.model_validate(hotel)


@router.get("/{hotel_id}/calendar", response_model=list[CalendarDay])
async def hotel_calendar(
    hotel_id: int,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    # `?meal=AI` or `?meal_plan=AI` narrows the heatmap to one meal-plan; omitted = MIN
    # across meal plans (backwards-compatible). See migration 002 + the
    # docstring in calendar_service.get_calendar for the dual-shape rules.
    meal: str | None = Query(default=None, max_length=16),
    meal_plan: str | None = Query(default=None, max_length=16),
    nights: int | None = Query(default=None, ge=1, le=30),
    session: AsyncSession = Depends(get_db),
) -> list[CalendarDay]:
    if to_date < from_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="`to` must be >= `from`")
    if (to_date - from_date).days > 180:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="window too wide (max 180 days)")
    # Read-only — no Redis mutation here. The previous fire-and-forget
    # `hot:hotel:{id}` INCR violated GET semantics and broke CDN caching.
    # The hot-priority signal now comes from the explicit POST below.
    effective_meal_plan = meal_plan or meal
    return await get_calendar(
        session,
        hotel_id,
        from_date,
        to_date,
        meal_plan=effective_meal_plan,
        nights=nights,
    )


@router.get("/{hotel_id}/offers", response_model=list[OfferOut])
async def hotel_offers(
    hotel_id: int,
    check_in: date = Query(alias="date"),
    nights: int | None = Query(default=None, ge=1, le=30),
    meal: str | None = Query(default=None, max_length=16),
    session: AsyncSession = Depends(get_db),
) -> list[OfferOut]:
    return await get_offers(session, hotel_id, check_in, nights=nights, meal_plan=meal)


# Hot-priority signal. Each calendar view bumps `hot:hotel:{id}` with a
# 24h TTL — the scheduler's `snapshot_hot` job reads these counters
# hourly to decide which hotels to re-fetch ahead of schedule. TTL keeps
# the set self-cleaning so stale interest decays naturally.
HOT_KEY_TTL_S = 86400


@router.post("/{hotel_id}/hot-ping", response_class=Response, status_code=204)
@limiter.limit("60/minute")
async def hotel_hot_ping(
    request: Request,
    hotel_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Client-driven hot-priority signal. Replaces the fire-and-forget
    INCR that used to live in GET /calendar.

    Frontend calls this whenever a user actually views a hotel page so
    the scheduler's `snapshot_hot` job re-fetches popular hotels ahead
    of schedule. Rate-limited per IP so a bot scraping IDs can't bias
    the heat map.
    """
    # Verify the hotel exists (don't pollute the heat map with random IDs).
    exists = await session.scalar(
        select(Hotel.id).where(Hotel.id == hotel_id, Hotel.is_active.is_(True))
    )
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    redis = get_redis()
    key = f"hot:hotel:{hotel_id}"
    try:
        # Synchronous, awaited: keeps the request open ~1 ms longer but
        # eliminates the unbounded module-level task set that the
        # previous fire-and-forget needed to survive GC.
        await redis.incr(key)
        await redis.expire(key, HOT_KEY_TTL_S)
    except Exception as exc:  # noqa: BLE001 — telemetry only
        log.debug("hot_counter.bump_failed", hotel_id=hotel_id, error=str(exc))
    # 204 No Content — explicit Response so FastAPI doesn't try to
    # JSON-serialise None into a body.
    return Response(status_code=204)


class RefreshResponse(BaseModel):
    """`POST /api/hotels/{id}/refresh` reply.

    `queued=true`  → a background task is fetching live prices from farvater
    `queued=false` → recent refresh exists; the client already has fresh data
    `eta_seconds`  → optimistic time until UI should re-query the calendar
    """

    queued: bool
    eta_seconds: int
    reason: str | None = None


@router.post("/{hotel_id}/refresh", response_model=RefreshResponse)
@limiter.limit("10/hour")
async def trigger_refresh(
    request: Request,
    hotel_id: int,
    nights: int | None = Query(default=None, ge=1, le=30),
    session: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """Stale-while-revalidate: enqueue a background live-price fetch.

    Rate-limited to 10 requests per IP per hour (slowapi decorator) —
    the `request` argument is required by slowapi to extract the
    client IP. Hotel-level dedup (5-min lock) plus the queue cap of
    200 live in `services.refresh_queue`.
    """
    # Sanity check the hotel exists, and grab its farvater mapping if any.
    row = (
        await session.execute(
            text("""SELECT h.id, m.external_id
                FROM hotels h
                LEFT JOIN hotel_operator_mapping m
                       ON m.hotel_id = h.id
                      AND m.operator_id =
                          (SELECT id FROM operators WHERE code = 'farvater')
                WHERE h.id = :id AND h.is_active"""),
            {"id": hotel_id},
        )
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    farvater_key = row[1]
    if not farvater_key:
        # Synthetic hotel — no farvater mapping. Nothing to refresh; pretend
        # we're up-to-date so the UI banner disappears quickly.
        return RefreshResponse(queued=False, eta_seconds=0, reason="hotel_not_mapped_to_farvater")
    # SSRF defence-in-depth: the mapping is set by our own scraper from
    # `\d+` regex, but assert here so a future change to the mapping path
    # can't smuggle a non-numeric key into our outbound URL.
    if not str(farvater_key).isdigit():
        log.error(
            "refresh.invalid_farvater_key",
            hotel_id=hotel_id,
            key=str(farvater_key)[:32],
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="hotel mapping invalid")

    redis = get_redis()
    try:
        result: EnqueueResult = await enqueue_refresh(
            redis,
            hotel_id=hotel_id,
            farvater_key=str(farvater_key),
            requested_nights=nights,
            trigger="user",
        )
    except QueueFullError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refresh queue full, try later",
        ) from exc
    except QueueUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refresh queue unavailable",
        ) from exc

    return RefreshResponse(
        queued=result.queued, eta_seconds=result.eta_seconds, reason=result.reason
    )


__all__ = ["REFRESH_QUEUE_KEY", "router"]
