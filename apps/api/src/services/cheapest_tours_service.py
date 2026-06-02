"""Cheapest-tours listing service.

Runs the shared :func:`shared.cheapest_tours.cheapest_tours_sql` (the single
source of "what is the cheapest tour" used by every surface) and maps each row
to :class:`CheapestTourOut`. Absolute-cheap, NOT a discount — see the SQL module
docstring.

Mirrors the explicit-SQL + build-response-from-columns pattern of
``search_service`` / ``deal_service``: a flat ranked list, clients group by
``country_iso2``.
"""

from __future__ import annotations

from shared.cheapest_tours import MIN_STARS, PER_COUNTRY, cheapest_tours_sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.cheapest_tour import CheapestTourOut


async def list_cheapest_tours(
    session: AsyncSession,
    *,
    per_country: int = PER_COUNTRY,
    min_stars: int = MIN_STARS,
) -> list[CheapestTourOut]:
    """Return the flat ranked list of cheapest tours (TOP-``per_country``
    distinct hotels per country, ``stars >= min_stars``, fresh + future)."""
    rows = (
        (
            await session.execute(
                text(cheapest_tours_sql()),
                {"per_country": per_country, "min_stars": min_stars},
            )
        )
        .mappings()
        .all()
    )

    return [
        CheapestTourOut(
            country_iso2=row["country_iso2"],
            country_name=row["country_name"],
            hotel_id=row["hotel_id"],
            hotel_slug=row["hotel_slug"],
            hotel_name=row["hotel_name"],
            stars=int(row["stars"]),
            review_score=(float(row["review_score"]) if row["review_score"] is not None else None),
            review_count=int(row["review_count"] or 0),
            check_in=row["check_in"],
            nights=int(row["nights"]),
            meal_plan=row["meal_plan"],
            price_uah=int(row["price_uah"]),
            deep_link=row["deep_link"],
            rank=int(row["rank"]),
        )
        for row in rows
    ]
