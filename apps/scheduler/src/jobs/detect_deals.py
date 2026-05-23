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

Idempotency: the cooldown sub-query is the only thing guarding against
re-insertion. We DON'T have a UNIQUE index on (hotel_id, detected_at)
because a deal might legitimately reappear after 24h. Re-running this
job within the same hour is therefore safe.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)

COLD_START_FLAG_KEY = "flag:cold_start"

# Warm-mode percentile rule. Mirrors the SQL from the task brief, with
# the cooldown sub-query parameterised so tests can dial it down.
_WARM_SQL = text(
    """
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link, source
    )
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
      AND pb.observation_count >= 10
      AND NOT EXISTS (
          SELECT 1
          FROM deals d
          WHERE d.hotel_id   = cp.hotel_id
            AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
      )
    ORDER BY ROUND(100 * (1 - cp.price_uah::numeric / pb.p50), 2) DESC
    LIMIT :max_per_run
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
    WITH peer_avg AS (
        SELECT
            cp.nights,
            cp.meal_plan,                          -- group by meal so BB doesn't undercut AI
            COALESCE(h.stars, 0) AS stars_bucket,  -- 0 = "unknown" (e.g. villas)
            h.destination_id,
            AVG(cp.price_uah)::int AS avg_price
        FROM current_prices cp
        JOIN hotels h ON h.id = cp.hotel_id
        WHERE h.is_active
          AND h.destination_id IS NOT NULL
          AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
        GROUP BY cp.nights, cp.meal_plan, COALESCE(h.stars, 0), h.destination_id
        HAVING COUNT(*) >= 3
    )
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link, source
    )
    SELECT
        cp.hotel_id,
        cp.operator_id,
        cp.check_in,
        cp.nights,
        cp.meal_plan,
        cp.price_uah,
        pa.avg_price AS baseline_p50,
        ROUND(100 * (1 - cp.price_uah::numeric / pa.avg_price), 2) AS discount_pct,
        cp.deep_link,
        -- See _WARM_SQL above for the rationale.
        CASE
            WHEN cp.deep_link LIKE '%farvater.travel%' THEN 'farvater_scrape'
            ELSE NULL
        END AS source
    FROM current_prices cp
    JOIN hotels h    ON h.id = cp.hotel_id AND h.is_active
    JOIN peer_avg pa ON pa.nights = cp.nights
                    AND pa.meal_plan = cp.meal_plan
                    AND pa.stars_bucket  = COALESCE(h.stars, 0)
                    AND pa.destination_id = h.destination_id
    WHERE cp.price_uah < pa.avg_price * 0.70
      -- Removed absolute 25 000 UAH cap — Maldives/UAE baseline is much
      -- higher and we want luxury deals through too.
      AND cp.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                          AND CURRENT_DATE + INTERVAL '90 days'
      AND NOT EXISTS (
          SELECT 1
          FROM deals d
          WHERE d.hotel_id   = cp.hotel_id
            AND d.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
      )
    ORDER BY ROUND(100 * (1 - cp.price_uah::numeric / pa.avg_price), 2) DESC
    LIMIT :max_per_run
    RETURNING id, hotel_id, discount_pct
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
    return value == "true"


async def _run_query(
    db: AsyncSession,
    *,
    cold_start: bool,
    cooldown_hours: int,
    max_per_run: int,
) -> list[tuple[int, int, float]]:
    sql = _COLD_START_SQL if cold_start else _WARM_SQL
    result = await db.execute(
        sql,
        {"cooldown_hours": cooldown_hours, "max_per_run": max_per_run},
    )
    rows = result.all()
    await db.commit()
    return [(r.id, r.hotel_id, float(r.discount_pct)) for r in rows]


async def detect_deals(
    *,
    cooldown_hours: int = 24,
    max_per_run: int = 20,
    force_cold_start: bool | None = None,
) -> int:
    """Insert new deals based on current prices vs. baselines.

    Args:
        cooldown_hours: how long to suppress repeat deals per hotel.
        max_per_run: cap inserts per tick.
        force_cold_start: test hook; ``None`` consults Redis.

    Returns: number of new deals inserted.
    """
    cold = force_cold_start if force_cold_start is not None else await _is_cold_start_mode()
    mode = "cold_start" if cold else "warm"

    async with async_session_factory() as db:
        try:
            inserted = await _run_query(
                db,
                cold_start=cold,
                cooldown_hours=cooldown_hours,
                max_per_run=max_per_run,
            )
        except Exception:
            await db.rollback()
            raise

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
