"""SQLAlchemy 2.x async engine + session factory.

Exposed:
    Base                 — declarative base; models inherit from it.
    async_engine         — the AsyncEngine singleton.
    async_session_factory — async sessionmaker.
    get_session()        — async-generator DI for FastAPI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    metadata_naming_convention: dict[str, str] = {
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
    }


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


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession and rolls back on error."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping_db() -> bool:
    """Lightweight health probe — runs `SELECT 1`."""
    from sqlalchemy import text

    async with async_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        return result.scalar_one() == 1


async def dispose_engine() -> None:
    """Call from FastAPI shutdown."""
    await async_engine.dispose()


__all__: list[str] = [
    "Base",
    "async_engine",
    "async_session_factory",
    "dispose_engine",
    "get_session",
    "ping_db",
]


# Suppress unused warning — kept to enforce import order in __init__ usage.
_ = Any
