"""Persistent refresh-queue logic for /api/hotels/{id}/refresh.

Audit #1.3 Medium "routers/hotels.py — 4 concerns": the router used to
mix CRUD + calendar + offers + the Redis-backed refresh queue. The
queue is the only part with non-trivial state machine (per-hotel lock,
queue cap, fallback on Redis blips), so it lives here as its own
service. The router becomes a thin HTTP-shape wrapper.
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.refresh_queue import (
    REFRESH_QUEUE_KEY,
    REFRESH_QUEUE_MAX_LEN,
    RefreshQueueFullError,
    RefreshQueueUnavailableError,
    push_refresh_job_with_cap,
)

from src.infra.logging import get_logger

log = get_logger(__name__)


# Stale-while-revalidate: refuse re-fetch if last refresh was less than this
# many seconds ago. Protects farvater from a hotel page being hammered by
# a flash crowd, and keeps response time predictable.
REFRESH_MIN_INTERVAL_S = 300  # 5 min

# Hard cap on the persistent queue so an attacker iterating hotel_ids cannot
# fill Redis (the queue is appendonly → persisted to disk). 200 is roughly
# 2× the size of a realistic burst from `snapshot_hot` (50 hot hotels)
# plus a small user trickle. Beyond that, reject 503 so the upstream rate
# limiter / human notices.
# The actual constant/script live in `shared.refresh_queue` because scheduler
# hot-priority jobs push into the same Redis list.


async def _await_if_needed(value: Awaitable[Any] | Any) -> Any:
    """redis.asyncio sometimes returns a coroutine, sometimes a value
    (depending on mock vs real client). One place to handle that."""
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(slots=True)
class EnqueueResult:
    queued: bool
    eta_seconds: int
    reason: str | None = None


class QueueFullError(RuntimeError):
    """Raised when REFRESH_QUEUE_MAX_LEN has been reached."""


class QueueUnavailableError(RuntimeError):
    """Raised when Redis is unreachable AFTER lock acquisition succeeded
    — caller drops the lock so the user can retry."""


async def _delete_refresh_lock(redis: Any, cache_key: str) -> None:
    try:
        await _await_if_needed(redis.delete(cache_key))
    except Exception as exc:  # noqa: BLE001
        log.warning("refresh.lock_release_failed", key=cache_key, error=str(exc))


async def enqueue_refresh(
    redis: Any,
    *,
    hotel_id: int,
    farvater_key: str,
    requested_nights: int | None = None,
    trigger: str = "user",
) -> EnqueueResult:
    """Try to enqueue a refresh job. Caller (the router) decides HTTP shape.

    Returns:
        EnqueueResult — `queued=True` on success, `queued=False` when
        deduped by the per-hotel lock (recent refresh exists).

    Raises:
        QueueFullError if the persistent queue is at the cap.
        QueueUnavailableError if Redis dies between lock acquire and
            enqueue (lock is rolled back inside).
    """
    cache_key = (
        f"refresh:hotel:{hotel_id}"
        if requested_nights is None
        else f"refresh:hotel:{hotel_id}:nights:{requested_nights}"
    )

    # Queue cap — hard ceiling on the persistent list. Reject well below
    # OOM so capacity exhaustion is visible in metrics instead of swap.
    try:
        qlen = await _await_if_needed(redis.llen(REFRESH_QUEUE_KEY))
        if qlen >= REFRESH_QUEUE_MAX_LEN:
            log.warning("refresh.queue_full", current=int(qlen), cap=REFRESH_QUEUE_MAX_LEN)
            raise QueueFullError(f"refresh queue full ({qlen}/{REFRESH_QUEUE_MAX_LEN})")
    except QueueFullError:
        raise
    except Exception as exc:  # noqa: BLE001 — Redis blip, let SET decide
        log.warning("refresh.queue_len_check_failed", error=str(exc))

    # SET NX EX — succeed only if no recent refresh for this hotel.
    try:
        acquired = await _await_if_needed(
            redis.set(cache_key, str(int(time.time())), nx=True, ex=REFRESH_MIN_INTERVAL_S)
        )
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("refresh.redis_unavailable", error=str(exc))
        acquired = True  # better stale fetch than nothing

    if not acquired:
        return EnqueueResult(queued=False, eta_seconds=0, reason="recently_refreshed")

    job: dict[str, Any] = {
        "hotel_id": hotel_id,
        "farvater_key": str(farvater_key),
        "requested_at": datetime.now(UTC).isoformat(),
        "trigger": trigger,
    }
    if requested_nights is not None:
        job["requested_nights"] = [requested_nights]
    job_json = json.dumps(job)

    try:
        await push_refresh_job_with_cap(redis, job_json)
    except RefreshQueueFullError as exc:
        log.warning("refresh.queue_full", current=exc.current, cap=exc.cap)
        await _delete_refresh_lock(redis, cache_key)
        raise QueueFullError(str(exc)) from exc
    except RefreshQueueUnavailableError as exc:
        await _delete_refresh_lock(redis, cache_key)
        raise QueueUnavailableError("refresh queue unavailable") from exc
    except Exception as exc:  # noqa: BLE001 — drop lock so user can retry
        log.error("refresh.enqueue_failed", hotel_id=hotel_id, error=str(exc))
        await _delete_refresh_lock(redis, cache_key)
        raise QueueUnavailableError("refresh queue unavailable") from exc

    return EnqueueResult(queued=True, eta_seconds=10)


__all__ = [
    "REFRESH_QUEUE_KEY",
    "REFRESH_QUEUE_MAX_LEN",
    "EnqueueResult",
    "QueueFullError",
    "QueueUnavailableError",
    "enqueue_refresh",
]
