from __future__ import annotations

from decimal import Decimal

import pytest

from shared.deal_detection import (
    DATE_DIP_POLICY,
    DateDipPolicy,
    date_dip_local_v_cte_sql,
)


def test_date_dip_policy_renders_stable_sql_literals() -> None:
    # SQL-literal props are interpolated into the CTE chain, so they must
    # render the exact owner-governed thresholds (no Decimal repr surprises).
    assert DATE_DIP_POLICY.side_match_ratio_sql == "1.15"
    assert DATE_DIP_POLICY.dip_threshold_pct_sql == "8"
    assert DATE_DIP_POLICY.max_depth_pct_sql == "35"


def test_date_dip_policy_exposes_owner_governed_fields() -> None:
    assert DATE_DIP_POLICY.lookahead_start_days == 5
    assert DATE_DIP_POLICY.lookahead_end_days == 90
    assert DATE_DIP_POLICY.shoulder_frame_days == 7
    assert DATE_DIP_POLICY.min_neighbors_per_side == 3
    assert DATE_DIP_POLICY.side_match_ratio == Decimal("1.15")
    assert DATE_DIP_POLICY.dip_threshold_pct == 8
    assert DATE_DIP_POLICY.max_depth_pct == 35
    assert DATE_DIP_POLICY.min_absolute_saving_uah == 1500


def _policy(**overrides: object) -> DateDipPolicy:
    kwargs: dict[str, object] = {
        "lookahead_start_days": 5,
        "lookahead_end_days": 90,
        "shoulder_frame_days": 7,
        "min_neighbors_per_side": 3,
        "side_match_ratio": Decimal("1.15"),
        "dip_threshold_pct": 8,
        "max_depth_pct": 35,
        "min_absolute_saving_uah": 1500,
    }
    kwargs.update(overrides)
    return DateDipPolicy(**kwargs)  # type: ignore[arg-type]


def test_date_dip_policy_accepts_default_shaped_overrides() -> None:
    # The helper baseline must itself be valid, otherwise the rejection
    # tests below would pass for the wrong reason.
    policy = _policy()
    assert policy.shoulder_frame_days == 7
    assert policy.side_match_ratio == Decimal("1.15")


def test_date_dip_policy_rejects_non_positive_shoulder_frame() -> None:
    with pytest.raises(ValueError, match="shoulder_frame_days"):
        _policy(shoulder_frame_days=0)


def test_date_dip_policy_rejects_non_positive_min_neighbors() -> None:
    with pytest.raises(ValueError, match="min_neighbors_per_side"):
        _policy(min_neighbors_per_side=0)


def test_date_dip_policy_rejects_side_match_ratio_at_or_below_one() -> None:
    # side_match_ratio is the return-to-baseline tolerance; <=1 would reject
    # every two-sided candidate, so the guard must require a value above 1.
    with pytest.raises(ValueError, match="side_match_ratio"):
        _policy(side_match_ratio=Decimal("1.0"))


def test_date_dip_policy_rejects_dip_threshold_outside_open_range() -> None:
    # dip_threshold must sit strictly inside (0, max_depth_pct): a zero floor
    # would flag flat dates, and a floor at/above the depth cap is empty.
    with pytest.raises(ValueError, match="dip_threshold_pct"):
        _policy(dip_threshold_pct=0)
    with pytest.raises(ValueError, match="dip_threshold_pct"):
        _policy(dip_threshold_pct=35)


def test_date_dip_policy_rejects_out_of_range_depth_cap() -> None:
    # max_depth_pct must be in (0, 100]. 101 is the only direction reachable
    # without first tripping the dip<depth check (0 would raise on that first).
    with pytest.raises(ValueError, match="max_depth_pct"):
        _policy(max_depth_pct=101)


def test_date_dip_policy_rejects_non_positive_absolute_saving() -> None:
    with pytest.raises(ValueError, match="min_absolute_saving_uah"):
        _policy(min_absolute_saving_uah=0)


def test_date_dip_policy_rejects_inverted_lookahead_bounds() -> None:
    with pytest.raises(ValueError, match="lookahead_start_days"):
        _policy(lookahead_start_days=-1)
    with pytest.raises(ValueError, match="lookahead_end_days"):
        _policy(lookahead_start_days=90, lookahead_end_days=90)


def test_date_dip_cte_builds_series_framed_local_stats_chain() -> None:
    sql = date_dip_local_v_cte_sql()

    # The shared CTE chain feeds both the channel detector and the web calendar.
    assert "series AS" in sql
    assert "framed AS" in sql
    assert "local_stats AS" in sql


def test_date_dip_cte_uses_two_sided_shoulder_frames() -> None:
    sql = date_dip_local_v_cte_sql()

    # Symmetric +-shoulder_frame_days windows: a preceding frame and a
    # following frame, each excluding the candidate date itself.
    assert "RANGE BETWEEN INTERVAL '7 days' PRECEDING" in sql
    assert "INTERVAL '1 day' PRECEDING" in sql
    assert "RANGE BETWEEN INTERVAL '1 day' FOLLOWING" in sql
    assert "INTERVAL '7 days' FOLLOWING" in sql
    for stat in ("prec_min", "foll_min", "prec_avg", "foll_avg", "prec_n", "foll_n"):
        assert stat in sql


def test_date_dip_cte_requires_true_two_sided_v_bottom() -> None:
    sql = date_dip_local_v_cte_sql()

    # Strictly below BOTH side minima — a real valley, not the edge of a step.
    assert "f.price_uah < f.prec_min" in sql
    assert "f.price_uah < f.foll_min" in sql
    # Both sides must have at least min_neighbors_per_side priced dates.
    assert "f.prec_n >= 3" in sql
    assert "f.foll_n >= 3" in sql


def test_date_dip_cte_enforces_return_to_baseline_side_match() -> None:
    sql = date_dip_local_v_cte_sql()

    # The two sides' average levels must match within side_match_ratio so a
    # seasonal step (different regimes left vs right) is rejected.
    assert "GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) * 1.15" in sql


def test_date_dip_cte_exposes_honest_baseline_and_discount() -> None:
    sql = date_dip_local_v_cte_sql()

    # The displayed baseline is the matched-side average (honest typical price).
    assert "baseline_p50" in sql
    assert "discount_pct" in sql


def test_date_dip_cte_collapses_same_room_casing_before_min() -> None:
    sql = date_dip_local_v_cte_sql()

    # Casing/whitespace duplicates of one room on one date are collapsed to
    # their MAX first, so a phantom cheap re-listing can't manufacture a dip.
    assert "MAX(cp.price_uah)" in sql
    assert "lower(btrim(cp.room_category))" in sql


def test_date_dip_cte_threads_extra_series_filter_into_inner_scan() -> None:
    plain = date_dip_local_v_cte_sql()
    scoped = date_dip_local_v_cte_sql(extra_series_filter="AND cp.hotel_id = :hotel_id")

    # The per-hotel calendar passes a trusted literal predicate that must land
    # inside the inner series WHERE (and not appear when omitted).
    assert "AND cp.hotel_id = :hotel_id" in scoped
    assert "AND cp.hotel_id = :hotel_id" not in plain
