from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class CheapestTourOut(BaseModel):
    """One ranked "cheapest tour" row — the absolute-cheap surface.

    This is NOT a discount: there is no baseline / percent-off / strike-through.
    The only price claim is the absolute ``price_uah`` («ціна від»). The endpoint
    returns a FLAT ranked list; clients group by ``country_iso2`` and render the
    TOP-``rank`` distinct hotels per country.

    ``stars`` is non-null here (the query filters ``stars >= min_stars``).
    ``review_score`` is nullable (``hotels.review_score`` is nullable) and is
    serialized as a float at this boundary (the column is Numeric -> Decimal).
    """

    model_config = ConfigDict(from_attributes=True)

    country_iso2: str
    country_name: str | None = None
    hotel_id: int
    hotel_slug: str
    hotel_name: str
    stars: int
    review_score: float | None = None
    review_count: int
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    deep_link: str | None = None
    rank: int
