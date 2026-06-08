"""Per-IP rate limiting on POST /api/hotels/{id}/refresh.

The queue-cap + per-hotel lock alone can't stop an attacker rotating
hotel_ids from a single IP. slowapi adds a 10/hour/IP cap so any one
client can fill at most 10 queue slots per hour.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from shared.refresh_queue import DEFAULT_REFRESH_NIGHTS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.limiter import limiter
from src.routers import hotels as hotels_router
from src.services.refresh_queue import (
    REFRESH_QUEUE_KEY,
    REFRESH_QUEUE_MAX_LEN,
    QueueFullError,
    enqueue_refresh,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.keys: dict[str, str] = {}
        self.set_calls: list[str] = []

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls.append(key)
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def eval(self, _script: str, _numkeys: int, key: str, cap: str, value: str) -> list[int]:
        queue = self.lists.setdefault(key, [])
        if len(queue) >= int(cap):
            return [0, len(queue)]
        queue.insert(0, value)
        return [1, len(queue)]

    async def delete(self, key: str) -> int:
        existed = key in self.keys
        self.keys.pop(key, None)
        return int(existed)


class _RacingCapRedis(_FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.lists[REFRESH_QUEUE_KEY] = ["existing"] * (REFRESH_QUEUE_MAX_LEN - 1)
        self._eval_lock = asyncio.Lock()
        self.deleted_keys: list[str] = []

    async def llen(self, key: str) -> int:
        if key == REFRESH_QUEUE_KEY:
            return REFRESH_QUEUE_MAX_LEN - 1
        return await super().llen(key)

    async def eval(self, _script: str, _numkeys: int, key: str, cap: str, value: str) -> list[int]:
        async with self._eval_lock:
            return await super().eval(_script, _numkeys, key, cap, value)

    async def delete(self, key: str) -> int:
        self.deleted_keys.append(key)
        return await super().delete(key)


class _FakeRefreshResult:
    def first(self) -> tuple[int, str]:
        return (42, "888888")


class _FakeRefreshSession:
    async def execute(self, *_args: object, **_kwargs: object) -> _FakeRefreshResult:
        return _FakeRefreshResult()


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    """Each test gets a clean slowapi storage so the 10/hour bucket starts
    empty. slowapi's in-memory backend persists state across the FastAPI
    app instance otherwise, leaking 429s between tests."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_refresh_rate_limit_caps_at_ten_per_hour(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """11th identical request within the window must respond 429.

    Uses a freshly inserted hotel so we don't interfere with whatever the
    live snapshot put into the DB; the operator-mapping row points the
    refresh code at a numeric farvater_key so the request gets past the
    SSRF guard and reaches the rate limit.
    """
    dest_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('ZY', 'rl-test-country', 'RL Country', 'RL Country')
                RETURNING id
                """
            )
        )
    ).scalar_one()
    hotel_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO hotels (
                    canonical_slug, name_uk, name_en, destination_id, is_active
                )
                VALUES ('rl-test-hotel', 'RL Hotel', 'RL Hotel', :dest, true)
                RETURNING id
                """
            ),
            {"dest": dest_id},
        )
    ).scalar_one()
    operator_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO operators (code, display_name)
                VALUES ('farvater', 'Farvater')
                ON CONFLICT (code) DO UPDATE
                SET display_name = EXCLUDED.display_name
                RETURNING id
                """
            )
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO hotel_operator_mapping
                  (operator_id, external_id, hotel_id, external_name)
            VALUES (:op, '999999', :h, 'RL Hotel')
            ON CONFLICT (operator_id, external_id) DO NOTHING
            """
        ),
        {"op": operator_id, "h": hotel_id},
    )

    successes = 0
    too_many = 0
    for _ in range(11):
        resp = await client.post(f"/api/hotels/{hotel_id}/refresh")
        if resp.status_code == 200:
            successes += 1
        elif resp.status_code == 429:
            too_many += 1

    assert successes == 10, f"expected 10 OK responses, got {successes}"
    assert too_many == 1, f"expected exactly one 429, got {too_many}"


@pytest.mark.asyncio
async def test_refresh_custom_nights_respects_base_hotel_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(hotels_router, "get_redis", lambda: redis)

    hotel_id = 42
    first = await hotels_router.trigger_refresh.__wrapped__(
        request=object(),
        hotel_id=hotel_id,
        nights=None,
        session=_FakeRefreshSession(),
    )
    second = await hotels_router.trigger_refresh.__wrapped__(
        request=object(),
        hotel_id=hotel_id,
        nights=15,
        session=_FakeRefreshSession(),
    )

    assert first.queued is True
    assert second.queued is False
    assert redis.set_calls == [f"refresh:hotel:{hotel_id}", f"refresh:hotel:{hotel_id}"]

    payloads = [json.loads(item) for item in redis.lists[hotels_router.REFRESH_QUEUE_KEY]]
    assert len(payloads) == 1
    assert "requested_nights" not in payloads[0]


@pytest.mark.asyncio
async def test_refresh_custom_nights_queues_default_nights_plus_custom_then_rejects_broad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(hotels_router, "get_redis", lambda: redis)

    hotel_id = 42
    first = await hotels_router.trigger_refresh.__wrapped__(
        request=object(),
        hotel_id=hotel_id,
        nights=15,
        session=_FakeRefreshSession(),
    )
    second = await hotels_router.trigger_refresh.__wrapped__(
        request=object(),
        hotel_id=hotel_id,
        nights=None,
        session=_FakeRefreshSession(),
    )

    assert first.queued is True
    assert second.queued is False
    assert redis.set_calls == [f"refresh:hotel:{hotel_id}", f"refresh:hotel:{hotel_id}"]

    payloads = [json.loads(item) for item in redis.lists[hotels_router.REFRESH_QUEUE_KEY]]
    assert len(payloads) == 1
    assert payloads[0]["requested_nights"] == [*DEFAULT_REFRESH_NIGHTS, 15]


@pytest.mark.asyncio
async def test_refresh_queue_cap_is_enforced_atomically_under_concurrency() -> None:
    redis = _RacingCapRedis()

    async def enqueue(hotel_id: int) -> bool:
        try:
            await enqueue_refresh(
                redis,
                hotel_id=hotel_id,
                farvater_key=str(800000 + hotel_id),
                trigger="test",
            )
        except QueueFullError:
            return False
        return True

    results = await asyncio.gather(enqueue(101), enqueue(102))

    assert results.count(True) == 1
    assert results.count(False) == 1
    assert len(redis.lists[REFRESH_QUEUE_KEY]) == REFRESH_QUEUE_MAX_LEN
    assert len(redis.deleted_keys) == 1
