"""Async Redis client factory.

Used by detect_deals to read the `flag:cold_start` feature flag and by
post_deals for the (future) per-hotel anti-spam dedup key. Kept
process-local — no shared state with apps/api at runtime.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from src.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Lazy-init shared async Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
