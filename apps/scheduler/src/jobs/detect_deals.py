"""Insert new rows into ``deals`` from current MVs (ADR-006).

Two execution modes:

* **Warm**  (default) — percentile rule against ``price_baselines``.
  Requires per-bucket ``observation_count >= 10``, so it kicks in only
  after a couple of weeks of snapshot history.

* **Cold-start** — destination/stars heuristic. Triggered by the Redis
  feature flag ``flag:cold_start`` (value ``"true"``). Designed for the
  first ~30 days of operation when ``price_baselines`` is too sparse to
  trust. ADR-006 documents the rule: ``price < 0.70 × average price for
  the same destination × stars × nights`` AND a hard absolute floor so we
  don't broadcast every all-inclusive tour to Bukovel.

Both modes share:
  - check_in window: +5 .. +90 days
  - per-hotel 24h cooldown (so we don't spam the same hotel)
  - LIMIT 20 (one tick floods the channel otherwise)

Idempotency: a per-hotel cooldown sub-query suppresses repeat detections
within the configured window. Migration 014 also adds
`uq_deals_natural_key_day` over
`(hotel_id, check_in, nights, meal_plan, detection_method, day(detected_at))`,
so same-day re-detection of the same key in the same method is silently
ignored via `ON CONFLICT DO NOTHING`. Re-running this job within the same
hour is therefore safe.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.deal_signals import metric_detection_method_for_reason
from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

# Inserted-deal tuple: (deal_id, hotel_id, discount_pct). Hoisted into
# a type alias because the strategy runners + record helper all use it.
_RowList = list[tuple[int, int, float]]

log = get_logger(__name__)

COLD_START_FLAG_KEY = "flag:cold_start"

# Sprint 1D feature flag. Default OFF until ops verify the bucket branch
# end-to-end (one tick + manual inspection of `deals.detection_method`).
# When OFF the third branch is skipped entirely.
BUCKETS_FLAG_ENV = "FT_DEAL_DETECTION_BUCKETS_ENABLED"

# Stage 1 (post-audit) feature flag. The `longer_stay_cheaper` branch of
# the calendar-anomaly detector tends to fire on legitimate package-tour
# pricing (operators routinely discount longer stays for occupancy), not
# on cost mistakes. Defaults OFF until we observe real overlap rate via
# the DEALS_INSERTED{reason="stay_inversion"} counter; ops flip the
# Redis key `flag:stay_inversion_enabled` to "true" to enable.
STAY_INVERSION_FLAG_KEY = "flag:stay_inversion_enabled"


def _buckets_enabled() -> bool:
    return os.getenv(BUCKETS_FLAG_ENV, "").strip().lower() in ("1", "true", "yes", "on")


# Warm-mode percentile rule. Mirrors the SQL from the task brief, with
# the cooldown sub-query parameterised so tests can dial it down.
_WARM_SQL = text(
    """
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link, source,
        detection_method
    )
    -- DISTINCT ON (hotel_id) collapses per-hotel candidates to the single
    -- highest-discount row. Without it the NOT EXISTS sub-query — which
    -- can't see rows being inserted in the same statement — lets the same
    -- hotel produce N deals (one per qualifying check_in/nights/meal).
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id,
        cand.operator_id,
        cand.check_in,
        cand.nights,
        cand.meal_plan,
        cand.price_uah,
        cand.p50,
        cand.discount_pct,
        cand.deep_link,
        cand.source,
        'percentile' AS detection_method
    FROM (
        SELECT
            cp.hotel_id,
            cp.operator_id,
            cp.check_in,
            cp.nights,
            cp.meal_plan,
            cp.price_uah,
            pb.p50,
            ROUND(100 * (1 - cp.price_uah::numeric / pb.p50), 2) AS discount_pct,
            cp.deep_link,
            -- Tag the deal's provenance so the Telegram broadcast can filter
            -- (migration 004). farvater deep-links are unmistakable; anything
            -- else is either synthetic seed (NULL stays NULL → broadcast
            -- skips) or a future operator (handled then).
            CASE
                WHEN cp.deep_link LIKE '%farvater.travel%' THEN 'farvater_scrape'
                ELSE NULL
            END AS source
        FROM current_prices cp
        JOIN price_baselines pb
            ON  pb.hotel_id        = cp.hotel_id
            AND pb.nights          = cp.nights
            AND pb.meal_plan       = cp.meal_plan
            AND pb.check_in_month  = EXTRACT(MONTH FROM cp.check_in)::int
        WHERE cp.price_uah < pb.p15
          AND cp.price_uah < pb.p50 * 0.85
          AND (pb.p50 - cp.price_uah) >= 2000
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
          -- Sprint 3.2 — restored to spec value (10). At n=5 the
          -- p15 via percentile_disc is just the minimum, which biases
          -- against hotels with legitimately recurring monthly sales
          -- (each sale = "lower than every prior observation" by
          -- definition, so the rule fires on every recurrence rather
          -- than the genuinely anomalous ones). The Warm rule needs a
          -- few weeks of price history to become useful regardless;
          -- 10 vs 5 trades a few extra days of cold-only behaviour for
          -- substantially less noise once it does fire.
          AND pb.observation_count >= 10
          AND NOT EXISTS (
              SELECT 1
              FROM deals d
              WHERE d.hotel_id   = cp.hotel_id
                AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
          )
    ) cand
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct
    """
)

# Cold-start heuristic. The peer group is "same destination × stars × nights"
# (not meal_plan — too narrow during bootstrap). Hard ceiling of 25 000 UAH
# matches MVP's "cheap weekend deal" target audience; tune per launch market.
#
# baseline_p50 is filled with the peer-average so the deals table is still
# meaningful downstream. discount_pct uses the same formula.
_COLD_START_SQL = text(
    """
    -- Peer stats per (nights, meal, stars, destination) bucket. We compute
    -- both the median (p50) and a robust spread (p25..p75) so the deal
    -- threshold can scale with each bucket's natural price variance — a
    -- single overpriced 5* villa shouldn't bend an Aegean-Bay 3* avg.
    --
    -- COUNT(*) >= 5 keeps the bucket statistically usable. Below that the
    -- median is just a single arbitrary row.
    WITH peer_stats AS (
        SELECT
            cp.nights,
            cp.meal_plan,                          -- group by meal so BB doesn't undercut AI
            COALESCE(h.stars, 0) AS stars_bucket,  -- 0 = "unknown" (e.g. villas)
            h.destination_id,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cp.price_uah)::int  AS p50,
            PERCENTILE_CONT(0.15) WITHIN GROUP (ORDER BY cp.price_uah)::int AS p15,
            COUNT(*)                                                         AS sample_n
        FROM current_prices cp
        JOIN hotels h ON h.id = cp.hotel_id
        WHERE h.is_active
          AND h.destination_id IS NOT NULL
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
        GROUP BY cp.nights, cp.meal_plan, COALESCE(h.stars, 0), h.destination_id
        HAVING COUNT(*) >= 5
    )
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link, source,
        detection_method
    )
    -- DISTINCT ON (hotel_id): same cooldown-within-batch issue as warm mode —
    -- without it the cold-start rule emits one row per qualifying check_in.
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id, cand.operator_id, cand.check_in, cand.nights, cand.meal_plan,
        cand.price_uah, cand.baseline_p50, cand.discount_pct, cand.deep_link, cand.source,
        -- Cold-start fires on PEER comparison (other hotels in the same
        -- destination+stars+meal+nights bucket), not on this hotel's own
        -- history. Tagging it 'peer_anomaly' lets every downstream
        -- surface (post_deals broadcast filter, /api/deals UI, bot
        -- templates) treat it appropriately — it's a weaker signal than
        -- date_dip / warm percentile and the user copy reflects that.
        'peer_anomaly' AS detection_method
    FROM (
        SELECT
            cp.hotel_id,
            cp.operator_id,
            cp.check_in,
            cp.nights,
            cp.meal_plan,
            cp.price_uah,
            ps.p50 AS baseline_p50,
            ROUND(100 * (1 - cp.price_uah::numeric / ps.p50), 2) AS discount_pct,
            cp.deep_link,
            -- See _WARM_SQL above for the rationale.
            CASE
                WHEN cp.deep_link LIKE '%farvater.travel%' THEN 'farvater_scrape'
                ELSE NULL
            END AS source
        FROM current_prices cp
        JOIN hotels h     ON h.id = cp.hotel_id AND h.is_active
        JOIN peer_stats ps ON ps.nights = cp.nights
                          AND ps.meal_plan = cp.meal_plan
                          AND ps.stars_bucket = COALESCE(h.stars, 0)
                          AND ps.destination_id = h.destination_id
        WHERE
          -- Two stacked conditions — must beat BOTH:
          --   1. p15  → "lower than the cheapest 15% of peers"
          --   2. p50 × 0.75 → "at least 25% below the median"
          -- Stacking them filters out cases where p15 ≈ p50 (tight
          -- peer group with one outlier dragging it down).
          -- Sprint 3.4 — `<` not `<=` for consistency with warm rule.
          -- Boundary equality previously emitted a deal when price
          -- exactly matched p15 ("tied for cheapest"), which isn't
          -- what `< p15` means in the warm path.
          cp.price_uah < ps.p15
          AND cp.price_uah < ps.p50 * 0.75
          -- Absolute headroom so we don't show "-30% on a 1200 UAH bus tour".
          AND (ps.p50 - cp.price_uah) >= 3000
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
          AND NOT EXISTS (
              SELECT 1
              FROM deals d
              WHERE d.hotel_id   = cp.hotel_id
                AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
          )
    ) cand
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct
    """
)


# Promo discount SQL. Promo_offers represent operator-flagged Farvater
# bucket membership, but bucket membership alone is not a measurable
# discount. Only rows with a real strike-through (`red_price_uah > price_uah`)
# are inserted into deals; bucket-only offers stay in /api/promotions.
_BUCKET_SQL = text(
    """
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    -- DISTINCT ON (hotel_id) keeps one best real promo discount per hotel
    -- per tick. Bucket-only rows are not deals and stay in promo_offers.
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id,
        cand.operator_id,
        cand.check_in,
        cand.nights,
        cand.meal_plan,
        cand.price_uah,
        cand.baseline_p50,
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
            po.bucket_slug,
            po.price_uah,
            po.red_price_uah AS baseline_p50,
            ROUND(100 * (1 - po.price_uah::numeric / po.red_price_uah), 2)
                AS discount_pct,
            -- Reconstruct the farvater deep_link from canonical_slug +
            -- destination iso2. Same pattern refresh_worker uses.
            COALESCE(
                'https://farvater.travel/uk/hotel/'
                    || lower(d.country_iso2) || '/'
                    || regexp_replace(h.canonical_slug, '^fv-[a-z]{2}-', '')
                    || '?q=' || po.system_key,
                'https://farvater.travel'
            ) AS deep_link
        FROM promo_offers po
        JOIN hotels h        ON h.id = po.hotel_id
        LEFT JOIN destinations d ON d.id = h.destination_id
        WHERE po.observed_at >= NOW() - INTERVAL '24 hours'
          AND po.red_price_uah IS NOT NULL
          AND po.red_price_uah > po.price_uah
          AND po.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
          AND po.operator_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM deals d2
              WHERE d2.hotel_id = po.hotel_id
                AND d2.detection_method = 'promo_discount'
                AND d2.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
          )
    ) cand
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct, detection_method
    """
)


# Calendar anomaly detector — two independent SQL branches, each
# guardable on its own:
#
# 1. _DATE_DIP_SQL  — same hotel + same nights + same meal has a check-in
#    date far below that hotel's own current calendar distribution.
#    Example: 7 Jun = 600 USD while the rest of the calendar is ~1000 USD.
#    This is the strongest "sweet price" signal — it's an outlier within
#    a single hotel's own pricing, so it cannot be confused with peer-group
#    bias. Always-on.
#
# 2. _STAY_INVERSION_SQL — a longer stay is cheaper than a shorter stay for
#    the same hotel/check-in/meal. Example: 10n cheaper than 7n. In package
#    tourism this is often a legitimate occupancy lever, not a price bug,
#    so this branch is gated by the Redis flag `flag:stay_inversion_enabled`
#    (default OFF). Re-enable after ops confirms the
#    DEALS_INSERTED{reason="stay_inversion"} volume is sensible.
#
# Both branches read `current_prices` directly — they don't need weeks of
# history, only the latest snapshot's calendar shape per hotel.
#
# Each INSERT carries `detection_method='calendar_anomaly'`. The natural
# `uq_deals_natural_key_day` index dedupes same-day same-method
# re-detections; `ON CONFLICT DO NOTHING` handles concurrent writers.
_DATE_DIP_SQL = text(
    """
    WITH hotel_stats AS (
        -- Median price per hotel across all available check-in dates
        -- for the same (nights, meal_plan) combination. A date that is
        -- 10%+ below this median is a deal worth posting.
        SELECT
            cp.hotel_id,
            cp.operator_id,
            cp.nights,
            cp.meal_plan,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cp.price_uah)::int AS p50,
            COUNT(*) AS sample_n
        FROM current_prices cp
        WHERE cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
        GROUP BY cp.hotel_id, cp.operator_id, cp.nights, cp.meal_plan
        HAVING COUNT(*) >= 5
    )
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id,
        cand.operator_id,
        cand.check_in,
        cand.nights,
        cand.meal_plan,
        cand.price_uah,
        cand.baseline_p50,
        cand.discount_pct,
        cand.deep_link,
        'farvater_scrape' AS source,
        'calendar_anomaly' AS detection_method
    FROM (
        SELECT
            cp.hotel_id,
            cp.operator_id,
            cp.check_in,
            cp.nights,
            cp.meal_plan,
            cp.price_uah,
            hs.p50 AS baseline_p50,
            ROUND(100 * (1 - cp.price_uah::numeric / hs.p50), 2) AS discount_pct,
            cp.deep_link
        FROM current_prices cp
        JOIN hotel_stats hs
          ON hs.hotel_id = cp.hotel_id
         AND hs.operator_id = cp.operator_id
         AND hs.nights = cp.nights
         AND hs.meal_plan = cp.meal_plan
        WHERE cp.price_uah < hs.p50 * 0.90
          AND (hs.p50 - cp.price_uah) >= 1500
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
    ) cand
    WHERE cand.discount_pct > 0
      AND NOT EXISTS (
          SELECT 1
          FROM deals d
          WHERE d.hotel_id = cand.hotel_id
            AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
      )
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct, detection_method
    """
)


_STAY_INVERSION_SQL = text(
    """
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id,
        cand.operator_id,
        cand.check_in,
        cand.nights,
        cand.meal_plan,
        cand.price_uah,
        cand.baseline_p50,
        cand.discount_pct,
        cand.deep_link,
        'farvater_scrape' AS source,
        'calendar_anomaly' AS detection_method
    FROM (
        SELECT
            long_cp.hotel_id,
            long_cp.operator_id,
            long_cp.check_in,
            long_cp.nights,
            long_cp.meal_plan,
            long_cp.price_uah,
            short_cp.price_uah AS baseline_p50,
            ROUND(100 * (1 - long_cp.price_uah::numeric / short_cp.price_uah), 2)
                AS discount_pct,
            long_cp.deep_link
        FROM current_prices long_cp
        JOIN current_prices short_cp
          ON short_cp.hotel_id = long_cp.hotel_id
         AND short_cp.operator_id = long_cp.operator_id
         AND short_cp.check_in = long_cp.check_in
         AND short_cp.meal_plan = long_cp.meal_plan
         AND long_cp.nights > short_cp.nights
        WHERE long_cp.price_uah < short_cp.price_uah
          AND long_cp.price_uah < short_cp.price_uah * 0.90
          AND (short_cp.price_uah - long_cp.price_uah) >= 3000
          AND long_cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                                   AND CURRENT_DATE + INTERVAL '90 days'
    ) cand
    WHERE cand.discount_pct > 0
      AND NOT EXISTS (
          SELECT 1
          FROM deals d
          WHERE d.hotel_id = cand.hotel_id
            AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
      )
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    ON CONFLICT DO NOTHING
    RETURNING id, hotel_id, discount_pct, detection_method
    """
)


async def _is_cold_start_mode() -> bool:
    try:
        value = await get_redis().get(COLD_START_FLAG_KEY)
    except Exception as exc:
        # Redis hiccup shouldn't halt the SQL job. Warm mode is the safer
        # default — false positives in cold-start would spam the channel.
        log.warning("detect_deals.flag_read_failed", error=str(exc), default="warm")
        return False
    return bool(value == "true")


async def _is_stay_inversion_enabled() -> bool:
    """Read the stay_inversion feature flag. Default OFF on any error —
    the branch fires on legitimate package-tour pricing patterns, so the
    safe default when Redis is unreachable is to suppress it."""
    try:
        value = await get_redis().get(STAY_INVERSION_FLAG_KEY)
    except Exception as exc:
        log.warning(
            "detect_deals.stay_inversion_flag_read_failed",
            error=str(exc),
            default="disabled",
        )
        return False
    return bool(value == "true")


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


async def _run_query(
    db: AsyncSession,
    *,
    cold_start: bool,
    cooldown_hours: int,
    max_per_run: int,
) -> _RowList:
    sql = _COLD_START_SQL if cold_start else _WARM_SQL
    result = await db.execute(
        sql,
        {"cooldown_hours": cooldown_hours, "max_per_run": max_per_run},
    )
    rows = result.all()
    await db.commit()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]


# Strategy-shaped wrappers (audit #1.2 split): each accepts the same
# (db, cooldown_hours, max_per_run) signature so the orchestration loop
# in `detect_deals()` can iterate over them without per-branch glue.
async def _run_warm_query(db: AsyncSession, cooldown_hours: int, max_per_run: int) -> _RowList:
    return await _run_query(
        db,
        cold_start=False,
        cooldown_hours=cooldown_hours,
        max_per_run=max_per_run,
    )


async def _run_cold_query(db: AsyncSession, cooldown_hours: int, max_per_run: int) -> _RowList:
    return await _run_query(
        db,
        cold_start=True,
        cooldown_hours=cooldown_hours,
        max_per_run=max_per_run,
    )


async def detect_deals(
    *,
    cooldown_hours: int = 24,
    max_per_run: int = 20,
    force_cold_start: bool | None = None,
) -> int:
    """Insert new deals based on current prices vs. baselines.

    Hybrid execution: a list of strategies in priority order, each given
    the remaining budget. The first strategies (bucket / date_dip) carry
    the strongest signal; the last (cold peer-group) only fills leftover
    budget. The shared per-hotel cooldown prevents the same hotel from
    showing up across two strategies on the same tick.

    The Redis `flag:cold_start` toggle still forces cold-only behaviour
    (legacy bootstrap mode for empty databases).

    Args:
        cooldown_hours: how long to suppress repeat deals per hotel.
        max_per_run: cap inserts per tick.
        force_cold_start: test hook; ``None`` consults Redis.

    Returns: number of new deals inserted.
    """
    cold_only = force_cold_start if force_cold_start is not None else await _is_cold_start_mode()

    # Strategy table: only date_dip (calendar anomaly) is active.
    # runner). `enabled` lets the caller toggle a strategy without
    # mutating the loop body. `runner` takes (db, cooldown_hours,
    # max_per_run) and returns the inserted rows.
    #
    # Order matters — earlier strategies consume the per-tick budget
    # first, so the strongest signals lead. This is the same ordering
    # the audit recommended ("BUCKET → DATE_DIP → STAY_INV → WARM →
    # COLD"); now it's data, not control flow.
    strategies: list[tuple[str, bool, Callable[[AsyncSession, int, int], Awaitable[_RowList]]]] = [
        ("date_dip", True, _run_date_dip_query),
    ]

    results: dict[str, _RowList] = {}
    async with async_session_factory() as db:
        try:
            remaining = max_per_run
            for reason, enabled, runner in strategies:
                if not enabled or remaining <= 0:
                    results[reason] = []
                    continue
                rows = await runner(db, cooldown_hours, remaining)
                results[reason] = rows
                _record_inserted(rows, reason=reason)
                remaining -= len(rows)
        except Exception:
            await db.rollback()
            raise

    inserted: _RowList = []
    for _reason, _enabled, _runner in strategies:
        inserted.extend(results[_reason])

    mode_parts = [f"{name}={len(results[name])}" for name, _e, _r in strategies]
    # Append "(off)" suffix on flag-gated strategies that were skipped,
    # mirroring the pre-refactor log line so dashboards keep parsing.
    mode_parts = [
        part + ("(off)" if not enabled else "")
        for part, (name, enabled, _r) in zip(mode_parts, strategies, strict=True)
    ]
    mode = f"{'cold_only' if cold_only else 'hybrid'}({','.join(mode_parts)})"

    if inserted:
        top = max(inserted, key=lambda r: r[2])
        log.info(
            "detect_deals.completed",
            inserted=len(inserted),
            mode=mode,
            top_hotel_id=top[1],
            top_discount_pct=top[2],
        )
    else:
        log.info("detect_deals.completed", inserted=0, mode=mode)
    return len(inserted)


async def _run_bucket_query(db: AsyncSession, cooldown_hours: int, max_per_run: int) -> _RowList:
    result = await db.execute(
        _BUCKET_SQL,
        {"cooldown_hours": cooldown_hours, "max_per_run": max_per_run},
    )
    rows = result.all()
    await db.commit()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]


async def _run_date_dip_query(db: AsyncSession, cooldown_hours: int, max_per_run: int) -> _RowList:
    result = await db.execute(
        _DATE_DIP_SQL,
        {"cooldown_hours": cooldown_hours, "max_per_run": max_per_run},
    )
    rows = result.all()
    await db.commit()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]


async def _run_stay_inversion_query(
    db: AsyncSession, cooldown_hours: int, max_per_run: int
) -> _RowList:
    result = await db.execute(
        _STAY_INVERSION_SQL,
        {"cooldown_hours": cooldown_hours, "max_per_run": max_per_run},
    )
    rows = result.all()
    await db.commit()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]
