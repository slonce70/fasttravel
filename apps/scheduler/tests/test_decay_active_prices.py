"""Unit tests for the extracted decay_active_prices job.

The behaviour we lock in:

  1. Failures propagate — track_job_metrics must record
     outcome="failure" instead of counting a broken decay as success.
  2. scrape_runs gets a row even on failure (so dashboards see it).
  3. The configurable threshold via env DECAY_STALE_AFTER_DAYS is
     respected — defaults to 7 days, matches the inline behaviour
     this job replaced.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

# See test_static_tours_sweep — `from src.jobs import decay_active_prices`
# resolves to the FUNCTION exported by jobs/__init__, not the module.
sut = importlib.import_module("src.jobs.decay_active_prices")


@pytest.fixture
def _patch_session(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub `async_session_factory` with a context manager that yields
    a session whose `.execute(...)` returns a configurable rowcount."""

    rowcount = {"value": 5}
    execute_mock = AsyncMock(return_value=MagicMock(rowcount=rowcount["value"]))

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
    return {"execute": execute_mock, "rowcount": rowcount}


async def test_decay_returns_demoted_count(
    _patch_session: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Adjust the rowcount the mock returns.
    _patch_session["execute"].return_value = MagicMock(rowcount=12)
    result = await sut.decay_active_prices()
    assert result == 12


async def test_decay_uses_default_7_days(
    _patch_session: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DECAY_STALE_AFTER_DAYS", raising=False)
    await sut.decay_active_prices()
    # The SQL bound `:d` to 7 by default.
    # SQLAlchemy `execute(sql, params)` — params is positional[1] not kwarg.
    args = _patch_session["execute"].await_args.args
    assert args[1] == {"d": 7}


async def test_decay_honours_env_override(
    _patch_session: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DECAY_STALE_AFTER_DAYS", "3")
    await sut.decay_active_prices()
    args = _patch_session["execute"].await_args.args
    assert args[1] == {"d": 3}


async def test_decay_falls_back_on_bad_env(
    _patch_session: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DECAY_STALE_AFTER_DAYS", "not-a-number")
    await sut.decay_active_prices()
    args = _patch_session["execute"].await_args.args
    assert args[1] == {"d": 7}


async def test_decay_raises_on_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract: failures propagate so track_job_metrics records
    outcome="failure" — the wrapper only sees failures via exceptions."""

    class _BadFactory:
        async def __aenter__(self):
            raise RuntimeError("postgres unreachable")

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sut, "async_session_factory", lambda: _BadFactory())
    monkeypatch.setattr(sut, "_record_run", AsyncMock())

    with pytest.raises(RuntimeError, match="postgres unreachable"):
        await sut.decay_active_prices()


async def test_decay_records_failure_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadFactory:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(sut, "async_session_factory", lambda: _BadFactory())
    record_mock = AsyncMock()
    monkeypatch.setattr(sut, "_record_run", record_mock)

    with pytest.raises(RuntimeError, match="boom"):
        await sut.decay_active_prices()
    record_mock.assert_awaited_once()
    args = record_mock.await_args.args
    assert args[1] == "failed"  # status
    assert "boom" in args[3]  # error
