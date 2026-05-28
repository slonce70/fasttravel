"""Async Redis client factory.

Used by scheduler jobs that coordinate through Redis, such as snapshot queue
workers and Farvater sweep locks. Kept process-local — no shared state with
apps/api at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shared.infra.redis_client import close_redis as close_redis_client
from shared.infra.redis_client import get_redis_factory
from src.config import get_settings

_get_client: Callable[[], Any] | None = None


def get_redis() -> Any:
    """Lazy-init shared async Redis client."""
    global _get_client
    if _get_client is None:
        settings = get_settings()
        _get_client = get_redis_factory(settings.redis_url)
    return _get_client()


async def close_redis() -> None:
    global _get_client
    if _get_client is not None:
        await close_redis_client(_get_client())
        _get_client = None
