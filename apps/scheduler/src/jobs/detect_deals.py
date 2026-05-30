"""Insert public-notification-worthy signals into ``deals``.

The primary detector is ``date_dip``. It compares each current price with
nearby check-in dates for the same hotel, operator, nights, meal plan, and
materialized room-family/quality/view bucket, then inserts honest
``calendar_anomaly`` deals only when that local baseline is trustworthy.

The secondary detector promotes real operator strike-through offers from
``promo_offers`` into ``promo_discount`` deals only when Farvater provides a
true red price above the current price. Bucket-only promo flags stay in
``/api/promotions`` and are not treated as deals.

Historical ``detection_method`` values such as ``percentile`` and
``peer_anomaly`` remain part of the API/UI contract for existing rows, but this
job no longer schedules those legacy peer/history SQL branches.

Idempotency: a per-hotel cooldown suppresses repeat detections within the
configured window, a natural-key anti-join drops already-detected deals before
they can occupy country-cap/LIMIT slots, and any residual insert race is
absorbed by ``ON CONFLICT DO NOTHING`` so re-running this job is safe.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.deal_detection import (
    DATE_DIP_POLICY,
    PROMO_MAX_DISCOUNT_PCT,
    date_dip_local_v_cte_sql,
)
from shared.deal_signals import metric_detection_method_for_reason
from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.post_deals import MIN_BROADCAST_DISCOUNT_PCT

# Inserted-deal tuple: (deal_id, hotel_id, discount_pct). Hoisted into
# a type alias because the strategy runners + record helper all use it.
_RowList = list[tuple[int, int, float]]

log = get_logger(__name__)

_DATE_DIP_COUNTRY_CAP = 5
"""Per-country cap inside one detect_deals tick. With 11 catalogue countries
x 5 = 55 candidate slots, the global LIMIT of 50 below keeps the absolute
top across the whole pool while still surfacing 2-3 different countries
instead of "all Egypt"."""


# Same-hotel calendar-anomaly detector — regime-local two-sided V dip.
# Reads `current_prices` directly via the shared CTE chain (so the channel and
# the web calendar share one definition of "cheap date"), requires a true local
# valley with matching shoulders, and inserts `calendar_anomaly`.
_DATE_DIP_SQL = text(
    f"""
    WITH {date_dip_local_v_cte_sql()}
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    -- Per-country cap: without it the global ORDER BY discount_pct DESC
    -- favors whichever country has the steepest % drops, so the public
    -- channel reads as "Egypt + Egypt + Egypt". ROW_NUMBER OVER(PARTITION BY
    -- country_iso2) limits each country to :country_cap entries per tick, then
    -- the outer LIMIT picks the overall top-N across that diverse pool.
    SELECT
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    FROM (
        SELECT
            per_hotel.*,
            ROW_NUMBER() OVER (
                PARTITION BY country_iso2 ORDER BY discount_pct DESC, hotel_id
            ) AS country_rank
        FROM (
            -- Best *traveler* offer per hotel after the cooldown filter:
            -- cheapest real price first, then the steeper discount, then the
            -- sooner check-in, then deterministic keys so the published row
            -- is stable across runs. Highest-discount alone would prefer a
            -- pricier room just because its local dip is a touch deeper.
            SELECT DISTINCT ON (cand.hotel_id)
                cand.hotel_id,
                cand.operator_id,
                cand.check_in,
                cand.nights,
                cand.meal_plan,
                cand.room_category,
                cand.price_uah,
                cand.baseline_p50,
                cand.discount_pct,
                cand.deep_link,
                cand.country_iso2,
                'farvater_scrape' AS source,
                'calendar_anomaly' AS detection_method
            FROM (
                SELECT
                    cp.hotel_id,
                    cp.operator_id,
                    cp.check_in,
                    cp.nights,
                    cp.meal_plan,
                    cp.room_category,
                    cp.price_uah,
                    cp.baseline_p50,
                    cp.discount_pct,
                    cp.deep_link,
                    dest.country_iso2 AS country_iso2
                FROM local_stats cp
                JOIN hotels h ON h.id = cp.hotel_id
                LEFT JOIN destinations dest ON dest.id = h.destination_id
                WHERE cp.discount_pct >= {DATE_DIP_POLICY.dip_threshold_pct_sql}
                  AND cp.discount_pct <= {DATE_DIP_POLICY.max_depth_pct_sql}
                  AND (cp.baseline_p50 - cp.price_uah) >= {DATE_DIP_POLICY.min_absolute_saving_uah}
            ) cand
            WHERE cand.country_iso2 IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM deals d
                  WHERE d.hotel_id = cand.hotel_id
                    AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
              )
              -- Natural-key anti-join (uq_deals_natural_key is date-free since
              -- migration 023): a persistent dip already stored in `deals` would
              -- only hit ON CONFLICT DO NOTHING, so drop it here before it burns
              -- a country-cap/LIMIT slot that a genuinely new deal needs.
              AND NOT EXISTS (
                  SELECT 1
                  FROM deals d
                  WHERE d.hotel_id = cand.hotel_id
                    AND d.check_in = cand.check_in
                    AND d.nights = cand.nights
                    AND d.meal_plan = cand.meal_plan
                    AND d.detection_method = 'calendar_anomaly'
              )
            -- Best *traveler* offer per hotel: cheapest real price first, then
            -- the steeper discount, then the sooner check-in, then
            -- deterministic keys so the published row is stable across runs.
            -- Highest-discount alone would prefer a pricier room just because
            -- its local dip is a touch deeper. Every candidate here already
            -- passed the dip/depth/absolute-saving gates above.
            ORDER BY
                cand.hotel_id,
                cand.price_uah ASC,
                cand.discount_pct DESC,
                cand.check_in ASC,
                cand.nights ASC,
                cand.meal_plan ASC,
                cand.operator_id ASC,
                cand.room_category ASC
        ) per_hotel
    ) ranked
    WHERE country_rank <= :country_cap
    ORDER BY discount_pct DESC, hotel_id
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct, detection_method
    """
)


_PROMO_DISCOUNT_SQL = text(
    f"""
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    SELECT
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    FROM (
        SELECT DISTINCT ON (cand.hotel_id)
            cand.hotel_id,
            cand.operator_id,
            cand.check_in,
            cand.nights,
            cand.meal_plan,
            cand.price_uah,
            cand.red_price_uah AS baseline_p50,
            cand.discount_pct,
            cand.deep_link,
            'farvater_scrape' AS source,
            'promo_discount' AS detection_method
        FROM (
            SELECT
                po.hotel_id,
                po.operator_id,
                po.check_in,
                po.nights,
                po.meal_plan,
                po.price_uah,
                po.red_price_uah,
                ROUND(100 * (1 - po.price_uah::numeric / po.red_price_uah), 2)
                    AS discount_pct,
                'https://farvater.travel/?q=' || po.system_key AS deep_link
            FROM promo_offers po
            WHERE po.observed_at >= NOW() - INTERVAL '24 hours'
              AND po.red_price_uah IS NOT NULL
              AND po.red_price_uah > po.price_uah
              AND po.price_uah > 0
              AND po.operator_id IS NOT NULL
              AND po.check_in BETWEEN CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_start_days} days'
                                  AND CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_end_days} days'
        ) cand
        -- Publication floor: both consumers (post_deals / notify_subscribers)
        -- drop deals below MIN_BROADCAST_DISCOUNT_PCT, so a shallower promo
        -- would never be published yet still arm the per-hotel cooldown.
        -- Implausibility ceiling: a strike-through deeper than
        -- PROMO_MAX_DISCOUNT_PCT is almost always an inflated anchor, not a
        -- real saving — refuse to store it as a deal at all.
        WHERE cand.discount_pct >= :min_discount_pct
          AND cand.discount_pct <= {PROMO_MAX_DISCOUNT_PCT}
          AND NOT EXISTS (
              SELECT 1
              FROM deals d
              WHERE d.hotel_id = cand.hotel_id
                AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
          )
          -- Natural-key anti-join, same rationale as in the date-dip query:
          -- an already-stored promo must not burn a LIMIT slot only to hit
          -- ON CONFLICT DO NOTHING.
          AND NOT EXISTS (
              SELECT 1
              FROM deals d
              WHERE d.hotel_id = cand.hotel_id
                AND d.check_in = cand.check_in
                AND d.nights = cand.nights
                AND d.meal_plan = cand.meal_plan
                AND d.detection_method = 'promo_discount'
          )
        ORDER BY cand.hotel_id, cand.discount_pct DESC, cand.price_uah ASC
    ) per_hotel
    -- DISTINCT ON forces hotel_id to lead the inner ORDER BY, so the LIMIT
    -- budget is applied out here by discount depth (same two-level pattern
    -- as the date-dip query) instead of by whichever hotels have low ids.
    ORDER BY discount_pct DESC, hotel_id
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct, detection_method
    """
)


def _record_inserted(rows: list[tuple[int, int, float]], reason: str) -> None:
    """Best-effort Prometheus increment for the deal-insert counter.
    Metric publishing must never crash a job, so all errors are swallowed."""
    if not rows:
        return
    try:
        from src.infra.metrics import DEALS_INSERTED

        # Map reason → detection_method label so the counter mirrors the
        # DB column. The reason label is the sub-branch within a method.
        method = metric_detection_method_for_reason(reason)
        DEALS_INSERTED.labels(detection_method=method, reason=reason).inc(len(rows))
    except Exception:  # noqa: BLE001
        log.exception("detect_deals.metric_write_failed", reason=reason)


async def detect_deals(
    *,
    cooldown_hours: int = 24,
    max_per_run: int = 50,
) -> int:
    """Insert date-dip calendar anomalies and real promo discounts.

    Args:
        cooldown_hours: how long to suppress repeat deals per hotel.
        max_per_run: cap inserts per tick.

    Returns: number of new deals inserted.
    """
    async with async_session_factory() as db:
        try:
            inserted = await _run_date_dip_query(db, cooldown_hours, max_per_run)
            promo_budget = max(0, max_per_run - len(inserted))
            promo_inserted = (
                await _run_promo_discount_query(db, cooldown_hours, promo_budget)
                if promo_budget
                else []
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    _record_inserted(inserted, reason="date_dip")
    _record_inserted(promo_inserted, reason="promo_discount")

    total_inserted = len(inserted) + len(promo_inserted)
    mode = f"date_dip(date_dip={len(inserted)}, promo_discount={len(promo_inserted)})"

    if total_inserted:
        top = max([*inserted, *promo_inserted], key=lambda r: r[2])
        log.info(
            "detect_deals.completed",
            inserted=total_inserted,
            mode=mode,
            top_hotel_id=top[1],
            top_discount_pct=top[2],
        )
    else:
        log.info("detect_deals.completed", inserted=0, mode=mode)
    return total_inserted


async def _run_date_dip_query(db: AsyncSession, cooldown_hours: int, max_per_run: int) -> _RowList:
    result = await db.execute(
        _DATE_DIP_SQL,
        {
            "cooldown_hours": cooldown_hours,
            "max_per_run": max_per_run,
            "country_cap": _DATE_DIP_COUNTRY_CAP,
        },
    )
    rows = result.all()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]


async def _run_promo_discount_query(
    db: AsyncSession, cooldown_hours: int, max_per_run: int
) -> _RowList:
    result = await db.execute(
        _PROMO_DISCOUNT_SQL,
        {
            "cooldown_hours": cooldown_hours,
            "max_per_run": max_per_run,
            "min_discount_pct": MIN_BROADCAST_DISCOUNT_PCT,
        },
    )
    rows = result.all()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]
