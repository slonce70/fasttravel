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
    assert "d.detected_at >= NOW() - INTERVAL '6 hours'" in sql


def test_post_deals_selects_short_hotel_context_fields() -> None:
    sql = post_deals._SELECT_UNPOSTED.text

    assert "h.description_uk" in sql
    assert "h.review_score" in sql
    assert "h.review_count" in sql


def test_notify_subscribers_discount_floor() -> None:
    sql = notify_subscribers._MATCH_SQL.text

    assert "d.discount_pct >= 4" in sql
    assert "(f.meal_plan IS NULL OR d.meal_plan = f.meal_plan)" in sql


def test_date_dip_branch_detects_same_hotel_date_mispricing() -> None:
    """date_dip = one calendar date sharply cheaper than nearby dates for
    the same hotel + nights + meal combo."""
    sql = detect_deals._DATE_DIP_SQL.text

    assert "'calendar_anomaly'" in sql
    assert "PERCENTILE_CONT(0.5)" in sql
    assert "local_stats" in sql
    assert "neighbor.check_in BETWEEN cp.check_in - INTERVAL '14 days'" in sql
    assert "neighbor.check_in <> cp.check_in" in sql
    assert "p50 * 0.96" in sql
    assert "(cp.p50 - cp.price_uah) >= 1500" in sql
    assert "long_cp.nights > short_cp.nights" not in sql
    # Per-country diversity guard (without it the top-N by % is dominated
    # by whichever single country has the steepest drops).
    assert "PARTITION BY country_iso2" in sql
    assert "country_rank <= :country_cap" in sql


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

    assert counter.labels_seen == [{"detection_method": "peer_anomaly", "reason": "cold"}]
    assert counter.inc_seen == [1]
