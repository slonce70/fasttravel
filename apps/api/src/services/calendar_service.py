"""Business logic for hotel calendar heatmap.

Reads from `hotel_calendar_prices` MV. Stub for now — real implementation
arrives once the ingest pipeline lands and the MV has data.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.calendar import CalendarDay, OfferOut


async def get_calendar(
    session: AsyncSession,
    hotel_id: int,
    from_date: date,
    to_date: date,
    meal_plan: str | None = None,
) -> list[CalendarDay]:
    """Return the daily min-price grid for a hotel within a window.

    The underlying MV (`hotel_calendar_prices`, post migration 002) is
    keyed on (hotel_id, check_in, meal_plan). Two query shapes:

    * `meal_plan` given → filter the MV directly, one row per
      (check_in, meal_plan). The `meal_plan` field on the response
      echoes the filter value.
    * `meal_plan` omitted → backward-compatible shape: re-aggregate with
      MIN across meal-plan rows so callers still get one row per day.
      The `meal_plan` field on the response is NULL in this branch.
      MIN over per-meal-plan MIN is still a MIN — no double-counting.
    """
    if meal_plan is not None:
        sql = text(
            """
            SELECT
                check_in,
                meal_plan,
                min_price_uah,
                min_7n,
                min_10n,
                min_14n,
                last_observed_at AS observed_at
            FROM hotel_calendar_prices
            WHERE hotel_id = :hotel_id
              AND check_in BETWEEN :from_date AND :to_date
              AND meal_plan = :meal_plan
            ORDER BY check_in
            """
        )
        params = {
            "hotel_id": hotel_id,
            "from_date": from_date,
            "to_date": to_date,
            "meal_plan": meal_plan,
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
    """Return all current offers for a hotel × date."""
    # Explicit casts on NULL-able filter parameters: asyncpg cannot infer
    # the type of a bare parameter that only appears inside `IS NULL`,
    # and raises AmbiguousParameterError. The casts make the type
    # unambiguous at prepare time.
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
          AND (CAST(:meal_plan AS VARCHAR) IS NULL OR cp.meal_plan = CAST(:meal_plan AS VARCHAR))
        ORDER BY cp.price_uah
        """
    )
    rows = (
        await session.execute(
            sql,
            {
                "hotel_id": hotel_id,
                "check_in": check_in,
                "nights": nights,
                "meal_plan": meal_plan,
            },
        )
    ).mappings().all()
    return [OfferOut(**dict(row)) for row in rows]
