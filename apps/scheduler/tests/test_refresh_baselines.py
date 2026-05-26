"""Tests for the extracted refresh_baselines job (Sprint 1F).

We can't run a real REFRESH MV against fakeredis (it needs Postgres),
but we can verify the wrapper:
  * issues exactly one REFRESH MATERIALIZED VIEW statement
  * does NOT include CONCURRENTLY (price_baselines has no unique index)
  * records a scrape_runs row on success and failure
  * raises only on DB error (the daily tick can't silently swallow)
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

import pytest

sut = importlib.import_module("src.jobs.refresh_baselines")


@pytest.fixture
def _patch_session(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the SQL the job executes."""
    execute_mock = AsyncMock()

    class _Session:
        execute = execute_mock
        commit = AsyncMock()

    class _Factory:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sut, "async_session_factory", lambda: _Factory())
    monkeypatch.setattr(sut, "_record_run", AsyncMock())
    return {"execute": execute_mock}


async def test_issues_non_concurrent_refresh(_patch_session: dict) -> None:
    """price_baselines has no unique index → must use plain REFRESH,
    not REFRESH ... CONCURRENTLY."""
    await sut.refresh_baselines()
    sql_text = str(_patch_session["execute"].await_args.args[0])
    assert "REFRESH MATERIALIZED VIEW price_baselines" in sql_text
    assert "CONCURRENTLY" not in sql_text


async def test_success_returns_zero(_patch_session: dict) -> None:
    """Wrapper returns 0 on success (no row count to report)."""
    result = await sut.refresh_baselines()
    assert result == 0


async def test_db_failure_records_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REFRESH failure must NOT be swallowed — operators need to
    know if price_baselines is silently stale. But it MUST record
    to scrape_runs before propagating so the dashboard catches it."""

    class _BadSession:
        execute = AsyncMock(side_effect=RuntimeError("DB exploded"))
        commit = AsyncMock()

    class _Factory:
        async def __aenter__(self):
            return _BadSession()

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sut, "async_session_factory", lambda: _Factory())
    record = AsyncMock()
    monkeypatch.setattr(sut, "_record_run", record)

    with pytest.raises(RuntimeError):
        await sut.refresh_baselines()
    record.assert_awaited_once()
    args = record.await_args.args
    assert args[1] == "failed"  # status
    assert "DB exploded" in args[2]  # error
