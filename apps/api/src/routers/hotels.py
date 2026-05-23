"""Hotel-related endpoints.

NOTE on slug vs id: external URLs use the canonical_slug (better for SEO).
Calendar and offers endpoints take the numeric id since they're typically
called from JS already in possession of the hotel row. The web app should
resolve slug -> id via GET /api/hotels/{slug} and reuse the id thereafter.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.infra.cache import get_redis
from src.infra.logging import get_logger
from src.models import Hotel
from src.schemas.calendar import CalendarDay, OfferOut
from src.schemas.hotel import HotelOut
from src.services.calendar_service import get_calendar, get_offers

log = get_logger(__name__)
router = APIRouter(prefix="/api/hotels", tags=["hotels"])

# Stale-while-revalidate: refuse re-fetch if last refresh was less than this
# many seconds ago. Protects farvater from a hotel page being hammered by
# a flash crowd, and keeps response time predictable.
REFRESH_MIN_INTERVAL_S = 300  # 5 min

# Hot-priority signal. Each calendar view bumps `hot:hotel:{id}` with a
# 24h TTL — the scheduler's `snapshot_hot` job reads these counters
# hourly to decide which hotels to re-fetch ahead of schedule. TTL keeps
# the set self-cleaning so stale interest decays naturally.
HOT_KEY_TTL_S = 86400
# Persistent refresh queue. `POST /refresh` LPUSHes here; the scheduler's
# `refresh_worker_loop` BRPOPs. Survives API restarts (which FastAPI's
# `BackgroundTasks` did not).
REFRESH_QUEUE_KEY = "refresh:queue"
# Hard cap on the persistent queue so an attacker iterating hotel_ids can't
# fill Redis (the queue is appendonly → persisted to disk). 200 is roughly
# 2× the size of a realistic burst from `snapshot_hot` (50 hot hotels)
# plus a small user trickle. Beyond that, reject 503 so the upstream rate
# limiter / human notices.
REFRESH_QUEUE_MAX_LEN = 200

# Keep strong references to fire-and-forget tasks so the event loop's weak
# ref doesn't garbage-collect them mid-flight. CPython has bitten plenty
# of people with this pattern.
_pending_tasks: set[asyncio.Task] = set()


def _spawn_fire_and_forget(coro) -> None:
    t = asyncio.create_task(coro)
    _pending_tasks.add(t)
    t.add_done_callback(_pending_tasks.discard)


@router.get("/{slug}", response_model=HotelOut)
async def get_hotel(slug: str, session: AsyncSession = Depends(get_db)) -> HotelOut:
    hotel = await session.scalar(
        select(Hotel).where(Hotel.canonical_slug == slug, Hotel.is_active.is_(True))
    )
    if hotel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    return HotelOut.model_validate(hotel)


async def _bump_hot_counter(hotel_id: int) -> None:
    """Fire-and-forget INCR on `hot:hotel:{id}` with a sliding 24h TTL.

    Failures are swallowed — Redis being down must not break the calendar
    response. The hot-priority pass is best-effort by design.
    """
    try:
        redis = get_redis()
        key = f"hot:hotel:{hotel_id}"
        await redis.incr(key)
        await redis.expire(key, HOT_KEY_TTL_S)
    except Exception as exc:  # noqa: BLE001 — telemetry only
        log.debug("hot_counter.bump_failed", hotel_id=hotel_id, error=str(exc))


@router.get("/{hotel_id}/calendar", response_model=list[CalendarDay])
async def hotel_calendar(
    hotel_id: int,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    # `?meal=AI` narrows the heatmap to one meal-plan; omitted = MIN
    # across meal plans (backwards-compatible). See migration 002 + the
    # docstring in calendar_service.get_calendar for the dual-shape rules.
    meal_plan: str | None = Query(default=None, alias="meal", max_length=16),
    session: AsyncSession = Depends(get_db),
) -> list[CalendarDay]:
    if to_date < from_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="`to` must be >= `from`")
    if (to_date - from_date).days > 180:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="window too wide (max 180 days)")
    # Record interest *before* the read so a slow DB query still earns
    # the hotel its hot-priority score for the next sweep. Held in a
    # module-level set — see `_spawn_fire_and_forget` for the gc-safety
    # rationale.
    _spawn_fire_and_forget(_bump_hot_counter(hotel_id))
    return await get_calendar(session, hotel_id, from_date, to_date, meal_plan=meal_plan)


@router.get("/{hotel_id}/offers", response_model=list[OfferOut])
async def hotel_offers(
    hotel_id: int,
    check_in: date = Query(alias="date"),
    nights: int | None = Query(default=None, ge=1, le=30),
    meal: str | None = Query(default=None, max_length=16),
    session: AsyncSession = Depends(get_db),
) -> list[OfferOut]:
    return await get_offers(session, hotel_id, check_in, nights=nights, meal_plan=meal)


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
async def trigger_refresh(
    hotel_id: int,
    session: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """Stale-while-revalidate: enqueue a background live-price fetch.

    Returns immediately with `queued=true` so the client can render cached
    data without waiting. UI is expected to re-query the calendar after
    ~`eta_seconds`.

    Rate-limited per hotel via Redis. Two requests within 5 minutes for the
    same hotel collapse to one queued job — the second caller gets
    `queued=false` and current cached data is already fresh enough.

    Job is pushed onto the persistent Redis list `refresh:queue` and
    drained by `apps/scheduler/src/jobs/refresh_worker.py` — so a
    refresh survives the API process restarting (unlike the previous
    in-process `BackgroundTasks` implementation).
    """
    # Sanity check the hotel exists, and grab its farvater mapping if any.
    row = (await session.execute(
        text("""SELECT h.id, m.external_id
                FROM hotels h
                LEFT JOIN hotel_operator_mapping m
                       ON m.hotel_id = h.id
                      AND m.operator_id =
                          (SELECT id FROM operators WHERE code = 'farvater')
                WHERE h.id = :id AND h.is_active"""),
        {"id": hotel_id},
    )).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    farvater_key = row[1]
    if not farvater_key:
        # Synthetic hotel — no farvater mapping. Nothing to refresh; pretend
        # we're up-to-date so the UI banner disappears quickly.
        return RefreshResponse(queued=False, eta_seconds=0,
                                reason="hotel_not_mapped_to_farvater")
    # SSRF defence-in-depth: the mapping is set by our own scraper from
    # `\d+` regex, but assert here so a future change to the mapping path
    # can't smuggle a non-numeric key into our outbound URL.
    if not str(farvater_key).isdigit():
        log.error("refresh.invalid_farvater_key",
                  hotel_id=hotel_id, key=str(farvater_key)[:32])
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                             detail="hotel mapping invalid")

    redis = get_redis()
    cache_key = f"refresh:hotel:{hotel_id}"

    # Queue cap — hard ceiling on the persistent list so an attacker
    # rotating hotel_ids can't flood Redis (the list is appendonly →
    # persisted to disk). Reject 503 well below the OOM threshold so
    # capacity exhaustion is visible in metrics instead of swap thrashing.
    try:
        qlen = await redis.llen(REFRESH_QUEUE_KEY)
        if qlen >= REFRESH_QUEUE_MAX_LEN:
            log.warning("refresh.queue_full", current=int(qlen),
                        cap=REFRESH_QUEUE_MAX_LEN)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="refresh queue full, try later",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — Redis blip, let lock SET below decide
        log.warning("refresh.queue_len_check_failed", error=str(exc))
    try:
        # SET NX EX — succeed only if no recent refresh for this hotel.
        acquired = await redis.set(cache_key, str(int(time.time())),
                                    nx=True, ex=REFRESH_MIN_INTERVAL_S)
    except Exception as exc:
        log.warning("refresh.redis_unavailable", error=str(exc))
        acquired = True  # fail-open — better stale read of farvater than nothing

    if not acquired:
        return RefreshResponse(queued=False, eta_seconds=0,
                                reason="recently_refreshed")

    payload = json.dumps({
        "hotel_id": hotel_id,
        "farvater_key": str(farvater_key),
        "requested_at": datetime.now(UTC).isoformat(),
        "trigger": "user",
    })
    try:
        await redis.lpush(REFRESH_QUEUE_KEY, payload)
    except Exception as exc:  # noqa: BLE001 — drop lock so user can retry
        log.error("refresh.enqueue_failed", hotel_id=hotel_id, error=str(exc))
        try:
            await redis.delete(cache_key)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refresh queue unavailable",
        ) from exc

    return RefreshResponse(queued=True, eta_seconds=10)
