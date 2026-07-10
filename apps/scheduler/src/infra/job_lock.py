"""Best-effort cross-job mutual exclusion via a Redis lock.

APScheduler's ``max_instances=1`` only dedupes runs of a single job id.
A workload registered under several ids (e.g. the sitemap ingest's
weekly / startup one-shot / daily-fallback triggers) needs an external
mutex, which this module provides:

- the lock value is a per-acquisition token, so a holder only ever
  renews or releases its own acquisition;
- a background task re-arms the TTL while the job runs, so multi-hour
  jobs keep the lock while a crashed holder frees it within one TTL;
- release happens in ``finally``, covering exceptions and cancellation.

The lock guards against duplicate load, not data corruption (the jobs
using it are idempotent), so Redis being unreachable fails open: the
job runs unlocked with a warning rather than being skipped.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from src.infra.cache import get_redis
from src.infra.logging import get_logger

log = get_logger(__name__)

DEFAULT_TTL_S = 15 * 60


async def _renew_periodically(
    redis: Any, key: str, token: str, ttl_s: int, every_s: float
) -> None:
    """Re-arm the lock TTL while the holder is still running.

    GET-then-EXPIRE is not atomic, but the race window (key expires and is
    re-acquired between the two commands) is milliseconds against a TTL of
    minutes — and renewal always runs with at least ``ttl_s - every_s`` of
    TTL remaining, so in practice the key cannot expire mid-renewal.
    """
    while True:
        await asyncio.sleep(every_s)
        try:
            holder = await redis.get(key)
            if holder != token:
                # TTL elapsed while renewal was stalled and another run took
                # the lock — stop renewing; the sibling owns the key now.
                log.warning("job_lock.lost", key=key)
                return
            await redis.expire(key, ttl_s)
        except Exception as exc:  # noqa: BLE001 — renewal is best-effort
            log.warning("job_lock.renew_failed", key=key, error=str(exc)[:200])


@asynccontextmanager
async def try_job_lock(
    key: str,
    *,
    ttl_s: int = DEFAULT_TTL_S,
    renew_every_s: float | None = None,
) -> AsyncIterator[bool]:
    """Try to take the named lock; yield whether it was acquired.

    Yields ``False`` (caller should log and skip its work) when another
    holder owns the lock. While held, the TTL is re-armed every
    ``renew_every_s`` seconds (default ``ttl_s / 3``).
    """
    redis = get_redis()
    token = uuid.uuid4().hex
    try:
        acquired = await redis.set(key, token, nx=True, ex=ttl_s)
    except Exception as exc:  # noqa: BLE001 — fail open, see module docstring
        log.warning("job_lock.unavailable", key=key, error=str(exc)[:200])
        yield True
        return

    if not acquired:
        yield False
        return

    renewer = asyncio.create_task(
        _renew_periodically(redis, key, token, ttl_s, renew_every_s or ttl_s / 3),
        name=f"job_lock_renew:{key}",
    )
    try:
        yield True
    finally:
        renewer.cancel()
        with suppress(asyncio.CancelledError):
            await renewer
        try:
            # Token-guarded delete. GET-then-DEL is not atomic, but the
            # renewer just kept the TTL fresh, so the key expiring (and
            # being re-acquired) between the two commands is not a
            # realistic window; a wrongly-surviving key expires via TTL.
            holder = await redis.get(key)
            if holder == token:
                await redis.delete(key)
        except Exception as exc:  # noqa: BLE001 — TTL is the backstop
            log.warning("job_lock.release_failed", key=key, error=str(exc)[:200])
