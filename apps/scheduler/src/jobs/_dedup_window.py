"""Shared 12h dedup helper for both snapshot_farvater and refresh_worker.

Before Sprint 3.3 both jobs had their own copy of the same query — same
SQL, same window, same tuple shape minus a subtle drift: snapshot_farvater
used `(check_in, nights, meal_plan, price_uah)` while refresh_worker used
`(check_in, nights, meal, uah)` (same database column, different
dict-key names). Easy to drift apart over time.

The bigger gap was that NEITHER included `room_category` in the tuple.
A hotel offering the same (board, duration) for two different room
categories at the same price would have one of the rows silently
dropped — even though those are legitimately distinct offers.

This helper fixes both:
  * one canonical query, both call sites import it
  * room_category in the dedup tuple

`DEDUP_WINDOW_HOURS` lives here too so the constants don't drift either.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEDUP_WINDOW_HOURS = 12

# Tuple shape: (check_in, nights, meal_plan, room_category, price_uah).
# room_category can be empty string ("") which is OK — different rooms
# at the same price still collapse as distinct only if their categories
# differ; empty vs empty is one dedup'd row, as it should be.
DedupKey = tuple[object, int, str, str, int]


async def existing_dedup_keys(
    db: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    window_hours: int = DEDUP_WINDOW_HOURS,
) -> set[DedupKey]:
    """Return the set of (check_in, nights, meal_plan, room_category, price_uah)
    tuples already in `price_observations` within `window_hours` for the
    given (hotel_id, operator_id).

    Callers build new rows then filter via membership test:

        existing = await existing_dedup_keys(db, hotel_id=h, operator_id=op)
        new = [r for r in rows if r.dedup_key() not in existing]
    """
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
