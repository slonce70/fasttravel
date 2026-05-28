"""Behavioural tests for production deal detection.

The primary strategy is date_dip (calendar_anomaly). It compares a check-in
date's price against nearby dates for the same hotel + operator + nights +
meal + room-family neighborhood. A date that is 4%+ below the trimmed local
baseline (and at least 1500 UAH cheaper in absolute terms) is flagged as a
deal. A narrow promo_discount branch also promotes real operator strike-through
promos where red_price_uah > price_uah.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.deal_detection import DATE_DIP_POLICY

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

    return {"executed": executed, "params": executed_params}


@pytest.mark.asyncio
async def test_only_active_production_strategies_run(patched_orchestrator) -> None:
    """Only date_dip plus real promo-discount strategies should execute."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert len(executed_sql) == 2, f"Expected 2 SQL queries, got {len(executed_sql)}"
    assert "local_stats" in executed_sql[0], "date_dip SQL should use local_stats CTE"
    assert "FROM promo_offers po" in executed_sql[1]
    assert "po.red_price_uah > po.price_uah" in executed_sql[1]


@pytest.mark.asyncio
async def test_date_dip_uses_4pct_threshold(patched_orchestrator) -> None:
    """The SQL should use 0.96 multiplier (4% discount threshold)."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    assert any(
        f"trimmed_mean * {DATE_DIP_POLICY.discount_multiplier_sql}" in sql for sql in executed_sql
    ), "date_dip should use the shared date-dip discount multiplier"


@pytest.mark.asyncio
async def test_date_dip_uses_nearby_dates_not_whole_season(patched_orchestrator) -> None:
    """The public copy says neighboring dates, so the SQL must not compare
    an early-June price to late-July high-season prices for the same hotel."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    assert f"CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_start_days} days'" in sql
    assert f"AND CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_end_days} days'" in sql
    assert (
        "neighbor.check_in BETWEEN "
        f"cp.check_in - INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'" in sql
    )
    assert f"cp.check_in + INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'" in sql
    assert "neighbor.check_in <> cp.check_in" in sql
    assert "room_family" in sql
    assert "neighbor.room_family = cp.room_family" in sql
    assert "GROUP BY neighbor.check_in" in sql
    assert "neighbor.room_category = cp.room_category" not in sql
    assert "JOIN LATERAL" in sql
    assert f"hs.sample_n >= {DATE_DIP_POLICY.min_sample_size}" in sql
    # Trimmed local baseline + consistency gate. Farvater's synthetic "sold out"
    # placeholder prices were inflating the plain local comparison by 3-5x and
    # triggering false 70-80% "deals". Two defences:
    #   1. interquartile mean (PERCENT_RANK middle 50%) — robust to a few
    #      outliers in an otherwise clean sample.
    #   2. p_max <= p_min * 2.5 — rejects the baseline entirely when the
    #      neighbour spread is too wide to be trusted (bimodal data with
    #      ≥half synthetic rows can't be saved by trimming alone).
    assert "PERCENT_RANK()" in sql
    assert "rnk BETWEEN 0.25 AND 0.75" in sql
    assert f"hs.p_max <= hs.p_min * {DATE_DIP_POLICY.max_spread_ratio_sql}" in sql


@pytest.mark.asyncio
async def test_date_dip_uses_materialized_room_family(patched_orchestrator) -> None:
    """Equivalent Farvater room labels are normalized in current_prices, keeping
    detector lookups indexed instead of recomputing family per neighbor row."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    assert "cp.room_family" in sql
    assert "neighbor.room_family = cp.room_family" in sql
    assert "regexp_replace" not in sql


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
async def test_detect_deals_rolls_back_all_branches_when_promo_branch_fails(monkeypatch) -> None:
    """Date-dip and promo promotion should share one transaction boundary."""
    db = AsyncMock()
    executions = 0

    async def _execute(_sql, _params=None):
        nonlocal executions
        executions += 1
        if executions == 1:
            return _FakeResult([(1, 101, 12.5)])
        raise RuntimeError("promo query failed")

    db.execute = _execute
    db.commit = AsyncMock(return_value=None)
    db.rollback = AsyncMock(return_value=None)
    db.__aenter__.return_value = db
    db.__aexit__.return_value = None

    monkeypatch.setattr(detect_deals, "async_session_factory", lambda: db)

    with pytest.raises(RuntimeError, match="promo query failed"):
        await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_warm_cold_bucket_only_executed(patched_orchestrator) -> None:
    """Warm, cold, and bucket-only strategies must not execute."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    executed_sql = patched_orchestrator["executed"]
    for sql in executed_sql:
        assert "price_baselines" not in sql, "warm strategy should not run"
        assert "peer_stats" not in sql, "cold strategy should not run"
        assert "long_cp.nights > short_cp.nights" not in sql, "stay_inversion should not run"
    assert any("FROM promo_offers po" in sql for sql in executed_sql)
    assert all("'bucket_'" not in sql for sql in executed_sql)
