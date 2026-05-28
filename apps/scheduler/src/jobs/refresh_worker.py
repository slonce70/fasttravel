"""Persistent on-demand refresh worker.

Replaces FastAPI's in-process `BackgroundTasks` for `POST /api/hotels/
{id}/refresh`. The API now `LPUSH`es a refresh request onto
`refresh:queue`; this worker drains the list with `BRPOP` and runs the
same fetch+insert logic, so a refresh survives the API container
restarting and won't get dropped if the API is under load.

Two producers feed the queue:
  1. `POST /api/hotels/{id}/refresh`  → user-triggered single hotel
  2. `snapshot_hot` (hourly :30)      → top-N viewed hotels

Both push the same payload shape:
  {"hotel_id": int, "farvater_key": str, "requested_at": iso8601,
   "trigger": "user" | "hot_priority", "hot_count": int?}

The worker is one long-running asyncio task spawned by `src/main.py`
alongside `scheduler.start()`. On SIGTERM the main loop cancels it
and `BRPOP` unblocks via `CancelledError` → clean shutdown without
losing already-fetched jobs (the job is popped first, then run; if
we crash mid-fetch the user just retries).

Fetch logic mirrors the scheduled snapshot's product window: one broad
calendar request from today, 12h dedup, same MV refresh scope.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from datetime import date, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import text

from src.clients.farvater_calendar import CALENDAR_DATE_SHIFT_DAYS, NIGHTS, fetch_calendar
from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.services.hotel_upsert import HotelMeta
from src.services.materialized_views import refresh_price_views
from src.services.price_insert import PriceRow, insert_prices
from src.services.price_state import mark_priced

log = get_logger(__name__)


QUEUE_KEY = "refresh:queue"
BRPOP_TIMEOUT_S = 5
CHECK_IN_OFFSETS_DAYS = [0]
USER_AGENT = "FastTravel-RefreshWorker/1.0"


class _HttpxCalendarClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def post_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        json: dict[str, Any],
        extra_headers: dict[str, str],
    ) -> dict[str, Any]:
        response = await self._client.post(
            url,
            params=params,
            json=json,
            headers=extra_headers,
        )
        if response.status_code != 200:
            return {"statusCode": response.status_code}
        return cast(dict[str, Any], response.json())


async def _fetch_hotel_prices(
    hotel_id: int,
    farvater_key: str,
    requested_nights: list[int] | None = None,
) -> list[PriceRow]:
    """Pull live price calendar with one broad Farvater request.
    Returns a list of normalised price rows ready for INSERT."""
    all_prices: list[PriceRow] = []
    seen: set[str] = set()
    nights_to_fetch = requested_nights or NIGHTS
    async with httpx.AsyncClient(http2=True, timeout=20) as client:
        calendar_client = _HttpxCalendarClient(client)
        for offset in CHECK_IN_OFFSETS_DAYS:
            ci_date = date.today() + timedelta(days=offset)
            rows = await fetch_calendar(
                calendar_client,
                int(farvater_key),
                ci_date,
                date_shift_days=CALENDAR_DATE_SHIFT_DAYS,
                nights=nights_to_fetch,
                user_agent=USER_AGENT,
                payload_source="live_refresh",
                payload_hotel_key=str(farvater_key),
            )
            for row in rows:
                if row.system_key in seen:
                    continue
                seen.add(row.system_key)
                all_prices.append(row)
    return all_prices


_DEEP_LINK_BASE_SQL = text(
    """SELECT 'https://farvater.travel/uk/hotel/'
              || lower(COALESCE(parent.country_iso2, d.country_iso2)) || '/'
              || regexp_replace(h.canonical_slug, '^fv-[a-z]{2}-', '')
              AS url
        FROM hotels h
        JOIN destinations d ON d.id = h.destination_id
        LEFT JOIN destinations parent ON parent.id = d.parent_id
        WHERE h.id = :id"""
)


def _hotel_meta_from_deep_link_base(deep_link_base: str | None) -> HotelMeta:
    prefix = "https://farvater.travel"
    url_path = (deep_link_base or prefix).removeprefix(prefix)
    parts = url_path.strip("/").split("/")
    country_iso2 = parts[2].upper() if len(parts) >= 3 and parts[:2] == ["uk", "hotel"] else ""
    return HotelMeta(
        hotel_id=0,
        url_path=url_path,
        name="",
        country_iso2=country_iso2,
        photo_url="",
        description="",
        stars=None,
        photos=[],
        review_score=None,
        review_count=0,
    )


async def _persist_prices(hotel_id: int, prices: list[PriceRow]) -> int:
    """Write fetched prices + refresh hotel-page MVs. Returns rows inserted.

    Applies the same 12h dedup as `snapshot_farvater._insert_prices` — a
    user-triggered refresh that lands inside the scheduled snapshot's window
    must not double-count.
    """
    if not prices:
        return 0

    async with async_session_factory() as db:
        op_row = (
            await db.execute(text("SELECT id FROM operators WHERE code = 'farvater'"))
        ).first()
        if not op_row:
            log.error("refresh_worker.no_farvater_operator")
            return 0
        op_id = op_row[0]
        deep_link_base = (
            await db.execute(_DEEP_LINK_BASE_SQL, {"id": hotel_id})
        ).scalar() or "https://farvater.travel"
        hotel = _hotel_meta_from_deep_link_base(deep_link_base)
        inserted = await insert_prices(
            db,
            hotel_id,
            op_id,
            hotel,
            prices,
            country_iso2=hotel.country_iso2 or None,
        )
        if inserted == 0:
            log.info(
                "refresh_worker.all_deduped",
                hotel_id=hotel_id,
                seen_in_last_12h=len(prices),
            )
            return 0
        # Hotel just produced fresh prices — bump the search-gate flags.
        await mark_priced(db, hotel_id)
        await db.commit()

    await refresh_price_views(log_prefix="refresh_worker")

    return inserted


async def _process_job(raw: str) -> None:
    """Decode + execute a single queued refresh."""
    try:
        job = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — malformed job is non-fatal
        log.error("refresh_worker.bad_payload", raw=raw[:200], error=str(exc))
        return

    hotel_id = job.get("hotel_id")
    farvater_key = job.get("farvater_key")
    trigger = job.get("trigger", "user")
    requested_nights = job.get("requested_nights")
    if not hotel_id or not farvater_key:
        log.warning("refresh_worker.missing_fields", job=job)
        return
    if requested_nights is not None and (
        not isinstance(requested_nights, list)
        or not all(type(n) is int and 1 <= n <= 30 for n in requested_nights)
    ):
        log.warning("refresh_worker.invalid_requested_nights", job=job)
        return

    try:
        prices = await _fetch_hotel_prices(
            int(hotel_id),
            str(farvater_key),
            requested_nights=requested_nights,
        )
        inserted = await _persist_prices(int(hotel_id), prices)
        log.info(
            "refresh_worker.done",
            hotel_id=hotel_id,
            trigger=trigger,
            fetched=len(prices),
            inserted=inserted,
        )
    except Exception as exc:  # noqa: BLE001 — log+continue, never crash the worker
        log.error(
            "refresh_worker.failed",
            hotel_id=hotel_id,
            trigger=trigger,
            error=str(exc),
        )


async def refresh_worker_loop() -> None:
    """Long-running BRPOP loop. Cancelled cleanly on SIGTERM by main.py."""
    redis = get_redis()
    log.info("refresh_worker.started", queue=QUEUE_KEY, brpop_timeout_s=BRPOP_TIMEOUT_S)
    try:
        while True:
            try:
                item = await cast(
                    Awaitable[list[Any] | None],
                    redis.brpop([QUEUE_KEY], timeout=BRPOP_TIMEOUT_S),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — Redis blip shouldn't kill worker
                log.warning("refresh_worker.brpop_failed", error=str(exc))
                # Back off briefly so a Redis outage doesn't busy-loop.
                await asyncio.sleep(1.0)
                continue
            if item is None:
                # Timeout — no work this window. Loop back to BRPOP, which
                # also gives the cancellation a chance to fire.
                continue
            # `item` is (queue_name, payload); decode_responses=True → str.
            _queue_name, raw = item
            await _process_job(raw)
    except asyncio.CancelledError:
        log.info("refresh_worker.cancelled")
        raise


if __name__ == "__main__":
    asyncio.run(refresh_worker_loop())
