"""Cheapest-tours endpoint («Найдешевші тури»).

GET /api/cheapest-tours — flat ranked list of the cheapest upcoming tours,
TOP-`per_country` distinct hotels per country, min-stars filtered, freshness
gated. Absolute-cheap, NOT a discount — clients group by `country_iso2`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from shared.cheapest_tours import MIN_STARS, PER_COUNTRY
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.cheapest_tour import CheapestTourOut
from src.services.cheapest_tours_service import list_cheapest_tours

router = APIRouter(prefix="/api/cheapest-tours", tags=["cheapest-tours"])


@router.get("", response_model=list[CheapestTourOut])
async def get_cheapest_tours(
    per_country: int = Query(default=PER_COUNTRY, ge=1, le=10),
    min_stars: int = Query(default=MIN_STARS, ge=1, le=5),
    session: AsyncSession = Depends(get_db),
) -> list[CheapestTourOut]:
    return await list_cheapest_tours(
        session,
        per_country=per_country,
        min_stars=min_stars,
    )
