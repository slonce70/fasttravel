"""Smoke test for `scripts.seed_demo`.

Marked `slow` and skipped unless explicitly selected so it never runs in
CI by default. Run locally with:

    docker compose run --rm api pytest -m slow tests/test_seed.py -s

The test cannot reuse the `db_session` fixture from conftest because that
fixture wraps everything in a SAVEPOINT-and-rollback. The seed needs to
commit (and `REFRESH MATERIALIZED VIEW` cannot run inside a transaction
block in all cases). We open our own AsyncConnection in AUTOCOMMIT mode
for the post-seed assertions.

Pre-condition: the schema must be migrated and the relevant tables must be
EMPTY. If a previous seed has already populated the database the script
short-circuits via its sentinel — in that case we just assert that the
existing data still matches the invariants.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from scripts.seed_demo import seed
from src.infra.db import async_engine


@pytest.mark.slow
@pytest.mark.asyncio
async def test_seed_demo_populates_database() -> None:
    # Run the seed (idempotent — safe even if data already present).
    await seed(full=False)

    async with async_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")

        hotel_count = await conn.scalar(text("SELECT COUNT(*) FROM hotels"))
        operator_count = await conn.scalar(text("SELECT COUNT(*) FROM operators"))
        mapping_count = await conn.scalar(text("SELECT COUNT(*) FROM hotel_operator_mapping"))
        obs_count = await conn.scalar(text("SELECT COUNT(*) FROM price_observations"))
        calendar_count = await conn.scalar(text("SELECT COUNT(*) FROM hotel_calendar_prices"))

        # 50 hotels exactly, 3 operators, 100-150 mappings.
        assert hotel_count == 50, f"expected 50 hotels, got {hotel_count}"
        assert operator_count == 3, f"expected 3 operators, got {operator_count}"
        assert 100 <= mapping_count <= 150, f"expected 100-150 mappings, got {mapping_count}"

        # Default mode floor: 7 days × 2 snapshots × ~125 mappings × 60 days × 3 nights × 2 meals
        # = ~630 000 max, ~315 000 typical. Lower bound generously.
        assert obs_count > 100_000, f"expected >100k price_observations, got {obs_count}"

        # hotel_calendar_prices MV must have data for all 50 hotels.
        hotels_with_calendar = await conn.scalar(
            text("SELECT COUNT(DISTINCT hotel_id) FROM hotel_calendar_prices")
        )
        assert (
            hotels_with_calendar == 50
        ), f"expected calendar data for all 50 hotels, got {hotels_with_calendar}"

        # The hotel_calendar_prices MV groups by (hotel, check_in). With 60 days
        # of check-in horizon × 50 hotels we should see roughly 3 000 rows.
        assert calendar_count >= 50 * 30, (
            f"expected at least 1500 calendar rows (50 hotels × 30 days), got {calendar_count}"
        )

        # Sentinel hotel must be queryable by slug (smoke check for HTTP layer).
        sample = await conn.execute(
            text(
                "SELECT id, canonical_slug, stars FROM hotels "
                "WHERE canonical_slug = 'rixos-premium-belek-belek-tr'"
            )
        )
        row = sample.first()
        assert row is not None, "sentinel slug missing — seed did not run correctly"
        assert row.stars in (3, 4, 5)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_seed_demo_is_idempotent() -> None:
    """Calling seed() a second time must be a no-op (no duplicate rows)."""
    # First call (idempotent if already seeded by previous test).
    await seed(full=False)
    async with async_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        hotels_before = await conn.scalar(text("SELECT COUNT(*) FROM hotels"))

    # Second call should detect sentinel and skip.
    await seed(full=False)
    async with async_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        hotels_after = await conn.scalar(text("SELECT COUNT(*) FROM hotels"))

    assert hotels_after == hotels_before, "seed is not idempotent — hotel count changed"
