"""Business logic for hotel calendar heatmap.

Reads from `hotel_calendar_prices` MV. The MV stores raw operator
meal codes (``AI``/``UAI``/``HB``/``BB``/``RO``/``FB``); the API exposes
canonical product keys (``all_inclusive``/``half_board``/…). Translation
happens here via :mod:`src.services.meal_normalizer`.
"""

from __future__ import annotations

from datetime import date

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
) -> list[CalendarDay]:
    """Return the daily min-price grid for a hotel within a window.

    The underlying MV (``hotel_calendar_prices``, post migration 002) is
    keyed on (hotel_id, check_in, meal_plan) and stores **raw** meal
    codes (``AI``/``UAI``/…).

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
    if meal_plan is not None:
        codes = raw_codes_for(meal_plan)
        # Re-aggregate with MIN across codes (matters for canonical keys
        # that expand to >1 raw code, e.g. all_inclusive → AI+UAI). The
        # response ``meal_plan`` is NULL because we MIN'd over a set.
        sql = text(
            """
            SELECT
                check_in,
                NULL::VARCHAR             AS meal_plan,
                MIN(min_price_uah)        AS min_price_uah,
                MIN(min_7n)               AS min_7n,
                MIN(min_10n)              AS min_10n,
                MIN(min_14n)              AS min_14n,
                MAX(last_observed_at)     AS observed_at
            FROM hotel_calendar_prices
            WHERE hotel_id = :hotel_id
              AND check_in BETWEEN :from_date AND :to_date
              AND meal_plan IN :meal_codes
            GROUP BY check_in
            ORDER BY check_in
            """
        ).bindparams(bindparam("meal_codes", expanding=True))
        params = {
            "hotel_id": hotel_id,
            "from_date": from_date,
            "to_date": to_date,
            "meal_codes": codes,
        }
    else:
        # Re-aggregate MIN over meal-plan rows; MAX over observed_at.
        sql = text(
            """
            SELECT
                check_in,
                NULL::VARCHAR AS meal_plan,
                MIN(min_price_uah)        AS min_price_uah,
                MIN(min_7n)               AS min_7n,
                MIN(min_10n)              AS min_10n,
                MIN(min_14n)              AS min_14n,
                MAX(last_observed_at)     AS observed_at
            FROM hotel_calendar_prices
            WHERE hotel_id = :hotel_id
              AND check_in BETWEEN :from_date AND :to_date
            GROUP BY check_in
            ORDER BY check_in
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
