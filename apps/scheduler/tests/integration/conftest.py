"""Integration-test fixtures — real Postgres + Redis.

These tests run only when the CI services block (audit Sprint #12)
or a local `docker compose up -d postgres redis` provides reachable
engines on the standard ports.

Skip gracefully when DB isn't reachable so unit-only runs stay green.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Build a session-scoped async engine. Skip the whole module if
    the host is unreachable."""
    import asyncio
    import socket

    # Fast pre-flight: probe TCP. The asyncpg connect error would still
    # be obvious, but probing keeps the skip clean and avoids 10 s of
    # connect timeouts when nothing's listening.
    try:
        with socket.create_connection(("localhost", 5432), timeout=1):
            pass
    except OSError:
        pytest.skip("Postgres not reachable on localhost:5432", allow_module_level=True)

    eng = create_async_engine(DATABASE_URL, future=True, pool_pre_ping=True)
    # Sanity: SELECT 1.
    async with eng.connect() as conn:
        from sqlalchemy import text

        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    yield eng
    await eng.dispose()
    # Give asyncpg cleanup tasks a chance to finish.
    await asyncio.sleep(0)


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test async session. NOT wrapped in SAVEPOINT — these tests
    are about real SQL behaviour, so they accept that they need to
    clean up after themselves or run against a freshly-migrated DB."""
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
