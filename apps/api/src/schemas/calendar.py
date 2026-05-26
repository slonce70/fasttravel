from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CalendarDay(BaseModel):
    """One row of the hotel_calendar_prices MV per (hotel, day[, meal_plan]).

    `meal_plan` is None when the caller did NOT filter by meal_plan — in
    that case the service layer re-aggregates rows across meal plans so
    the response stays one-row-per-day (backwards-compatible shape).
    When `meal_plan` is supplied (?meal_plan=AI), this field echoes the
    filter value, one row per (day, meal_plan).

    `prices_by_night` is a map ``{"7": 50000, "8": 52000, ...}`` keyed by
    stringified night count. With ``?nights=N`` it contains a single
    entry for the requested N; without it, the full MV map (currently
    nights 7..14, see migration 016). Missing nights mean no offers
    were observed for that duration — frontend falls back to
    ``min_price_uah`` for display.
    """

    check_in: date
    meal_plan: str | None = None
    min_price_uah: int | None = None
    prices_by_night: dict[str, int] = Field(default_factory=dict)
    observed_at: datetime | None = None


class OfferOut(BaseModel):
    """One offer from current_prices MV."""

    operator_id: int
    operator_code: str
    check_in: date
    nights: int
    meal_plan: str
    room_category: str | None = None
    price_uah: int
    price_original: int | None = None
    currency: str
    deep_link: str | None = None
    observed_at: datetime
