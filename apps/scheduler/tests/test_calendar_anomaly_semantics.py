"""Behavioural tests for the simplified deal detection (date_dip only).

The detector now runs a single strategy: date_dip (calendar_anomaly).
It compares a check-in date's price against nearby dates for the same
hotel + nights + meal. A date that is 4%+ below the local median (and
at least 1500 UAH cheaper in absolute terms) is flagged as a deal.
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


def _make_db(executed: list, executed_params: list | None = None) -> AsyncMock:
    db = AsyncMock()

    async def _execute(sql, _params=None):
        executed.append(sql.text)
        if executed_params is not None:
            executed_params.append(dict(_params) if _params else {})
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
    executed_params: list[dict] = []
    db = _make_db(executed, executed_params)

    def _session_factory():
        return db

    monkeypatch.setattr(detect_deals, "async_session_factory", _session_factory)

    redis_mock = MagicMock()

    async def _get(key: str):
        return None

    redis_mock.get = _get
    monkeypatch.setattr(detect_deals, "get_redis", lambda: redis_mock)

    return {"executed": executed, "params": executed_params}


@pytest.mark.asyncio
async def test_only_date_dip_runs(patched_orchestrator) -> None:
    """Only date_dip strategy should execute — no warm, cold, or bucket."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert len(executed_sql) == 1, f"Expected 1 SQL query (date_dip), got {len(executed_sql)}"
    assert "local_stats" in executed_sql[0], "date_dip SQL should use local_stats CTE"


@pytest.mark.asyncio
async def test_date_dip_uses_4pct_threshold(patched_orchestrator) -> None:
    """The SQL should use 0.96 multiplier (4% discount threshold)."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert any("p50 * 0.96" in sql for sql in executed_sql), (
        "date_dip should use 4% threshold (p50 * 0.96)"
    )


@pytest.mark.asyncio
async def test_date_dip_uses_nearby_dates_not_whole_season(patched_orchestrator) -> None:
    """The public copy says neighboring dates, so the SQL must not compare
    an early-June price to late-July high-season prices for the same hotel."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    assert "neighbor.check_in BETWEEN cp.check_in - INTERVAL '14 days'" in sql
    assert "neighbor.check_in <> cp.check_in" in sql
    assert "JOIN LATERAL" in sql
    assert "hs.sample_n >= 4" in sql


@pytest.mark.asyncio
async def test_date_dip_caps_per_country(patched_orchestrator) -> None:
    """Without a cap the global ORDER BY % shoves whichever country has the
    steepest drops to the top; channel ends up "all Egypt". Per-country
    ROW_NUMBER ensures no single country eats more than country_cap slots."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=50)

    sql = patched_orchestrator["executed"][0]

    assert "PARTITION BY country_iso2" in sql
    assert "ROW_NUMBER()" in sql
    assert "country_rank <= :country_cap" in sql
    # destination JOIN so the partition key can be projected.
    assert "JOIN hotels h ON h.id = cp.hotel_id" in sql
    assert "LEFT JOIN destinations dest ON dest.id = h.destination_id" in sql


@pytest.mark.asyncio
async def test_date_dip_passes_country_cap_param(patched_orchestrator) -> None:
    """Runner must bind country_cap so PostgreSQL gets a value instead of
    failing with 'no value for bind parameter'."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=50)

    params = patched_orchestrator["params"][0]
    assert params.get("country_cap") == detect_deals._DATE_DIP_COUNTRY_CAP
    assert params.get("max_per_run") == 50


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
