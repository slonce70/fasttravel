"""pytest fixtures.

We rely on a real Postgres + Redis (the docker-compose services) being
reachable. Tests run inside the `api` container via
`docker compose run --rm api pytest`.

Each test gets its own session bound to a SAVEPOINT and rolled back at
teardown — no data leaks between tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.deps import get_db
from src.infra.db import async_engine
from src.main import app


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
    async with async_engine.connect() as connection:
        trans = await connection.begin()
        session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with session_factory() as session:
            try:
                yield session
            finally:
                await trans.rollback()


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
