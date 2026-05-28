from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import _database_probe_target


def test_database_probe_target_uses_async_engine_url_host() -> None:
    url = make_url("postgresql+asyncpg://test:test@localhost:5544/test")

    assert _database_probe_target(url) == ("localhost", 5544)


def test_database_probe_target_defaults_to_local_postgres_port() -> None:
    url = make_url("postgresql+asyncpg:///fasttravel")

    assert _database_probe_target(url) == ("localhost", 5432)


def test_database_probe_target_rejects_non_postgres_urls() -> None:
    url = make_url("sqlite+aiosqlite:///tmp/test.db")

    with pytest.raises(ValueError, match="Postgres"):
        _database_probe_target(url)
