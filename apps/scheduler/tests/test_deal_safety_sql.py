"""Regression checks for deal publication safety.

These tests intentionally inspect the SQL text. The production bugs here were
caused by SQL branches that inserted/published semantically invalid deals; a
small string-level guard catches future edits before they hit a live DB.
"""

from __future__ import annotations

import importlib

from shared.deal_detection import DATE_DIP_POLICY

detect_deals = importlib.import_module("src.jobs.detect_deals")
post_deals = importlib.import_module("src.jobs.post_deals")
notify_subscribers = importlib.import_module("src.jobs.notify_subscribers")
refresh_worker = importlib.import_module("src.jobs.refresh_worker")
price_insert = importlib.import_module("src.services.price_insert")


def test_post_deals_never_selects_zero_discount_or_bucket_only_rows() -> None:
    sql = post_deals._SELECT_UNPOSTED.text

    assert "d.discount_pct >= :min_discount_pct" in sql
    assert "d.detection_method NOT LIKE 'bucket_%'" in sql
    assert "d.detection_method != 'peer_anomaly'" in sql
    assert "d.detected_at >= NOW() - INTERVAL '6 hours'" in sql
    assert "d.telegram_msg_id IS NULL" in sql


def test_post_deals_retries_stale_inflight_claims() -> None:
    select_sql = post_deals._SELECT_UNPOSTED.text
    claim_sql = post_deals._CLAIM_FOR_POSTING.text

    assert "d.telegram_msg_id IS NULL" in select_sql
    assert "d.telegram_msg_id = :pending_msg_id" in select_sql
    assert "d.telegram_claimed_at" in select_sql
    assert "make_interval(mins => CAST(:claim_ttl_minutes AS INTEGER))" in select_sql

    assert "telegram_claimed_at = NOW()" in claim_sql
    assert "telegram_msg_id = :pending_msg_id" in claim_sql
    assert "telegram_claimed_at" in claim_sql
    assert "make_interval(mins => CAST(:claim_ttl_minutes AS INTEGER))" in claim_sql


def test_post_deals_selects_short_hotel_context_fields() -> None:
    sql = post_deals._SELECT_UNPOSTED.text

    assert "h.description_uk" in sql
    assert "h.canonical_slug" in sql
    assert "h.review_score" in sql
    assert "h.review_count" in sql


def test_post_deals_marks_only_still_unposted_rows() -> None:
    sql = post_deals._MARK_POSTED.text

    assert "WHERE id = :deal_id" in sql
    assert "posted_at IS NULL" in sql


def test_post_deals_records_accepted_telegram_send_without_pending_sentinel() -> None:
    sql = post_deals._MARK_POSTED.text

    assert "SET posted_at = NOW()" in sql
    assert "telegram_msg_id = :msg_id" in sql
    assert "telegram_claimed_at = NULL" in sql
    assert "telegram_msg_id = :pending_msg_id" not in sql


def test_post_deals_claims_rows_before_external_send() -> None:
    claim_sql = post_deals._CLAIM_FOR_POSTING.text
    release_sql = post_deals._RELEASE_POSTING_CLAIM.text

    assert "UPDATE deals" in claim_sql
    assert "telegram_msg_id = :pending_msg_id" in claim_sql
    assert "telegram_claimed_at = NOW()" in claim_sql
    assert "posted_at IS NULL" in claim_sql
    assert "telegram_msg_id IS NULL" in claim_sql
    assert "RETURNING id" in claim_sql

    assert "SET telegram_msg_id = NULL" in release_sql
    assert "telegram_claimed_at = NULL" in release_sql
    assert "telegram_msg_id = :pending_msg_id" in release_sql


def test_notify_subscribers_discount_floor() -> None:
    sql = notify_subscribers._MATCH_SQL.text

    assert "d.detected_at >= NOW() - make_interval(hours => :freshness_hours)" in sql
    assert "d.discount_pct >= :min_discount_pct" in sql
    assert "d.detection_method = 'peer_anomaly'" in sql
    assert "d.discount_pct >= :min_peer_discount_pct" in sql
    assert "d.detection_method != 'peer_anomaly'" in sql
    assert "f.meal_plan IS NULL" in sql
    assert "d.meal_plan = f.meal_plan" in sql
    assert "f.meal_plan = 'all_inclusive'" in sql
    assert "d.meal_plan IN ('AI', 'UAI')" in sql


def test_notify_subscribers_uses_sent_ledger_not_scalar_cursor() -> None:
    match_sql = notify_subscribers._MATCH_SQL.text
    mark_sql = notify_subscribers._MARK_NOTIFIED.text

    assert "telegram_filter_notifications" in match_sql
    assert "NOT EXISTS" in match_sql
    assert "n.filter_id = f.id" in match_sql
    assert "n.deal_id = d.id" in match_sql
    assert "d.id > f.last_notified_deal_id" not in match_sql
    assert "ORDER BY f.id, d.discount_pct DESC, d.id DESC" in match_sql

    assert "INSERT INTO telegram_filter_notifications" in mark_sql
    assert "ON CONFLICT DO NOTHING" in mark_sql
    assert "GREATEST(" in mark_sql


def test_promo_discount_branch_requires_real_operator_strike_through() -> None:
    sql = detect_deals._PROMO_DISCOUNT_SQL.text

    assert "FROM promo_offers po" in sql
    assert "po.red_price_uah IS NOT NULL" in sql
    assert "po.red_price_uah > po.price_uah" in sql
    assert "ROUND(100 * (1 - po.price_uah::numeric / po.red_price_uah), 2)" in sql
    assert "'promo_discount'" in sql
    assert "'bucket_'" not in sql


def test_date_dip_branch_detects_same_hotel_date_mispricing() -> None:
    """date_dip = one calendar date sharply cheaper than nearby dates for
    the same hotel + nights + meal combo."""
    sql = detect_deals._DATE_DIP_SQL.text

    assert "'calendar_anomaly'" in sql
    # Trimmed local baseline (interquartile mean) replaces the plain
    # local comparison that Farvater's synthetic "sold out" placeholder prices
    # were inflating. Both PERCENT_RANK and the 0.25..0.75 filter must
    # be present or the false-positive 70-80% deals come back.
    assert "PERCENT_RANK()" in sql
    assert "rnk BETWEEN 0.25 AND 0.75" in sql
    assert "local_stats" in sql
    assert (
        "neighbor.check_in BETWEEN "
        f"cp.check_in - INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'" in sql
    )
    assert "neighbor.check_in <> cp.check_in" in sql
    assert "room_family" in sql
    assert "neighbor.room_family = cp.room_family" in sql
    assert "GROUP BY neighbor.check_in" in sql
    assert "neighbor.room_category = cp.room_category" not in sql
    assert f"trimmed_mean * {DATE_DIP_POLICY.discount_multiplier_sql}" in sql
    assert f"(cp.trimmed_mean - cp.price_uah) >= {DATE_DIP_POLICY.min_absolute_saving_uah}" in sql
    assert "long_cp.nights > short_cp.nights" not in sql
    # Per-country diversity guard (without it the top-N by % is dominated
    # by whichever single country has the steepest drops).
    assert "PARTITION BY country_iso2" in sql
    assert "country_rank <= :country_cap" in sql


def test_date_dip_lateral_neighbor_search_keeps_current_prices_indexable() -> None:
    sql = detect_deals._DATE_DIP_SQL.text

    assert "FROM current_prices neighbor" in sql
    assert "FROM priced neighbor" not in sql
    assert "neighbor.room_family = cp.room_family" in sql
    assert "GROUP BY neighbor.check_in" in sql
    assert "regexp_replace" not in sql


def test_shared_price_inserts_conflict_on_room_category() -> None:
    snapshot_consts = price_insert.insert_prices.__code__.co_consts
    snapshot_sql = "\n".join(c for c in snapshot_consts if isinstance(c, str))

    expected = "meal_plan, room_category, observed_at"
    assert expected in snapshot_sql
    refresh_sql = "\n".join(
        c for c in refresh_worker._persist_prices.__code__.co_consts if isinstance(c, str)
    )
    assert "INSERT INTO price_observations" not in refresh_sql


def test_active_deal_insert_branch_ignores_daily_natural_key_conflicts() -> None:
    """Manual re-runs must not crash when today's deal already exists."""

    assert "ON CONFLICT DO NOTHING" in detect_deals._DATE_DIP_SQL.text
    assert "ON CONFLICT DO NOTHING" in detect_deals._PROMO_DISCOUNT_SQL.text


def test_promo_discount_metrics_are_recorded_with_real_method(monkeypatch) -> None:
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

    detect_deals._record_inserted([(1, 42, 27.5)], reason="promo_discount")

    assert counter.labels_seen == [
        {"detection_method": "promo_discount", "reason": "promo_discount"}
    ]
    assert counter.inc_seen == [1]
