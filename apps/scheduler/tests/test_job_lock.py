"""Tests for the cross-job Redis lock helper (src.infra.job_lock).

The lock exists because APScheduler's max_instances=1 only dedupes runs
of a single job id — jobs registered under several ids (sitemap ingest:
weekly / startup one-shot / daily fallback) need an external mutex.
Contract under test:

  1. Second holder is rejected while the first is alive.
  2. The lock is always released — normal exit, exception, cancellation.
  3. The TTL is renewed so runs longer than one TTL keep the lock.
  4. Redis being unreachable fails open (job runs unlocked).
  5. Release is token-guarded — never deletes a sibling's acquisition.
"""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis
import pytest

from src.infra import job_lock


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    # decode_responses=True matches the production factory in
    # shared.infra.redis_client — token comparison relies on str replies.
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(job_lock, "get_redis", lambda: client)
    return client


async def test_acquires_sets_key_and_releases_on_exit(redis: Any) -> None:
    async with job_lock.try_job_lock("lk", ttl_s=60) as acquired:
        assert acquired
        assert await redis.get("lk") is not None
        assert await redis.ttl("lk") > 0  # never set without an expiry
    assert await redis.get("lk") is None


async def test_second_holder_rejected_and_does_not_steal_lock(redis: Any) -> None:
    async with job_lock.try_job_lock("lk", ttl_s=60) as first:
        assert first
        async with job_lock.try_job_lock("lk", ttl_s=60) as second:
            assert second is False
        # The rejected holder's exit must not release the owner's lock.
        assert await redis.get("lk") is not None
    assert await redis.get("lk") is None


async def test_released_on_exception(redis: Any) -> None:
    with pytest.raises(RuntimeError):
        async with job_lock.try_job_lock("lk", ttl_s=60) as acquired:
            assert acquired
            raise RuntimeError("job blew up")
    assert await redis.get("lk") is None


async def test_released_on_cancellation(redis: Any) -> None:
    entered = asyncio.Event()

    async def _hold_forever() -> None:
        async with job_lock.try_job_lock("lk", ttl_s=60) as acquired:
            assert acquired
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(_hold_forever())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await redis.get("lk") is None


async def test_renewal_keeps_lock_past_original_ttl(redis: Any) -> None:
    """A 1-2h ingest must outlive the TTL — the renewer re-arms it."""
    async with job_lock.try_job_lock("lk", ttl_s=1, renew_every_s=0.1) as acquired:
        assert acquired
        await asyncio.sleep(1.3)  # > ttl_s: without renewal the key expires
        assert await redis.get("lk") is not None
    assert await redis.get("lk") is None


async def test_fails_open_when_redis_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DownRedis:
        async def set(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(job_lock, "get_redis", lambda: _DownRedis())
    async with job_lock.try_job_lock("lk", ttl_s=60) as acquired:
        assert acquired  # the job matters more than the duplicate guard


async def test_release_leaves_foreign_token_untouched(redis: Any) -> None:
    """If the lock expired mid-run and a sibling re-acquired it, our exit
    must not delete the sibling's key."""
    async with job_lock.try_job_lock("lk", ttl_s=60) as acquired:
        assert acquired
        await redis.set("lk", "sibling-token")
    assert await redis.get("lk") == "sibling-token"
