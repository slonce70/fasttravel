"""Behavioural tests for the simplified deal detection (date_dip only).

The detector now runs a single strategy: date_dip (calendar_anomaly).
It compares a check-in date's price against the median price for the
same hotel + nights + meal across all available dates. A date that is
10%+ below the median is flagged as a deal.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

detect_deals = importlib.import_module("src.jobs.detect_deals")


class _FakeResult:
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
    executed: list[str] = []
    db = _make_db(executed)

    def _session_factory():
        return db

    monkeypatch.setattr(detect_deals, "async_session_factory", _session_factory)

    redis_mock = MagicMock()

    async def _get(key: str):
        return None

    redis_mock.get = _get
    monkeypatch.setattr(detect_deals, "get_redis", lambda: redis_mock)

    return {"executed": executed}


@pytest.mark.asyncio
async def test_only_date_dip_runs(patched_orchestrator) -> None:
    """Only date_dip strategy should execute — no warm, cold, or bucket."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert len(executed_sql) == 1, f"Expected 1 SQL query (date_dip), got {len(executed_sql)}"
    assert "hotel_stats" in executed_sql[0], "date_dip SQL should use hotel_stats CTE"


@pytest.mark.asyncio
async def test_date_dip_uses_10pct_threshold(patched_orchestrator) -> None:
    """The SQL should use 0.90 multiplier (10% discount threshold)."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert any("p50 * 0.90" in sql for sql in executed_sql), (
        "date_dip should use 10% threshold (p50 * 0.90)"
    )


@pytest.mark.asyncio
async def test_no_warm_cold_bucket_executed(patched_orchestrator) -> None:
    """Warm, cold, and bucket strategies must not execute."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    for sql in executed_sql:
        assert "price_baselines" not in sql, "warm strategy should not run"
        assert "peer_stats" not in sql, "cold strategy should not run"
        assert "promo_offers" not in sql, "bucket strategy should not run"
        assert "long_cp.nights > short_cp.nights" not in sql, "stay_inversion should not run"
