"""Shared dedup helper for recent Farvater price observations."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEDUP_WINDOW_HOURS = 12
DedupKey = tuple[object, int, str, str, int]


async def existing_dedup_keys(
    db: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    window_hours: int = DEDUP_WINDOW_HOURS,
) -> set[DedupKey]:
    """Return recent natural keys including room_category."""
    rows = (
        await db.execute(
            text(
                """SELECT check_in, nights, meal_plan,
                          COALESCE(room_category, ''), price_uah
                   FROM price_observations
                   WHERE hotel_id = :h AND operator_id = :op
                     AND observed_at >= NOW() - make_interval(hours => :hh)"""
            ),
            {"h": hotel_id, "op": operator_id, "hh": window_hours},
        )
    ).all()
    return {(r[0], r[1], r[2], r[3] or "", r[4]) for r in rows}
