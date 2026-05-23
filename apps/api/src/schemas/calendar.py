from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CalendarDay(BaseModel):
    """One row of the hotel_calendar_prices MV per (hotel, day[, meal_plan]).

    `meal_plan` is None when the caller did NOT filter by meal_plan — in
    that case the service layer re-aggregates rows across meal plans so
    the response stays one-row-per-day (backwards-compatible shape).
    When `meal_plan` is supplied (?meal_plan=AI), this field echoes the
    filter value, one row per (day, meal_plan).
    """

    check_in: date
    meal_plan: str | None = None
    min_price_uah: int | None = None
    # MIN(price) filtered per nights bucket — lets the UI render different
    # heatmaps for 7n/10n/14n without an extra round trip.
    min_7n: int | None = None
    min_10n: int | None = None
    min_14n: int | None = None
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
