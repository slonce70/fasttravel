from __future__ import annotations

import json
from importlib import import_module

import pytest
from fakeredis.aioredis import FakeRedis

snapshot_hot_module = import_module("src.jobs.snapshot_hot")


class _FakeRedis(FakeRedis):
    async def eval(self, _script: str, _numkeys: int, key: str, cap: str, value: str) -> list[int]:
        current = await self.llen(key)
        if current >= int(cap):
            return [0, current]
        await self.lpush(key, value)
        return [1, current + 1]


def _resolver(mapping: dict[int, str]):
    async def resolve(hotel_ids: list[int]) -> dict[int, str]:
        return {hotel_id: mapping[hotel_id] for hotel_id in hotel_ids if hotel_id in mapping}

    return resolve


@pytest.mark.asyncio
async def test_snapshot_hot_queues_top_mapped_unlocked_hotels(monkeypatch) -> None:
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
async def test_snapshot_hot_skips_hotels_with_active_refresh_lock(monkeypatch) -> None:
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
async def test_snapshot_hot_skips_unmapped_hotels(monkeypatch) -> None:
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
async def test_snapshot_hot_respects_shared_refresh_queue_cap(monkeypatch) -> None:
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
