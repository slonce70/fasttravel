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

Fetch logic mirrors the original `_refresh_one_hotel` in
`apps/api/src/routers/hotels.py` 1:1 — same offsets, same dedup
behaviour (none — P0-6 will add 12h dedup at both call sites in
one pass), same MV refresh scope.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import text

from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


QUEUE_KEY = "refresh:queue"
BRPOP_TIMEOUT_S = 5
CHECK_IN_OFFSETS_DAYS = [3, 14, 30, 45]
NIGHTS = [7, 10, 14]
USER_AGENT = "FastTravel-RefreshWorker/1.0"


async def _fetch_hotel_prices(hotel_id: int, farvater_key: str) -> list[dict]:
    """Pull live price calendar across the standard check-in offsets.
    Returns a list of normalised price rows ready for INSERT."""
    all_prices: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(http2=True, timeout=20) as client:
        for offset in CHECK_IN_OFFSETS_DAYS:
            ci_date = date.today() + timedelta(days=offset)
            ci = ci_date.strftime("%d.%m.%Y")
            url = (
                f"https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
                f"?hotelKey={farvater_key}&adults=2&ages=0&meals=all&checkIn={ci}"
            )
            try:
                r = await client.post(
                    url,
                    json={"dateShift": 7, "nights": NIGHTS, "townFroms": "all"},
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except Exception as exc:  # noqa: BLE001 — single offset failure is recoverable
                log.warning(
                    "refresh_worker.fetch_failed",
                    hotel_id=hotel_id, offset=offset, error=str(exc),
                )
                continue
            if r.status_code != 200:
                continue
            try:
                payload = r.json()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "refresh_worker.bad_json",
                    hotel_id=hotel_id, offset=offset, error=str(exc),
                )
                continue
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
    return all_prices


async def _persist_prices(hotel_id: int, prices: list[dict]) -> int:
    """Write fetched prices + refresh hotel-page MVs. Returns rows inserted."""
    if not prices:
        return 0

    async with async_session_factory() as db:
        op_row = (await db.execute(
            text("SELECT id FROM operators WHERE code = 'farvater'")
        )).first()
        if not op_row:
            log.error("refresh_worker.no_farvater_operator")
            return 0
        op_id = op_row[0]

        observed_at = datetime.now(UTC)
        fx = (Decimal(prices[0]["uah"]) / Decimal(prices[0]["usd"])
              if prices[0]["usd"] else Decimal("41.5"))

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
                "raw": json.dumps({
                    "systemKey": p["sk"],
                    "source": "live_refresh",
                }),
            }
            for p in prices
        ]
        await db.execute(
            text("""INSERT INTO price_observations
                      (observed_at, hotel_id, operator_id, check_in, nights,
                       meal_plan, room_category, adults, departure_city,
                       price_uah, price_original, currency, fx_rate_to_uah,
                       deep_link, raw_payload)
                    VALUES (:obs, :h, :op, :ci, :n, :m, :rm, :ad, :dc,
                            :puah, :porig, :cur, :fx, :dl, CAST(:raw AS jsonb))"""),
            payload,
        )
        # Same MV scope as the original API-side refresh — only the views
        # the hotel page actually reads. price_baselines stays out;
        # baselines need the hourly batch tick to recompute coherently.
        await db.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
        await db.execute(text("REFRESH MATERIALIZED VIEW hotel_calendar_prices"))
        # Hotel just produced fresh prices — bump the search-gate flags.
        await db.execute(
            text("""UPDATE hotels
                    SET last_priced_at = NOW(),
                        has_active_prices = TRUE
                    WHERE id = :id"""),
            {"id": hotel_id},
        )
        await db.commit()
    return len(payload)


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
    if not hotel_id or not farvater_key:
        log.warning("refresh_worker.missing_fields", job=job)
        return

    try:
        prices = await _fetch_hotel_prices(int(hotel_id), str(farvater_key))
        inserted = await _persist_prices(int(hotel_id), prices)
        log.info(
            "refresh_worker.done",
            hotel_id=hotel_id, trigger=trigger,
            fetched=len(prices), inserted=inserted,
        )
    except Exception as exc:  # noqa: BLE001 — log+continue, never crash the worker
        log.error(
            "refresh_worker.failed",
            hotel_id=hotel_id, trigger=trigger, error=str(exc),
        )


async def refresh_worker_loop() -> None:
    """Long-running BRPOP loop. Cancelled cleanly on SIGTERM by main.py."""
    redis = get_redis()
    log.info("refresh_worker.started", queue=QUEUE_KEY,
             brpop_timeout_s=BRPOP_TIMEOUT_S)
    try:
        while True:
            try:
                item = await redis.brpop(QUEUE_KEY, timeout=BRPOP_TIMEOUT_S)
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
