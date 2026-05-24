"""Centralised FastAPI dependencies (re-exported for routers)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.infra.cache import get_redis as _get_redis
from src.infra.db import get_session as _get_session


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a transactional AsyncSession."""
    async for session in _get_session():
        yield session


async def get_redis() -> aioredis.Redis:
    """Return the singleton Redis client."""
    return _get_redis()


def get_app_settings() -> Settings:
    """Cached settings — handy when a route needs config injected."""
    return get_settings()
