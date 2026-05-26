"""Async Redis client factory + health probe."""

import redis.asyncio as aioredis

from src.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Lazy-init shared async Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def ping_redis() -> bool:
    return bool(await get_redis().ping())


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
