"""Hotel price-state helpers for search-gate freshness."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_priced(db: AsyncSession, hotel_db_id: int) -> None:
    """Flip a hotel into the live-priced cohort."""
    await db.execute(
        text("""UPDATE hotels
                SET last_priced_at = NOW(),
                    has_active_prices = TRUE
                WHERE id = :id"""),
        {"id": hotel_db_id},
    )


async def mark_unpriced(db: AsyncSession, hotel_db_id: int) -> None:
    """Record that a live price probe found no current inventory."""
    await db.execute(
        text("""UPDATE hotels
                SET last_priced_at = NOW(),
                    has_active_prices = FALSE
                WHERE id = :id"""),
        {"id": hotel_db_id},
    )


async def decay_active_prices(db: AsyncSession, stale_after_days: int = 7) -> int:
    """Demote stale active hotels and return the rowcount."""
    res = await db.execute(
        text("""UPDATE hotels
                SET has_active_prices = FALSE
                WHERE has_active_prices = TRUE
                  AND (last_priced_at IS NULL
                       OR last_priced_at < NOW()
                          - make_interval(days => :d))"""),
        {"d": stale_after_days},
    )
    return int(cast(Any, res).rowcount or 0)
