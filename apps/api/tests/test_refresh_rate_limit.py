"""Per-IP rate limiting on POST /api/hotels/{id}/refresh.

The queue-cap + per-hotel lock alone can't stop an attacker rotating
hotel_ids from a single IP. slowapi adds a 10/hour/IP cap so any one
client can fill at most 10 queue slots per hour.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.limiter import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Each test gets a clean slowapi storage so the 10/hour bucket starts
    empty. slowapi's in-memory backend persists state across the FastAPI
    app instance otherwise, leaking 429s between tests."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_refresh_rate_limit_caps_at_ten_per_hour(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """11th identical request within the window must respond 429.

    Uses a freshly inserted hotel so we don't interfere with whatever the
    live snapshot put into the DB; the operator-mapping row points the
    refresh code at a numeric farvater_key so the request gets past the
    SSRF guard and reaches the rate limit.
    """
    dest_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('ZY', 'rl-test-country', 'RL Country', 'RL Country')
                RETURNING id
                """
            )
        )
    ).scalar_one()
    hotel_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO hotels (
                    canonical_slug, name_uk, name_en, destination_id, is_active
                )
                VALUES ('rl-test-hotel', 'RL Hotel', 'RL Hotel', :dest, true)
                RETURNING id
                """
            ),
            {"dest": dest_id},
        )
    ).scalar_one()
    operator_id = (
        await db_session.execute(text("SELECT id FROM operators WHERE code='farvater'"))
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO hotel_operator_mapping
                  (operator_id, external_id, hotel_id, external_name)
            VALUES (:op, '999999', :h, 'RL Hotel')
            ON CONFLICT (operator_id, external_id) DO NOTHING
            """
        ),
        {"op": operator_id, "h": hotel_id},
    )

    successes = 0
    too_many = 0
    for _ in range(11):
        resp = await client.post(f"/api/hotels/{hotel_id}/refresh")
        if resp.status_code == 200:
            successes += 1
        elif resp.status_code == 429:
            too_many += 1

    assert successes == 10, f"expected 10 OK responses, got {successes}"
    assert too_many == 1, f"expected exactly one 429, got {too_many}"
