"""Tests for /api/deals list and /api/deals/{id} lookup.

Each test seeds the minimal graph (operator + destination + hotel + deal)
inside the SAVEPOINT, hits the endpoint via the ASGI client (which shares
the same transaction), and asserts on the response payload.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SeededDeal:
    deal_id: int
    hotel_id: int
    operator_id: int
    destination_id: int


async def _seed_minimal_deal(
    session: AsyncSession,
    *,
    deal_price: int = 8000,
    baseline_p50: int = 12000,
    discount_pct: float = 33.0,
) -> SeededDeal:
    """Insert one operator + destination + hotel + deal via raw SQL.

    We avoid the ORM for hotels because `Hotel.coords` is mapped as Text
    while the underlying column is Postgres `point` — the ORM tries to
    bind a VARCHAR even when the value is NULL, which Postgres rejects.
    Ingest writes via raw SQL for the same reason (see ARCHITECTURE.md).
    """
    operator_id = (
        await session.execute(
            text(
                "INSERT INTO operators (code, display_name) "
                "VALUES (:code, :name) RETURNING id"
            ),
            {"code": "ittour-test", "name": "IT-Tour (test)"},
        )
    ).scalar_one()

    destination_id = (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk) "
                "VALUES (:iso, :slug, :name) RETURNING id"
            ),
            {"iso": "TR", "slug": "antalya", "name": "Анталія"},
        )
    ).scalar_one()

    hotel_id = (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, stars, destination_id) "
                "VALUES (:slug, :name, :stars, :dest) RETURNING id"
            ),
            {
                "slug": "test-hotel-pegasos-kemer-tr",
                "name": "Pegasos Resort (тест)",
                "stars": 4,
                "dest": destination_id,
            },
        )
    ).scalar_one()

    deal_id = (
        await session.execute(
            text(
                "INSERT INTO deals (hotel_id, operator_id, check_in, nights, "
                "meal_plan, price_uah, baseline_p50, discount_pct, deep_link, "
                "detected_at) VALUES (:h, :o, :ci, :n, :m, :p, :b, :d, :dl, :dt) "
                "RETURNING id"
            ),
            {
                "h": hotel_id,
                "o": operator_id,
                "ci": date(2026, 6, 15),
                "n": 7,
                "m": "AI",
                "p": deal_price,
                "b": baseline_p50,
                "d": discount_pct,
                "dl": "https://example.com/affiliate?h=1",
                "dt": datetime(2026, 5, 22, 10, 30, tzinfo=timezone.utc),
            },
        )
    ).scalar_one()

    await session.flush()
    return SeededDeal(
        deal_id=deal_id,
        hotel_id=hotel_id,
        operator_id=operator_id,
        destination_id=destination_id,
    )


@pytest.mark.asyncio
async def test_get_deal_by_id_returns_enriched_payload(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(db_session)

    response = await client.get(f"/api/deals/{seeded.deal_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded.deal_id
    assert body["price_uah"] == 8000
    assert body["baseline_p50"] == 12000
    assert body["hotel_slug"] == "test-hotel-pegasos-kemer-tr"
    assert body["hotel_name_uk"] == "Pegasos Resort (тест)"
    assert body["hotel_stars"] == 4
    assert body["destination_name"] == "Анталія"


@pytest.mark.asyncio
async def test_get_deal_by_id_returns_404_when_missing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # No seeding — table is empty inside this savepoint.
    response = await client.get("/api/deals/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "deal not found"


@pytest.mark.asyncio
async def test_list_deals_includes_joined_hotel_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_minimal_deal(db_session)

    response = await client.get("/api/deals?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["items"], "expected at least one deal in the listing"
    first = body["items"][0]
    # The joined fields the frontend needs to skip the "Готель #42" placeholder.
    assert "hotel_slug" in first
    assert "hotel_name_uk" in first
    assert "hotel_stars" in first
    assert "destination_name" in first
