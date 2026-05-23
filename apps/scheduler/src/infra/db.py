"""SQLAlchemy 2.x async engine + session factory.

Same shape as apps/api/src/infra/db.py — kept duplicated rather than
imported so the scheduler image stays independent of the API image. The
two are likely to diverge over time (different pool sizes, no FastAPI
DI hook here) so duplication is the lower-risk choice.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


async_engine: AsyncEngine = _build_engine()
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def dispose_engine() -> None:
    """Call from scheduler shutdown."""
    await async_engine.dispose()


__all__: list[str] = [
    "async_engine",
    "async_session_factory",
    "dispose_engine",
]
