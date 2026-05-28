"""pytest fixtures.

We rely on a real Postgres + Redis (the docker-compose services) being
reachable. Tests run inside the `api-test` container from
docker-compose.test.yml so dev-only pytest dependencies stay out of the
production API image.

Each test gets its own session bound to a SAVEPOINT and rolled back at
teardown — no data leaks between tests.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.deps import get_db
from src.infra.db import async_engine
from src.main import app

_DATABASE_URL_EXPLICIT = "DATABASE_URL" in os.environ


def _database_probe_target(url: URL) -> tuple[str, int]:
    if "postgresql" not in url.drivername:
        raise ValueError("API DB tests require a Postgres database URL")
    return url.host or "localhost", int(url.port or 5432)


async def _ensure_database_reachable() -> None:
    host, port = _database_probe_target(async_engine.url)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError as exc:
        if _DATABASE_URL_EXPLICIT:
            raise
        pytest.skip(f"Postgres not reachable on {host}:{port}: {exc}")

    try:
        async with async_engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as exc:
        await async_engine.dispose()
        if _DATABASE_URL_EXPLICIT:
            raise
        pytest.skip(f"Postgres not usable for API tests: {exc}")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Hand out a session bound to a SAVEPOINT that gets rolled back.

    `async_engine` is module-level. pytest-asyncio gives each test its own
    event loop, but asyncpg connections in the engine's pool are bound to
    whatever loop first opened them — re-using a connection on a fresh loop
    crashes pool teardown with "Event loop is closed". `dispose()` drops
    the pool, forcing a clean connection on the current test's loop.
    """
    await async_engine.dispose()
    await _ensure_database_reachable()
    await async_engine.dispose()
    async with async_engine.connect() as connection:
        trans = await connection.begin()
        session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with session_factory() as session:
            try:
                yield session
            finally:
                await trans.rollback()
    await async_engine.dispose()
    await asyncio.sleep(0)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """ASGI httpx client with the DB dep overridden to share the test txn."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
