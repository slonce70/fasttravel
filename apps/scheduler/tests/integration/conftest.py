"""Integration-test fixtures — real Postgres + Redis.

These tests run only when the CI services block, the `scheduler-test`
compose service, or a local `docker compose up -d postgres redis` provides
a reachable database.

Skip gracefully when DB isn't reachable so unit-only runs stay green.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@localhost:5432/fasttravel"
)
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
_DATABASE_URL_EXPLICIT = "DATABASE_URL" in os.environ


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Build an async engine. Skip cleanly if the configured host is unreachable."""
    import asyncio
    import socket

    # Fast pre-flight: probe TCP. The asyncpg connect error would still
    # be obvious, but probing keeps the skip clean and avoids 10 s of
    # connect timeouts when nothing's listening.
    url = make_url(DATABASE_URL)
    host = url.host or "localhost"
    port = int(url.port or 5432)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError:
        pytest.skip(f"Postgres not reachable on {host}:{port}", allow_module_level=True)

    eng = create_async_engine(DATABASE_URL, future=True, pool_pre_ping=True)
    # Sanity: SELECT 1. If the developer has some other Postgres on
    # localhost, default integration tests should skip instead of failing
    # unit-only runs with auth/schema noise. An explicit DATABASE_URL is
    # treated as an intentional integration-test target and failures surface.
    try:
        async with eng.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as exc:
        await eng.dispose()
        if _DATABASE_URL_EXPLICIT:
            raise
        pytest.skip(f"Postgres not usable for scheduler integration tests: {exc}")
    yield eng
    await eng.dispose()
    # Give asyncpg cleanup tasks a chance to finish.
    await asyncio.sleep(0)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test async session rolled back at teardown."""
    async with engine.connect() as connection:
        trans = await connection.begin()
        factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with factory() as s:
            try:
                yield s
            finally:
                await trans.rollback()
