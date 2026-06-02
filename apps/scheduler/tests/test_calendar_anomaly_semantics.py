"""Behavioural tests for production deal detection.

The primary strategy is date_dip (calendar_anomaly). It is regime-local and
two-sided: for the same hotel + operator + nights + meal + room-family it
flags a check-in date that is a genuine V-bottom — strictly below the cheapest
neighbouring date on BOTH preceding and following shoulder frames, with the two
sides' average levels matching within side_match_ratio (return-to-baseline).
The dip must be at least dip_threshold_pct below the matched-side average, no
deeper than max_depth_pct (glitch-cliff guard), and save at least
min_absolute_saving_uah. A narrow promo_discount branch also promotes real
operator strike-through promos where red_price_uah > price_uah.
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
async def test_date_dip_uses_owner_governed_magnitude_gates(patched_orchestrator) -> None:
    """The SQL should apply the shared dip threshold, glitch-cliff depth cap,
    and absolute-saving floor on top of the local_stats CTE."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    assert f"cp.discount_pct >= {DATE_DIP_POLICY.dip_threshold_pct_sql}" in sql
    assert f"cp.discount_pct <= {DATE_DIP_POLICY.max_depth_pct_sql}" in sql
    assert f"(cp.baseline_p50 - cp.price_uah) >= {DATE_DIP_POLICY.min_absolute_saving_uah}" in sql


@pytest.mark.asyncio
async def test_date_dip_uses_nearby_dates_not_whole_season(patched_orchestrator) -> None:
    """The public copy says neighboring dates, so the detector must compare a
    date only against its two ±shoulder_frame_days shoulders — never against
    late-season prices for the same hotel."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    # Lookahead bounds on the candidate (V-bottom) date.
    assert f"CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_start_days} days'" in sql
    assert f"AND CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_end_days} days'" in sql
    # Two-sided shoulder frames, each excluding the candidate date itself.
    assert f"RANGE BETWEEN INTERVAL '{DATE_DIP_POLICY.shoulder_frame_days} days' PRECEDING" in sql
    assert f"INTERVAL '{DATE_DIP_POLICY.shoulder_frame_days} days' FOLLOWING" in sql
    assert "INTERVAL '1 day' PRECEDING" in sql
    assert "RANGE BETWEEN INTERVAL '1 day' FOLLOWING" in sql
    # Genuine V-bottom: strictly below both side minima, both sides populated.
    assert "f.price_uah < f.prec_min" in sql
    assert "f.price_uah < f.foll_min" in sql
    assert f"f.prec_n >= {DATE_DIP_POLICY.min_neighbors_per_side}" in sql
    assert f"f.foll_n >= {DATE_DIP_POLICY.min_neighbors_per_side}" in sql
    # Return-to-baseline guard rejects seasonal steps (two different regimes).
    assert (
        f"GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) "
        f"* {DATE_DIP_POLICY.side_match_ratio_sql}" in sql
    )
    # The old whole-season lateral-neighbour design is gone.
    assert "PERCENT_RANK()" not in sql
    assert "rnk BETWEEN 0.25 AND 0.75" not in sql
    assert "neighbor" not in sql
    assert "trimmed_mean" not in sql


@pytest.mark.asyncio
async def test_date_dip_uses_materialized_room_family(patched_orchestrator) -> None:
    """Equivalent Farvater room labels are normalized in current_prices, keeping
    detector lookups indexed; same-room casing duplicates are MAX-collapsed
    before the per-date family minimum instead of recomputing family per row."""
    await detect_deals.detect_deals(cooldown_hours=0, max_per_run=20)

    sql = patched_orchestrator["executed"][0]

    assert "cp.room_family" in sql
    assert "MAX(cp.price_uah)" in sql
    assert "lower(btrim(cp.room_category))" in sql
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
