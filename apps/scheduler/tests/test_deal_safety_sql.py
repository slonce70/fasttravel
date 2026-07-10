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


def test_promo_discount_branch_enforces_publication_floor() -> None:
    """Promos below the broadcast floor are never published by post_deals or
    notify_subscribers, yet would still arm the 24h per-hotel cooldown — so
    they must not be inserted at all, and all three jobs must share one floor."""
    sql = detect_deals._PROMO_DISCOUNT_SQL.text

    assert "cand.discount_pct >= :min_discount_pct" in sql
    assert "cand.discount_pct > 0" not in sql
    assert detect_deals.MIN_BROADCAST_DISCOUNT_PCT == post_deals.MIN_BROADCAST_DISCOUNT_PCT
    assert post_deals.MIN_BROADCAST_DISCOUNT_PCT == notify_subscribers.MIN_ALERT_DISCOUNT_PCT


def test_promo_discount_budget_is_spent_by_discount_depth_not_hotel_id() -> None:
    """LIMIT must apply to an outer ORDER BY discount_pct DESC (two-level
    pattern, like the date-dip query); the hotel_id-led inner ORDER BY exists
    only to satisfy DISTINCT ON and must not decide who gets budget slots."""
    sql = detect_deals._PROMO_DISCOUNT_SQL.text

    inner = sql.index("ORDER BY cand.hotel_id, cand.discount_pct DESC")
    outer = sql.index("ORDER BY discount_pct DESC, hotel_id")
    assert inner < outer < sql.index("LIMIT :max_per_run")


def test_detectors_exclude_already_stored_deals_from_ranking() -> None:
    """Natural-key anti-join: a persistent deal already present in `deals`
    would only hit ON CONFLICT DO NOTHING, so it must be dropped before it
    burns a country-cap/LIMIT slot that a genuinely new deal needs."""
    for sql, method in (
        (detect_deals._DATE_DIP_SQL.text, "'calendar_anomaly'"),
        (detect_deals._PROMO_DISCOUNT_SQL.text, "'promo_discount'"),
    ):
        anti_join = (
            "WHERE d.hotel_id = cand.hotel_id"
            " AND d.check_in = cand.check_in"
            " AND d.nights = cand.nights"
            " AND d.meal_plan = cand.meal_plan"
            f" AND d.detection_method = {method}"
        )
        assert anti_join in " ".join(sql.split())


def test_date_dip_branch_detects_same_hotel_date_mispricing() -> None:
    """date_dip = one calendar date that is a genuine local V-bottom: cheaper
    than the surrounding dates of the same hotel/operator/nights/meal/room
    family, with both shoulders at one matching price level."""
    sql = detect_deals._DATE_DIP_SQL.text

    assert "'calendar_anomaly'" in sql
    # Regime-local two-sided detector: the shared CTE chain plus the magnitude
    # gates the caller applies on top of `local_stats`.
    assert "local_stats" in sql
    assert "f.price_uah < f.prec_min" in sql
    assert "f.price_uah < f.foll_min" in sql
    assert "f.prec_n >= 3" in sql
    assert "f.foll_n >= 3" in sql
    # Return-to-baseline guard rejects seasonal steps (two different regimes).
    assert "GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) * 1.15" in sql
    # Magnitude gates: dip threshold, glitch-cliff depth cap, absolute saving.
    assert f"cp.discount_pct >= {DATE_DIP_POLICY.dip_threshold_pct_sql}" in sql
    assert f"cp.discount_pct <= {DATE_DIP_POLICY.max_depth_pct_sql}" in sql
    assert f"(cp.baseline_p50 - cp.price_uah) >= {DATE_DIP_POLICY.min_absolute_saving_uah}" in sql
    # The old whole-season / trimmed-mean / lateral-neighbor design is gone.
    assert "PERCENT_RANK()" not in sql
    assert "rnk BETWEEN 0.25 AND 0.75" not in sql
    assert "trimmed_mean" not in sql
    assert "neighbor" not in sql
    assert "long_cp.nights > short_cp.nights" not in sql
    # Per-country diversity guard (without it the top-N by % is dominated
    # by whichever single country has the steepest drops).
    assert "PARTITION BY country_iso2" in sql
    assert "country_rank <= :country_cap" in sql


def test_date_dip_reads_current_prices_via_shared_cte_chain() -> None:
    sql = detect_deals._DATE_DIP_SQL.text

    # Builds on the shared CTE chain that scans current_prices directly and
    # collapses same-room casing duplicates before the per-date family MIN.
    assert "FROM current_prices cp" in sql
    assert "series AS" in sql
    assert "framed AS" in sql
    assert "MAX(cp.price_uah)" in sql
    assert "lower(btrim(cp.room_category))" in sql
    # No per-neighbour recomputation / regex normalization on the hot path.
    assert "neighbor" not in sql
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
