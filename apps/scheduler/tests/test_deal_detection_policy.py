from __future__ import annotations

from decimal import Decimal

import pytest

from shared.deal_detection import (
    DATE_DIP_POLICY,
    DateDipPolicy,
    date_dip_neighbor_stats_lateral_sql,
)


def test_date_dip_policy_renders_stable_sql_literals() -> None:
    assert DATE_DIP_POLICY.discount_multiplier_sql == "0.96"
    assert DATE_DIP_POLICY.max_spread_ratio_sql == "2.5"
    assert DATE_DIP_POLICY.max_discount_pct_sql == "50"
    # price/baseline floor equivalent to a 50% cap.
    assert DATE_DIP_POLICY.min_price_ratio_sql == "0.5"


def _policy(**overrides: object) -> DateDipPolicy:
    kwargs: dict[str, object] = {
        "lookahead_start_days": 5,
        "lookahead_end_days": 90,
        "neighbor_window_days": 14,
        "min_sample_size": 4,
        "max_spread_ratio": Decimal("2.5"),
        "discount_multiplier": Decimal("0.96"),
        "min_absolute_saving_uah": 1500,
        "max_discount_pct": 50,
    }
    kwargs.update(overrides)
    return DateDipPolicy(**kwargs)  # type: ignore[arg-type]


def test_date_dip_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="discount_multiplier"):
        _policy(discount_multiplier=Decimal("1.0"))


def test_date_dip_policy_rejects_out_of_range_discount_cap() -> None:
    with pytest.raises(ValueError, match="max_discount_pct"):
        _policy(max_discount_pct=0)
    with pytest.raises(ValueError, match="max_discount_pct"):
        _policy(max_discount_pct=101)


def test_date_dip_neighbor_stats_sql_collapses_aliases_to_unique_dates() -> None:
    sql = date_dip_neighbor_stats_lateral_sql(candidate_alias="cp")

    assert "JOIN LATERAL" in sql
    assert "GROUP BY neighbor.check_in" in sql
    assert "MIN(neighbor.price_uah) AS price_uah" in sql
    assert "COUNT(*) AS sample_n" in sql
    assert f"hs.sample_n >= {DATE_DIP_POLICY.min_sample_size}" in sql
    assert f"hs.p_max <= hs.p_min * {DATE_DIP_POLICY.max_spread_ratio_sql}" in sql
    assert (
        f"neighbor.check_in BETWEEN cp.check_in - INTERVAL "
        f"'{DATE_DIP_POLICY.neighbor_window_days} days'"
    ) in sql


def test_date_dip_neighbor_stats_sql_rejects_unsafe_alias() -> None:
    with pytest.raises(ValueError, match="candidate_alias"):
        date_dip_neighbor_stats_lateral_sql(candidate_alias="cp; DROP TABLE deals")
