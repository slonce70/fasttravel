"""GET /api/promotions — operator-flagged farvater promo offers.

Distinct from /api/deals which surfaces algorithmic price-anomaly
deals. Promotions are tour-level events from farvater's own buckets
(gorjashhie-tury / rannee-bronirovanie / akcionnye-tury) with their
own lifecycle (LoadedDate, promotionEndDate); see Sprint 1A/B/C/E for
the full pipeline.

Query params mirror /api/deals shape so the client can switch tabs
without re-shaping requests:
  - country=TR
  - limit / offset
Plus promo-specific filters:
  - bucket=<slug>            — narrow to one farvater bucket
  - min_discount_pct=<num>   — only show offers with real strike-through
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.schemas.promotion import PaginatedPromotions
from src.services.promo_service import list_promotions

router = APIRouter(prefix="/api/promotions", tags=["promotions"])


@router.get("", response_model=PaginatedPromotions)
async def get_promotions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    bucket: str | None = Query(default=None, min_length=2, max_length=32),
    min_discount_pct: float | None = Query(default=None, ge=0, le=100),
    session: AsyncSession = Depends(get_db),
) -> PaginatedPromotions:
    return await list_promotions(
        session,
        bucket=bucket,
        country=country,
        min_discount_pct=min_discount_pct,
        limit=limit,
        offset=offset,
    )
