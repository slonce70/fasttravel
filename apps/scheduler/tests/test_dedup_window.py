"""Unit tests for the shared 12h dedup helper (Sprint 3.3).

Before the helper, snapshot_farvater and refresh_worker each had their
own copy of this query with subtly different tuple shapes (`meal_plan`
vs `meal`; missing `room_category` in both). The helper centralises
both, AND adds room_category to the natural key so distinct rooms at
the same price don't silently collapse.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.jobs._dedup_window import DEDUP_WINDOW_HOURS, existing_dedup_keys


async def test_returns_5_tuple_with_room_category() -> None:
    """Tuple shape lock: (check_in, nights, meal_plan, room_category, price_uah).
    Drift from 4-tuple to 5-tuple is exactly what the helper was extracted to fix."""
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            all=lambda: [
                ("2026-07-01", 7, "AI", "Standard", 29847),
                ("2026-07-01", 10, "AI", "Suite", 45000),
                ("2026-07-01", 7, "AI", None, 30000),  # None room_category
            ]
        )
    )
    keys = await existing_dedup_keys(db, hotel_id=1, operator_id=2)
    assert keys == {
        ("2026-07-01", 7, "AI", "Standard", 29847),
        ("2026-07-01", 10, "AI", "Suite", 45000),
        # COALESCE(NULL, '') in SQL → empty string in tuple
        ("2026-07-01", 7, "AI", "", 30000),
    }


async def test_uses_default_12h_window() -> None:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    await existing_dedup_keys(db, hotel_id=1, operator_id=2)
    args = db.execute.await_args.args
    # Second positional is the params dict
    assert args[1]["hh"] == DEDUP_WINDOW_HOURS == 12


async def test_window_override_honoured() -> None:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    await existing_dedup_keys(db, hotel_id=1, operator_id=2, window_hours=24)
    args = db.execute.await_args.args
    assert args[1]["hh"] == 24


async def test_empty_db_returns_empty_set() -> None:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    keys = await existing_dedup_keys(db, hotel_id=99, operator_id=99)
    assert keys == set()
