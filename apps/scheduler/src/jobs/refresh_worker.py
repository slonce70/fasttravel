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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
from sqlalchemy import text

from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs._price_validation import parse_check_in, validate_price_row
from src.jobs.snapshot_farvater import CALENDAR_DATE_SHIFT_DAYS, NIGHTS

log = get_logger(__name__)


QUEUE_KEY = "refresh:queue"
BRPOP_TIMEOUT_S = 5
CHECK_IN_OFFSETS_DAYS = [0]
USER_AGENT = "FastTravel-RefreshWorker/1.0"


async def _fetch_hotel_prices(
    hotel_id: int,
    farvater_key: str,
    requested_nights: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Pull live price calendar with one broad Farvater request.
    Returns a list of normalised price rows ready for INSERT."""
    all_prices: list[dict[str, Any]] = []
    seen: set[str] = set()
    nights_to_fetch = requested_nights or NIGHTS
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
                    json={
                        "dateShift": CALENDAR_DATE_SHIFT_DAYS,
                        "nights": nights_to_fetch,
                        "townFroms": "all",
                    },
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except Exception as exc:  # noqa: BLE001 — single offset failure is recoverable
                log.warning(
                    "refresh_worker.fetch_failed",
                    hotel_id=hotel_id,
                    offset=offset,
                    error=str(exc),
                )
                continue
            if r.status_code != 200:
                continue
            try:
                payload = r.json()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "refresh_worker.bad_json",
                    hotel_id=hotel_id,
                    offset=offset,
                    error=str(exc),
                )
                continue
            if payload.get("statusCode") != 200:
                continue
            for w in payload["data"]["items"]:
                n = int(w["item"]["night"])
                for d in w["item"]["dates"]:
                    ok, reason = validate_price_row(d)
                    if not ok:
                        log.warning(
                            "refresh_worker.row_rejected",
                            hotel_id=hotel_id,
                            offset=offset,
                            reason=reason,
                        )
                        continue
                    sk = str(d.get("systemKey") or "")
                    if sk in seen:
                        continue
                    seen.add(sk)
                    ci_d = parse_check_in(d["date"])
                    if ci_d is None:
                        log.warning(
                            "refresh_worker.row_bad_date",
                            hotel_id=hotel_id,
                            offset=offset,
                            raw_date=d.get("date"),
                        )
                        continue
                    all_prices.append(
                        {
                            "check_in": ci_d,
                            "nights": n,
                            "meal": (d.get("meal") or "OTHER")[:8],
                            "room": (d.get("room") or "")[:64],
                            "uah": int(d.get("priceUAH") or 0),
                            "usd": int(d.get("price") or 0),
                            "sk": sk,
                            "raw": {
                                "systemKey": sk,
                                "source": "live_refresh",
                                "hotelKey": str(farvater_key),
                                "requestedCheckIn": ci_date.isoformat(),
                                "requestedDateShift": CALENDAR_DATE_SHIFT_DAYS,
                                "requestedNights": nights_to_fetch,
                                "calendarNight": n,
                                "offer": d,
                            },
                        }
                    )
    return all_prices


# 12h dedup — mirrors apps/scheduler/src/jobs/snapshot_farvater.py::_insert_prices.
# Without this, hot-priority + user refresh + nightly snapshot inside the same
# 12h window double-write every row and poison the price_baselines percentiles.
DEDUP_WINDOW_HOURS = 12

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


async def _persist_prices(hotel_id: int, prices: list[dict[str, Any]]) -> int:
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

        # Sprint 3.3 — shared helper, room_category in tuple.
        from src.jobs._dedup_window import existing_dedup_keys

        existing_keys = await existing_dedup_keys(db, hotel_id=hotel_id, operator_id=op_id)
        fresh = [
            p
            for p in prices
            if (
                p["check_in"],
                p["nights"],
                p["meal"],
                p.get("room") or "",
                p["uah"],
            )
            not in existing_keys
        ]
        if not fresh:
            log.info(
                "refresh_worker.all_deduped",
                hotel_id=hotel_id,
                seen_in_last_12h=len(prices),
            )
            return 0

        observed_at = datetime.now(UTC)
        fx = (
            Decimal(fresh[0]["uah"]) / Decimal(fresh[0]["usd"])
            if fresh[0]["usd"]
            else Decimal("41.5")
        )

        deep_link_base = (
            await db.execute(_DEEP_LINK_BASE_SQL, {"id": hotel_id})
        ).scalar() or "https://farvater.travel"

        payload = [
            {
                "obs": observed_at,
                "h": hotel_id,
                "op": op_id,
                "ci": p["check_in"],
                "n": p["nights"],
                "m": p["meal"],
                "rm": p["room"],
                "ad": 2,
                "dc": "",
                "puah": p["uah"],
                "porig": p["usd"],
                "cur": "USD",
                "fx": fx,
                # `?q=` is the farvater-internal booking-preselect param.
                # See snapshot_farvater for the discovery trail.
                "dl": f"{deep_link_base}?q={p['sk']}",
                "raw": json.dumps(p["raw"], default=str),
            }
            for p in fresh
        ]
        # ON CONFLICT DO NOTHING uses uq_price_obs_natural (migration 007).
        # The in-code 12h dedup above filters most repeats; this is the
        # last-line guard for the rare case when two writers (snapshot_farvater
        # + this worker) hit the same hotel at the same microsecond.
        await db.execute(
            text("""INSERT INTO price_observations
                      (observed_at, hotel_id, operator_id, check_in, nights,
                       meal_plan, room_category, adults, departure_city,
                       price_uah, price_original, currency, fx_rate_to_uah,
                       deep_link, raw_payload)
                    VALUES (:obs, :h, :op, :ci, :n, :m, :rm, :ad, :dc,
                            :puah, :porig, :cur, :fx, :dl, CAST(:raw AS jsonb))
                    ON CONFLICT
                      (hotel_id, operator_id, check_in, nights, meal_plan, observed_at)
                    DO NOTHING"""),
            payload,
        )
        # Hotel just produced fresh prices — bump the search-gate flags.
        await db.execute(
            text("""UPDATE hotels
                    SET last_priced_at = NOW(),
                        has_active_prices = TRUE
                    WHERE id = :id"""),
            {"id": hotel_id},
        )
        await db.commit()

    # REFRESH MV CONCURRENTLY — non-blocking for ongoing reads. UNIQUE
    # indexes on these MVs (migration 001 lines 330/357) make CONCURRENTLY
    # legal; non-CONCURRENT here would take an AccessExclusiveLock and
    # block every /api/hotels/{id}/calendar request, which is exactly the
    # DoS the security audit flagged. CONCURRENTLY can't run inside a tx
    # so we use a fresh AUTOCOMMIT connection. price_baselines stays out
    # — baselines need the hourly batch tick to recompute coherently.
    from src.infra.db import async_engine

    async with async_engine.connect() as raw_conn:
        ac = await raw_conn.execution_options(isolation_level="AUTOCOMMIT")
        try:
            await ac.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices"))
            await ac.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY hotel_calendar_prices"))
        except Exception as exc:  # noqa: BLE001 — MV un-primed → fall back to plain
            log.warning("refresh_worker.mv_refresh_fallback", error=str(exc))
            await ac.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
            await ac.execute(text("REFRESH MATERIALIZED VIEW hotel_calendar_prices"))

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
    requested_nights = job.get("requested_nights")
    if not hotel_id or not farvater_key:
        log.warning("refresh_worker.missing_fields", job=job)
        return
    if requested_nights is not None and (
        not isinstance(requested_nights, list)
        or not all(isinstance(n, int) and 1 <= n <= 30 for n in requested_nights)
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
