"""Regression checks for deal publication safety.

These tests intentionally inspect the SQL text. The production bugs here were
caused by SQL branches that inserted/published semantically invalid deals; a
small string-level guard catches future edits before they hit a live DB.
"""

from __future__ import annotations

import importlib

detect_deals = importlib.import_module("src.jobs.detect_deals")
post_deals = importlib.import_module("src.jobs.post_deals")
notify_subscribers = importlib.import_module("src.jobs.notify_subscribers")


def test_bucket_branch_requires_real_strike_through() -> None:
    sql = detect_deals._BUCKET_SQL.text

    assert "po.red_price_uah > po.price_uah" in sql
    assert "po.red_price_uah IS NOT NULL" in sql
    assert "AND po.red_price_uah > po.price_uah" in sql
    assert "'promo_discount'" in sql
    assert "'bucket_'" not in sql


def test_post_deals_never_selects_zero_discount_or_bucket_only_rows() -> None:
    sql = post_deals._SELECT_UNPOSTED.text

    assert "d.discount_pct >= :min_discount_pct" in sql
    assert "d.detection_method NOT LIKE 'bucket_%'" in sql
    assert "d.detection_method != 'peer_anomaly'" in sql


def test_notify_subscribers_keeps_stricter_peer_anomaly_floor() -> None:
    sql = notify_subscribers._MATCH_SQL.text

    assert "d.discount_pct >= 15" in sql
    assert "d.detection_method != 'peer_anomaly'" in sql
    assert "d.discount_pct >= 25" in sql
    assert "(f.meal_plan IS NULL OR d.meal_plan = f.meal_plan)" in sql


def test_date_dip_branch_detects_same_hotel_date_mispricing() -> None:
    """date_dip = one calendar date sharply cheaper than the same hotel's
    own median for that (nights, meal) combo."""
    sql = detect_deals._DATE_DIP_SQL.text

    assert "'calendar_anomaly'" in sql
    assert "PERCENTILE_CONT(0.5)" in sql
    assert "PERCENTILE_CONT(0.15)" in sql
    assert "cp.price_uah < hs.p50 * 0.75" in sql
    assert "cp.price_uah < hs.p15" in sql
    assert "(hs.p50 - cp.price_uah) >= 3000" in sql
    # date_dip must NOT contain the stay-inversion self-join.
    assert "long_cp.nights > short_cp.nights" not in sql


def test_cold_start_branch_tags_peer_anomaly_and_uses_peer_thresholds() -> None:
    sql = detect_deals._COLD_START_SQL.text

    assert "'peer_anomaly' AS detection_method" in sql
    assert "WITH peer_stats AS" in sql
    assert "JOIN peer_stats ps" in sql
    assert "cp.price_uah < ps.p15" in sql
    assert "cp.price_uah < ps.p50 * 0.75" in sql
    assert "(ps.p50 - cp.price_uah) >= 3000" in sql


def test_stay_inversion_branch_detects_longer_stay_cheaper() -> None:
    """stay_inversion = longer-night offer cheaper than a shorter one at
    the same hotel/check_in/meal."""
    sql = detect_deals._STAY_INVERSION_SQL.text

    assert "'calendar_anomaly'" in sql
    assert "long_cp.nights > short_cp.nights" in sql
    assert "long_cp.price_uah < short_cp.price_uah" in sql
    assert "long_cp.price_uah < short_cp.price_uah * 0.90" in sql
    assert "(short_cp.price_uah - long_cp.price_uah) >= 3000" in sql
    # No PERCENTILE_CONT — this branch compares two rows directly.
    assert "PERCENTILE_CONT" not in sql


def test_all_deal_insert_branches_ignore_daily_natural_key_conflicts() -> None:
    """Manual re-runs must not crash when today's deal already exists."""

    for sql_obj in (
        detect_deals._WARM_SQL,
        detect_deals._COLD_START_SQL,
        detect_deals._BUCKET_SQL,
        detect_deals._DATE_DIP_SQL,
        detect_deals._STAY_INVERSION_SQL,
    ):
        assert "ON CONFLICT DO NOTHING" in sql_obj.text


def test_cold_start_metrics_are_recorded_as_peer_anomaly(monkeypatch) -> None:
    class FakeCounter:
        def __init__(self) -> None:
            self.labels_seen: list[dict[str, str]] = []
            self.inc_seen: list[int] = []

        def labels(self, **labels: str) -> FakeCounter:
            self.labels_seen.append(labels)
            return self

        def inc(self, amount: int) -> None:
            self.inc_seen.append(amount)

    counter = FakeCounter()
    monkeypatch.setattr("src.infra.metrics.DEALS_INSERTED", counter)

    detect_deals._record_inserted([(1, 42, 27.5)], reason="cold")

    assert counter.labels_seen == [
        {"detection_method": "peer_anomaly", "reason": "cold"}
    ]
    assert counter.inc_seen == [1]
