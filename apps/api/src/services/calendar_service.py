"""Business logic for hotel calendar heatmap.

Reads from `hotel_calendar_prices` MV (migration 016 onwards: stores
``prices_by_night JSONB`` keyed by stringified night count). The MV
stores raw operator meal codes (``AI``/``UAI``/``HB``/``BB``/``RO``/``FB``);
the API exposes canonical product keys (``all_inclusive``/``half_board``/…).
Translation happens here via :mod:`src.services.meal_normalizer`.
"""

from __future__ import annotations

from datetime import date

from shared.deal_detection import DATE_DIP_POLICY, date_dip_neighbor_stats_lateral_sql
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.calendar import CalendarDay, OfferOut
from src.services.meal_normalizer import raw_codes_for


async def get_calendar(
    session: AsyncSession,
    hotel_id: int,
    from_date: date,
    to_date: date,
    meal_plan: str | None = None,
    nights: int | None = None,
) -> list[CalendarDay]:
    """Return the daily min-price grid for a hotel within a window.

    When ``nights`` is supplied, read from ``current_prices`` and aggregate
    exact offers for that duration; ``prices_by_night`` is then a single-entry
    map ``{str(nights): MIN}`` so the shape stays consistent across callers.
    Without ``nights``, fall back to the ``hotel_calendar_prices`` MV which
    already stores the full ``prices_by_night`` JSONB across nights 7..14.

    * ``meal_plan`` given — accepted as either:

        - canonical key (``all_inclusive``) → expanded to the set of
          raw codes via :func:`meal_normalizer.raw_codes_for`
          (``['AI', 'UAI']``) and then re-aggregated with MIN across
          those rows so the caller sees one row per check-in day for
          the requested product category;
        - raw code (``AI``) → ``['AI']`` (single-row passthrough — keeps
          legacy ``?meal=AI`` callers working unchanged);
        - unknown — passthrough (degrades to literal filter).

    * ``meal_plan`` omitted — re-aggregate with MIN across all
      meal-plan rows so callers still get one row per day.
      ``meal_plan`` in the response is NULL in this branch.

    MIN over per-meal-plan MIN is still a MIN — no double-counting.
    """
    if nights is not None:
        response_meal = (
            "CAST(:requested_meal_plan AS VARCHAR)" if meal_plan is not None else "NULL::VARCHAR"
        )
        meal_filter = "AND cp.meal_plan IN :meal_codes" if meal_plan is not None else ""
        sql = text(
            f"""
            WITH candidate_prices AS (
                SELECT
                    cp.*,
                    MAX(cp.observed_at) OVER (PARTITION BY cp.check_in) AS day_observed_at
                FROM current_prices cp
                WHERE cp.hotel_id = :hotel_id
                  AND cp.check_in BETWEEN :from_date AND :to_date
                  AND cp.nights = :nights
                  {meal_filter}
            ),
            ranked_day_prices AS (
                SELECT
                    cp.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY cp.check_in
                        ORDER BY cp.price_uah, cp.operator_id, cp.meal_plan,
                                 cp.room_family, cp.room_category
                    ) AS price_rank
                FROM candidate_prices cp
            ),
            day_min AS (
                SELECT *
                FROM ranked_day_prices
                WHERE price_rank = 1
            ),
            date_dip_candidates AS (
                SELECT
                    cp.check_in,
                    cp.price_uah,
                    hs.trimmed_mean AS baseline_p50,
                    ROUND((1 - cp.price_uah::numeric / hs.trimmed_mean) * 100, 2) AS discount_pct,
                    hs.sample_n
                FROM candidate_prices cp
                {date_dip_neighbor_stats_lateral_sql(candidate_alias="cp")}
                WHERE cp.check_in BETWEEN CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_start_days} days'
                                      AND CURRENT_DATE + INTERVAL '{DATE_DIP_POLICY.lookahead_end_days} days'
                  AND cp.price_uah < hs.trimmed_mean * {DATE_DIP_POLICY.discount_multiplier_sql}
                  AND cp.price_uah >= hs.trimmed_mean * {DATE_DIP_POLICY.min_price_ratio_sql}
                  AND hs.trimmed_mean - cp.price_uah >= {DATE_DIP_POLICY.min_absolute_saving_uah}
            ),
            best_date_dip AS (
                SELECT DISTINCT ON (check_in)
                    check_in,
                    price_uah,
                    baseline_p50,
                    discount_pct,
                    sample_n
                FROM date_dip_candidates
                ORDER BY check_in, discount_pct DESC, price_uah ASC
            )
            SELECT
                dm.check_in,
                {response_meal} AS meal_plan,
                dm.price_uah AS min_price_uah,
                jsonb_build_object(CAST(:nights_key AS text), dm.price_uah) AS prices_by_night,
                dm.day_observed_at AS observed_at,
                bd.price_uah AS date_dip_price_uah,
                bd.baseline_p50 AS date_dip_baseline_uah,
                bd.discount_pct AS date_dip_discount_pct,
                bd.sample_n AS date_dip_sample_n
            FROM day_min dm
            LEFT JOIN best_date_dip bd ON bd.check_in = dm.check_in
            ORDER BY dm.check_in
            """
        )
        params = {
            "hotel_id": hotel_id,
            "from_date": from_date,
            "to_date": to_date,
            "nights": nights,
            "nights_key": str(nights),
        }
        if meal_plan is not None:
            sql = sql.bindparams(bindparam("meal_codes", expanding=True))
            params["meal_codes"] = raw_codes_for(meal_plan)
            params["requested_meal_plan"] = meal_plan
        rows = (await session.execute(sql, params)).mappings().all()
        return [CalendarDay(**dict(row)) for row in rows]

    if meal_plan is not None:
        codes = raw_codes_for(meal_plan)
        # Re-aggregate with MIN across codes (matters for canonical keys
        # that expand to >1 raw code, e.g. all_inclusive → AI+UAI). The
        # response ``meal_plan`` is NULL because we MIN'd over a set.
        # `prices_by_night` is merged across meals by taking the per-key
        # MIN — pure SQL via jsonb_object_agg over a per-night MIN CTE.
        sql = text(
            """
            WITH per_night AS (
                SELECT
                    hcp.check_in,
                    night_key,
                    MIN((entry.value)::int) AS min_price
                FROM hotel_calendar_prices hcp,
                     LATERAL jsonb_each_text(hcp.prices_by_night) AS entry(night_key, value)
                WHERE hcp.hotel_id = :hotel_id
                  AND hcp.check_in BETWEEN :from_date AND :to_date
                  AND hcp.meal_plan IN :meal_codes
                GROUP BY hcp.check_in, night_key
            ),
            day_min AS (
                SELECT
                    check_in,
                    MIN(min_price) AS min_price_uah,
                    jsonb_object_agg(night_key, min_price) AS prices_by_night
                FROM per_night
                GROUP BY check_in
            )
            SELECT
                dm.check_in,
                CAST(:requested_meal_plan AS VARCHAR) AS meal_plan,
                dm.min_price_uah,
                dm.prices_by_night,
                MAX(hcp.last_observed_at)  AS observed_at
            FROM day_min dm
            JOIN hotel_calendar_prices hcp
              ON hcp.hotel_id = :hotel_id
             AND hcp.check_in = dm.check_in
             AND hcp.meal_plan IN :meal_codes
            GROUP BY dm.check_in, dm.min_price_uah, dm.prices_by_night
            ORDER BY dm.check_in
            """
        ).bindparams(bindparam("meal_codes", expanding=True))
        params = {
            "hotel_id": hotel_id,
            "from_date": from_date,
            "to_date": to_date,
            "meal_codes": codes,
            "requested_meal_plan": meal_plan,
        }
    else:
        # Re-aggregate MIN over meal-plan rows; MAX over observed_at.
        # Same per-night merge pattern as the meal_plan branch above —
        # just without the meal_plan filter.
        sql = text(
            """
            WITH per_night AS (
                SELECT
                    hcp.check_in,
                    night_key,
                    MIN((entry.value)::int) AS min_price
                FROM hotel_calendar_prices hcp,
                     LATERAL jsonb_each_text(hcp.prices_by_night) AS entry(night_key, value)
                WHERE hcp.hotel_id = :hotel_id
                  AND hcp.check_in BETWEEN :from_date AND :to_date
                GROUP BY hcp.check_in, night_key
            ),
            day_min AS (
                SELECT
                    check_in,
                    MIN(min_price) AS min_price_uah,
                    jsonb_object_agg(night_key, min_price) AS prices_by_night
                FROM per_night
                GROUP BY check_in
            )
            SELECT
                dm.check_in,
                NULL::VARCHAR              AS meal_plan,
                dm.min_price_uah,
                dm.prices_by_night,
                MAX(hcp.last_observed_at)  AS observed_at
            FROM day_min dm
            JOIN hotel_calendar_prices hcp
              ON hcp.hotel_id = :hotel_id
             AND hcp.check_in = dm.check_in
            GROUP BY dm.check_in, dm.min_price_uah, dm.prices_by_night
            ORDER BY dm.check_in
            """
        )
        params = {
            "hotel_id": hotel_id,
            "from_date": from_date,
            "to_date": to_date,
        }

    rows = (await session.execute(sql, params)).mappings().all()
    return [CalendarDay(**dict(row)) for row in rows]


async def get_offers(
    session: AsyncSession,
    hotel_id: int,
    check_in: date,
    nights: int | None = None,
    meal_plan: str | None = None,
) -> list[OfferOut]:
    """Return all current offers for a hotel × date.

    ``meal_plan`` accepts the same three input shapes as :func:`get_calendar`
    — canonical key, raw code, or unknown passthrough — via
    :func:`meal_normalizer.raw_codes_for`. When omitted, no meal filter.
    """
    if meal_plan is not None:
        codes = raw_codes_for(meal_plan)
        sql = text(
            """
            SELECT
                cp.operator_id,
                o.code AS operator_code,
                cp.check_in,
                cp.nights,
                cp.meal_plan,
                cp.room_category,
                cp.price_uah,
                cp.price_original,
                cp.currency,
                cp.deep_link,
                cp.observed_at
            FROM current_prices cp
            JOIN operators o ON o.id = cp.operator_id
            WHERE cp.hotel_id = :hotel_id
              AND cp.check_in = :check_in
              AND (CAST(:nights AS INTEGER) IS NULL OR cp.nights = CAST(:nights AS INTEGER))
              AND cp.meal_plan IN :meal_codes
            ORDER BY cp.price_uah
            """
        ).bindparams(bindparam("meal_codes", expanding=True))
        params = {
            "hotel_id": hotel_id,
            "check_in": check_in,
            "nights": nights,
            "meal_codes": codes,
        }
    else:
        sql = text(
            """
            SELECT
                cp.operator_id,
                o.code AS operator_code,
                cp.check_in,
                cp.nights,
                cp.meal_plan,
                cp.room_category,
                cp.price_uah,
                cp.price_original,
                cp.currency,
                cp.deep_link,
                cp.observed_at
            FROM current_prices cp
            JOIN operators o ON o.id = cp.operator_id
            WHERE cp.hotel_id = :hotel_id
              AND cp.check_in = :check_in
              AND (CAST(:nights AS INTEGER) IS NULL OR cp.nights = CAST(:nights AS INTEGER))
            ORDER BY cp.price_uah
            """
        )
        params = {
            "hotel_id": hotel_id,
            "check_in": check_in,
            "nights": nights,
        }

    rows = (await session.execute(sql, params)).mappings().all()
    return [OfferOut(**dict(row)) for row in rows]
