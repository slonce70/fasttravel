"""Hotel-related endpoints.

NOTE on slug vs id: external URLs use the canonical_slug (better for SEO).
Calendar and offers endpoints take the numeric id since they're typically
called from JS already in possession of the hotel row. The web app should
resolve slug -> id via GET /api/hotels/{slug} and reuse the id thereafter.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models import Hotel
from src.schemas.calendar import CalendarDay, OfferOut
from src.schemas.hotel import HotelOut
from src.services.calendar_service import get_calendar, get_offers

router = APIRouter(prefix="/api/hotels", tags=["hotels"])


@router.get("/{slug}", response_model=HotelOut)
async def get_hotel(slug: str, session: AsyncSession = Depends(get_db)) -> HotelOut:
    hotel = await session.scalar(
        select(Hotel).where(Hotel.canonical_slug == slug, Hotel.is_active.is_(True))
    )
    if hotel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hotel not found")
    return HotelOut.model_validate(hotel)


@router.get("/{hotel_id}/calendar", response_model=list[CalendarDay])
async def hotel_calendar(
    hotel_id: int,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    session: AsyncSession = Depends(get_db),
) -> list[CalendarDay]:
    if to_date < from_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="`to` must be >= `from`")
    if (to_date - from_date).days > 180:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="window too wide (max 180 days)")
    return await get_calendar(session, hotel_id, from_date, to_date)


@router.get("/{hotel_id}/offers", response_model=list[OfferOut])
async def hotel_offers(
    hotel_id: int,
    check_in: date = Query(alias="date"),
    nights: int | None = Query(default=None, ge=1, le=30),
    meal: str | None = Query(default=None, max_length=16),
    session: AsyncSession = Depends(get_db),
) -> list[OfferOut]:
    return await get_offers(session, hotel_id, check_in, nights=nights, meal_plan=meal)
