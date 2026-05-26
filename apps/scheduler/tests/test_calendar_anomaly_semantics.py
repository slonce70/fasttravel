"""Behavioural tests for the calendar_anomaly branch split.

These tests don't hit Postgres — they patch `async_session_factory` and
`get_redis` so we can assert which SQL objects `detect_deals()` actually
chooses to execute under each flag combination. Catches regressions like
"feature flag added but the branch still runs anyway".

Heavyweight integration coverage (real DB + REFRESH MV + assert deal row)
is deliberately deferred — scheduler tests run with a pure-asyncio
conftest, and the production live-run after this Stage 1 lands gives the
same evidence at lower carrying cost.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

# `from src.jobs import detect_deals` is broken because src/jobs/__init__.py
# re-exports the function `detect_deals`, which shadows the submodule when
# accessed via attribute lookup. importlib gets us the module by string id.
detect_deals = importlib.import_module("src.jobs.detect_deals")


class _FakeResult:
    """Mimics SQLAlchemy `Result.all()` returning rows the orchestrator
    expects: objects with `.id`, `.hotel_id`, `.discount_pct` attributes."""

    def __init__(self, rows: list[tuple[int, int, float]] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[MagicMock]:
        out = []
        for rid, hid, disc in self._rows:
            m = MagicMock()
            m.id = rid
            m.hotel_id = hid
            m.discount_pct = disc
            m.detection_method = "calendar_anomaly"
            out.append(m)
        return out


def _make_db(executed: list) -> AsyncMock:
    """Build a mock AsyncSession that records every SQL object executed
    via its `.text` body so tests can assert which branches fired."""
    db = AsyncMock()

    async def _execute(sql, _params=None):
        executed.append(sql.text)
        return _FakeResult()

    db.execute = _execute
    db.commit = AsyncMock(return_value=None)
    db.rollback = AsyncMock(return_value=None)
    db.__aenter__.return_value = db
    db.__aexit__.return_value = None
    return db


@pytest.fixture
def patched_orchestrator(monkeypatch):
    """Patch session factory + redis so detect_deals can run sans infra.
    Tests configure the returned `flags` dict to control feature toggles."""
    executed: list[str] = []
    db = _make_db(executed)

    def _session_factory():
        return db

    monkeypatch.setattr(detect_deals, "async_session_factory", _session_factory)

    flags: dict[str, str | None] = {
        detect_deals.COLD_START_FLAG_KEY: None,
        detect_deals.STAY_INVERSION_FLAG_KEY: None,
    }

    redis_mock = MagicMock()

    async def _get(key: str):
        return flags.get(key)

    redis_mock.get = _get

    monkeypatch.setattr(detect_deals, "get_redis", lambda: redis_mock)

    return {"executed": executed, "flags": flags}


@pytest.mark.asyncio
async def test_stay_inversion_skipped_when_flag_off(patched_orchestrator) -> None:
    """With the Redis flag absent (default), the stay_inversion SQL must
    NOT be executed. date_dip + warm + cold are still expected to run."""
    patched_orchestrator["flags"][detect_deals.STAY_INVERSION_FLAG_KEY] = None

    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20, force_cold_start=False)

    executed_sql = patched_orchestrator["executed"]
    assert (
        any("long_cp.nights > short_cp.nights" in sql for sql in executed_sql) is False
    ), "stay_inversion ran despite flag being OFF"
    assert any(
        "PERCENTILE_CONT(0.15)" in sql and "long_cp" not in sql for sql in executed_sql
    ), "date_dip should always run"


@pytest.mark.asyncio
async def test_stay_inversion_runs_when_flag_on(patched_orchestrator) -> None:
    """Flag = 'true' must enable the stay_inversion branch."""
    patched_orchestrator["flags"][detect_deals.STAY_INVERSION_FLAG_KEY] = "true"

    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20, force_cold_start=False)

    executed_sql = patched_orchestrator["executed"]
    assert any(
        "long_cp.nights > short_cp.nights" in sql for sql in executed_sql
    ), "stay_inversion should run when flag is ON"


@pytest.mark.asyncio
async def test_redis_outage_defaults_stay_inversion_off(patched_orchestrator, monkeypatch) -> None:
    """If Redis is unreachable, stay_inversion must default to OFF (safer
    failure mode — the alternative is silently overfiring deals)."""
    redis_mock = MagicMock()

    async def _exploding_get(_key: str):
        raise RuntimeError("redis down")

    redis_mock.get = _exploding_get
    monkeypatch.setattr(detect_deals, "get_redis", lambda: redis_mock)

    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20, force_cold_start=False)

    executed_sql = patched_orchestrator["executed"]
    assert not any(
        "long_cp.nights > short_cp.nights" in sql for sql in executed_sql
    ), "stay_inversion must stay OFF when Redis errors"


def test_flag_key_constant_is_documented() -> None:
    """The Redis key name is part of the operational contract — runbooks
    and dashboards reference it. Pin it down."""
    assert detect_deals.STAY_INVERSION_FLAG_KEY == "flag:stay_inversion_enabled"
