from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from importlib import import_module
from typing import Any, TypeVar

import pytest
from fakeredis.aioredis import FakeRedis

snapshot_hot_module = import_module("src.jobs.snapshot_hot")

T = TypeVar("T")


async def _await_if_needed(value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


class _FakeRedis:
    def __init__(self, *, decode_responses: bool = False) -> None:
        self._redis = FakeRedis(decode_responses=decode_responses)

    async def eval(self, _script: str, _numkeys: int, key: str, cap: str, value: str) -> list[int]:
        current = await self.llen(key)
        if current >= int(cap):
            return [0, current]
        await self.lpush(key, value)
        return [1, current + 1]

    async def llen(self, key: str) -> int:
        return int(await _await_if_needed(self._redis.llen(key)))

    async def lpush(self, key: str, value: str) -> int:
        return int(await _await_if_needed(self._redis.lpush(key, value)))

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = await _await_if_needed(self._redis.lrange(key, start, end))
        return [str(value) for value in values]

    async def mget(self, keys: list[str]) -> list[str | None]:
        values = await _await_if_needed(self._redis.mget(keys))
        return [None if value is None else str(value) for value in values]

    async def set(self, key: str, value: str) -> bool:
        return bool(await _await_if_needed(self._redis.set(key, value)))

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
        async for key in self._redis.scan_iter(match=match, count=count):
            yield str(key)

    def pipeline(self) -> Any:
        return self._redis.pipeline()


def _resolver(mapping: dict[int, str]) -> Callable[[list[int]], Awaitable[dict[int, str]]]:
    async def resolve(hotel_ids: list[int]) -> dict[int, str]:
        return {hotel_id: mapping[hotel_id] for hotel_id in hotel_ids if hotel_id in mapping}

    return resolve


@pytest.mark.asyncio
async def test_snapshot_hot_queues_top_mapped_unlocked_hotels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis(decode_responses=True)
    await redis.set("hot:hotel:10", "2")
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({20: "fv20", 30: "fv30", 10: "fv10"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 2
    payloads = [json.loads(item) for item in await redis.lrange("refresh:queue", 0, -1)]
    assert {item["hotel_id"] for item in payloads} == {20, 30}
    assert all(item["trigger"] == "hot_priority" for item in payloads)


@pytest.mark.asyncio
async def test_snapshot_hot_skips_hotels_with_active_refresh_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis(decode_responses=True)
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")
    await redis.set("refresh:hotel:20", "already-refreshing")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({20: "fv20", 30: "fv30"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 1
    payloads = [json.loads(item) for item in await redis.lrange("refresh:queue", 0, -1)]
    assert [item["hotel_id"] for item in payloads] == [30]


@pytest.mark.asyncio
async def test_snapshot_hot_skips_unmapped_hotels(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis(decode_responses=True)
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({30: "fv30"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 1
    payloads = [json.loads(item) for item in await redis.lrange("refresh:queue", 0, -1)]
    assert [item["hotel_id"] for item in payloads] == [30]


@pytest.mark.asyncio
async def test_snapshot_hot_respects_shared_refresh_queue_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis(decode_responses=True)
    for i in range(snapshot_hot_module.REFRESH_QUEUE_MAX_LEN - 1):
        await redis.lpush("refresh:queue", f"existing-{i}")
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({20: "fv20", 30: "fv30"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 1
    assert await redis.llen("refresh:queue") == snapshot_hot_module.REFRESH_QUEUE_MAX_LEN
    payload = json.loads((await redis.lrange("refresh:queue", 0, 0))[0])
    assert payload["hotel_id"] == 20


@pytest.mark.asyncio
async def test_snapshot_hot_skips_hotels_with_custom_nights_refresh_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis(decode_responses=True)
    await redis.set("hot:hotel:20", "9")
    await redis.set("hot:hotel:30", "5")
    await redis.set("refresh:hotel:20:nights:15", "already-refreshing")

    monkeypatch.setattr(snapshot_hot_module, "get_redis", lambda: redis)
    monkeypatch.setattr(
        snapshot_hot_module,
        "_resolve_farvater_keys",
        _resolver({20: "fv20", 30: "fv30"}),
    )

    queued = await snapshot_hot_module.snapshot_hot(top_n=2)

    assert queued == 1
    payloads = [json.loads(item) for item in await redis.lrange("refresh:queue", 0, -1)]
    assert [item["hotel_id"] for item in payloads] == [30]
