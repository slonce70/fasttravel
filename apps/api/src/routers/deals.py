"""Deals endpoints.

Endpoints:
  GET /api/deals              — paginated list (optionally filtered by country)
  GET /api/deals/{deal_id}    — single deal by numeric id (permalink target)

Both responses carry hotel_slug / hotel_name_uk / hotel_stars / destination_name
so DealCard on the frontend can render without an extra hotel lookup.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.deal import DealOut, PaginatedDeals
from src.services.deal_service import get_deal_by_id, list_deals

router = APIRouter(prefix="/api/deals", tags=["deals"])


@router.get("", response_model=PaginatedDeals)
async def get_deals(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    session: AsyncSession = Depends(get_db),
) -> PaginatedDeals:
    return await list_deals(session, country_iso2=country, limit=limit, offset=offset)


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: int,
    session: AsyncSession = Depends(get_db),
) -> DealOut:
    """Look up a single deal by id. 404 if not found."""
    deal = await get_deal_by_id(session, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="deal not found")
    return deal
