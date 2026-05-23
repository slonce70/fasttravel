"""Hotel-related endpoints.

NOTE on slug vs id: external URLs use the canonical_slug (better for SEO).
Calendar and offers endpoints take the numeric id since they're typically
called from JS already in possession of the hotel row. The web app should
resolve slug -> id via GET /api/hotels/{slug} and reuse the id thereafter.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
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


@router.get("/{slug}", response_model=HotelOut)
async def get_hotel(slug: str, session: AsyncSession = Depends(get_db)) -> HotelOut:
    hotel = await session.scalar(
        select(Hotel).where(Hotel.canonical_slug == slug, Hotel.is_active.is_(True))
    )
    if hotel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    return HotelOut.model_validate(hotel)


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


async def _refresh_one_hotel(hotel_id: int, farvater_key: str) -> None:
    """Re-pull a single hotel from farvater's price-calendar endpoint and
    write to price_observations. Heavy import is kept *inside* the function
    so the API container doesn't need httpx until a refresh is requested
    (snapshot_farvater lives in apps/scheduler/, but the module is importable
    via the shared PYTHONPATH layout)."""
    try:
        # apps/scheduler is on PYTHONPATH thanks to docker volume mount in
        # docker-compose; for the API container without that mount we
        # gracefully degrade.
        from datetime import datetime, timedelta, UTC  # local to avoid cyclic
        import httpx, json
        from decimal import Decimal
        import re

        CHECK_IN_OFFSETS = [3, 14, 30, 45]
        async with httpx.AsyncClient(http2=True, timeout=20) as client:
            all_prices = []
            seen = set()
            for offset in CHECK_IN_OFFSETS:
                ci = (datetime.now(UTC).date() + timedelta(days=offset)).strftime("%d.%m.%Y")
                url = (
                    f"https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
                    f"?hotelKey={farvater_key}&adults=2&ages=0&meals=all&checkIn={ci}"
                )
                try:
                    r = await client.post(
                        url,
                        json={"dateShift": 7, "nights": [7, 10, 14], "townFroms": "all"},
                        headers={
                            "User-Agent": "FastTravel-LiveRefresh/1.0",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                    )
                except Exception as exc:
                    log.warning("refresh.fetch_failed",
                                hotel_id=hotel_id, offset=offset, error=str(exc))
                    continue
                if r.status_code != 200:
                    continue
                payload = r.json()
                if payload.get("statusCode") != 200:
                    continue
                for w in payload["data"]["items"]:
                    n = int(w["item"]["night"])
                    for d in w["item"]["dates"]:
                        sk = str(d.get("systemKey") or "")
                        if sk in seen:
                            continue
                        seen.add(sk)
                        try:
                            ci_d = datetime.strptime(d["date"], "%d.%m.%Y").date()
                        except Exception:
                            continue
                        all_prices.append({
                            "check_in": ci_d,
                            "nights": n,
                            "meal": (d.get("meal") or "OTHER")[:8],
                            "room": (d.get("room") or "")[:64],
                            "uah": int(d.get("priceUAH") or 0),
                            "usd": int(d.get("price") or 0),
                            "sk": sk,
                        })

        if not all_prices:
            log.info("refresh.no_prices", hotel_id=hotel_id, key=farvater_key)
            return

        # Insert + refresh MVs in one tx.
        from src.infra.db import async_session_factory
        async with async_session_factory() as db:
            op_row = (await db.execute(
                text("SELECT id FROM operators WHERE code = 'farvater'")
            )).first()
            if not op_row:
                log.error("refresh.no_farvater_operator")
                return
            op_id = op_row[0]
            observed_at = datetime.now(UTC)
            fx = (Decimal(all_prices[0]["uah"]) / Decimal(all_prices[0]["usd"])
                  if all_prices[0]["usd"] else Decimal("41.5"))

            deep_link_base = (await db.execute(
                text("""SELECT 'https://farvater.travel/uk/hotel/'
                          || lower(d.country_iso2) || '/'
                          || regexp_replace(h.canonical_slug, '^fv-[a-z]{2}-', '')
                          AS url
                        FROM hotels h
                        JOIN destinations d
                          ON d.id = h.destination_id AND d.parent_id IS NULL
                        WHERE h.id = :id"""),
                {"id": hotel_id},
            )).scalar() or "https://farvater.travel"

            payload = [
                {
                    "obs": observed_at, "h": hotel_id, "op": op_id,
                    "ci": p["check_in"], "n": p["nights"], "m": p["meal"], "rm": p["room"],
                    "ad": 2, "dc": "",
                    "puah": p["uah"], "porig": p["usd"], "cur": "USD", "fx": fx,
                    "dl": f"{deep_link_base}?systemKey={p['sk']}",
                    "raw": json.dumps({"systemKey": p["sk"],
                                        "source": "live_refresh"}),
                }
                for p in all_prices
            ]
            await db.execute(text("""
                INSERT INTO price_observations
                    (observed_at, hotel_id, operator_id, check_in, nights,
                     meal_plan, room_category, adults, departure_city,
                     price_uah, price_original, currency, fx_rate_to_uah,
                     deep_link, raw_payload)
                VALUES (:obs, :h, :op, :ci, :n, :m, :rm, :ad, :dc,
                        :puah, :porig, :cur, :fx, :dl, CAST(:raw AS jsonb))"""),
                payload,
            )
            # Refresh just the materialized views the hotel page reads.
            await db.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
            await db.execute(text("REFRESH MATERIALIZED VIEW hotel_calendar_prices"))
            await db.commit()

        log.info("refresh.done", hotel_id=hotel_id, inserted=len(all_prices))
    except Exception as exc:
        log.error("refresh.failed", hotel_id=hotel_id, error=str(exc))


@router.post("/{hotel_id}/refresh", response_model=RefreshResponse)
async def trigger_refresh(
    hotel_id: int,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """Stale-while-revalidate: queue a background live-price fetch.

    Returns immediately with `queued=true` so the client can render cached
    data without waiting. UI is expected to re-query the calendar after
    ~`eta_seconds`.

    Rate-limited per hotel via Redis. Two requests within 5 minutes for the
    same hotel collapse to one background job — the second caller gets
    `queued=false` and current cached data is already fresh enough.
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

    redis = get_redis()
    cache_key = f"refresh:hotel:{hotel_id}"
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

    background.add_task(_refresh_one_hotel, hotel_id, str(farvater_key))
    return RefreshResponse(queued=True, eta_seconds=10)
