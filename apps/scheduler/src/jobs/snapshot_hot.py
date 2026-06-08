"""Hot-priority refresh — re-fetch the top N most-viewed hotels every hour.

`apps/api/src/routers/hotels.py::hotel_calendar` fires
`INCR hot:hotel:{id} EX 86400` on every calendar view. This job reads
those counters once an hour, picks the top 50, and pushes them onto
the shared `refresh:queue` Redis list. `refresh_worker.py` (also in
the scheduler container) drains the queue with the same fetch+insert
logic the on-demand `POST /api/hotels/{id}/refresh` uses.

Why share the queue with on-demand instead of running the fetch
inline? Two reasons:
  1. Single code path for price refresh — easier to reason about
     rate limits, retries, and observability.
  2. The worker already serialises via BRPOP, so we don't hammer
     farvater when a user-driven burst overlaps with the hourly tick.

Cron: hourly at :30 (intentionally off-cycle from refresh_views :05
and detect_deals :10 so a slow run never starves them). No catch-up
on missed windows — `coalesce=True` in scheduler defaults takes care
of that.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import text

from shared.refresh_queue import (
    REFRESH_QUEUE_KEY,
    RefreshQueueFullError,
    legacy_custom_nights_lock_pattern,
    push_refresh_job_with_cap,
    refresh_base_lock_key,
)
from shared.refresh_queue import (
    REFRESH_QUEUE_MAX_LEN as SHARED_REFRESH_QUEUE_MAX_LEN,
)
from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


HOT_KEY_PREFIX = "hot:hotel:"
QUEUE_KEY = REFRESH_QUEUE_KEY
REFRESH_QUEUE_MAX_LEN = SHARED_REFRESH_QUEUE_MAX_LEN
TOP_N = 50
OPERATOR_CODE = "farvater"
# Conservative SCAN batch — big enough that ~few-hundred hot keys
# resolve in one round-trip, small enough to keep each MATCH iteration
# under a millisecond on a busy Redis.
SCAN_COUNT = 200


def _parse_legacy_custom_nights_lock_hotel_id(key: object) -> int | None:
    if isinstance(key, bytes):
        key = key.decode()
    if not isinstance(key, str):
        return None

    parts = key.split(":")
    if len(parts) != 5 or parts[0] != "refresh" or parts[1] != "hotel" or parts[3] != "nights":
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


async def _resolve_farvater_keys(hotel_ids: list[int]) -> dict[int, str]:
    """Return {hotel_id: farvater external_id} for hotels mapped to the
    farvater operator. Hotels without a mapping (synthetic seeds) are
    omitted — we can't refresh what we can't fetch.
    """
    if not hotel_ids:
        return {}
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text("""SELECT m.hotel_id, m.external_id
                    FROM hotel_operator_mapping m
                    JOIN operators o ON o.id = m.operator_id
                    WHERE o.code = :op
                      AND m.hotel_id = ANY(:ids)"""),
                {"op": OPERATOR_CODE, "ids": hotel_ids},
            )
        ).all()
    return {row[0]: row[1] for row in rows}


async def snapshot_hot(*, top_n: int = TOP_N) -> int:
    """Scan `hot:hotel:*` counters, enqueue top-N to refresh queue.

    Returns the number of refresh jobs queued. Idempotent within a
    tick: if the queue already holds a refresh for a hotel, the
    worker's per-hotel dedup (inherits from the existing 5-min
    Redis lock in `POST /refresh`) keeps duplicates harmless.
    """
    redis = get_redis()

    # SCAN MATCH replaces the old KEYS — KEYS is O(N) blocking across the
    # whole Redis keyspace and locks every other command until it returns.
    # That's fine at a few hundred keys but becomes a latency problem once
    # the hot set grows past ~10k. SCAN is non-blocking, cursor-based, and
    # the per-iteration cost is bounded by COUNT.
    keys: list[str] = []
    async for k in redis.scan_iter(match=f"{HOT_KEY_PREFIX}*", count=SCAN_COUNT):
        keys.append(k)
    if not keys:
        log.info("snapshot_hot.empty", note="no hot counters set this window")
        return 0

    # decode_responses=True (see apps/scheduler/src/infra/cache.py) means
    # both keys and values come back as strings — no .decode() needed.
    # MGET in one round-trip beats per-key GET when N grows.
    raw_values = await redis.mget(keys)
    pairs: list[tuple[int, int]] = []
    for k, raw in zip(keys, raw_values, strict=False):
        try:
            count = int(raw or 0)
        except (TypeError, ValueError):
            continue
        try:
            hotel_id = int(k.split(":")[-1])
        except (TypeError, ValueError):
            log.warning("snapshot_hot.bad_key", key=k)
            continue
        pairs.append((hotel_id, count))

    if not pairs:
        log.info("snapshot_hot.empty", note="all hot counters were unparseable")
        return 0

    pairs.sort(key=lambda x: -x[1])
    top = pairs[:top_n]
    top_ids = [hid for hid, _ in top]

    mapping = await _resolve_farvater_keys(top_ids)
    if not mapping:
        log.info("snapshot_hot.no_mappings", top=len(top_ids))
        return 0

    # Batch base-lock checks for current API refreshes, then run one bounded
    # SCAN for legacy custom-night locks left by pre-unification producers.
    pipe = redis.pipeline()
    for hid in mapping:
        pipe.exists(refresh_base_lock_key(hid))
    base_lock_results = await pipe.execute()

    locked = {
        hid for hid, exists in zip(mapping.keys(), base_lock_results, strict=False) if exists
    }
    mapped_ids = set(mapping)
    async for key in redis.scan_iter(
        match=legacy_custom_nights_lock_pattern(),
        count=SCAN_COUNT,
    ):
        legacy_hotel_id = _parse_legacy_custom_nights_lock_hotel_id(key)
        if legacy_hotel_id is not None and legacy_hotel_id in mapped_ids:
            locked.add(legacy_hotel_id)

    now_iso = datetime.now(UTC).isoformat()
    queued = 0
    skipped_locked = 0
    for hotel_id, count in top:
        farvater_key = mapping.get(hotel_id)
        if not farvater_key:
            continue
        if hotel_id in locked:
            skipped_locked += 1
            continue
        payload = json.dumps(
            {
                "hotel_id": hotel_id,
                "farvater_key": str(farvater_key),
                "requested_at": now_iso,
                "trigger": "hot_priority",
                "hot_count": count,
            }
        )
        try:
            await push_refresh_job_with_cap(redis, payload)
        except RefreshQueueFullError as exc:
            log.warning(
                "snapshot_hot.queue_full",
                current=exc.current,
                cap=exc.cap,
                skipped_remaining=len(top) - queued,
            )
            break
        queued += 1

    # Sprint 2.2 — REFRESH_QUEUE_DEPTH was declared in metrics.py from
    # the start but never updated. Stamp it at the tail of every
    # snapshot_hot tick so the dashboard reflects current depth (the
    # refresh_worker drains continuously, so this gauge moves between
    # ticks too — best-effort snapshot is good enough for alerting).
    try:
        from src.infra.metrics import REFRESH_QUEUE_DEPTH

        REFRESH_QUEUE_DEPTH.set(await cast(Awaitable[int], redis.llen(QUEUE_KEY)))
    except Exception:  # noqa: BLE001
        log.exception("snapshot_hot.metrics_set_failed")

    log.info(
        "snapshot_hot.queued",
        candidates=len(pairs),
        top=len(top),
        queued=queued,
        skipped_locked=skipped_locked,
        queue=QUEUE_KEY,
    )
    return queued


if __name__ == "__main__":
    import asyncio

    asyncio.run(snapshot_hot())
