"""Tests for /api/deals list and /api/deals/{id} lookup.

Each test seeds the minimal graph (operator + destination + hotel + deal)
inside the SAVEPOINT, hits the endpoint via the ASGI client (which shares
the same transaction), and asserts on the response payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

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
    source: str | None = "farvater_scrape",
    detection_method: str = "calendar_anomaly",
    nights: int = 7,
) -> SeededDeal:
    """Insert one operator + destination + hotel + deal via raw SQL.

    We avoid the ORM for hotels because `Hotel.coords` is mapped as Text
    while the underlying column is Postgres `point` — the ORM tries to
    bind a VARCHAR even when the value is NULL, which Postgres rejects.
    Ingest writes via raw SQL for the same reason (see ARCHITECTURE.md).
    """
    suffix = uuid4().hex[:8]
    operator_id = (
        await session.execute(
            text(
                "INSERT INTO operators (code, display_name) " "VALUES (:code, :name) RETURNING id"
            ),
            {"code": f"ittour-test-{suffix}", "name": "IT-Tour (test)"},
        )
    ).scalar_one()

    destination_id = (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk) "
                "VALUES (:iso, :slug, :name) RETURNING id"
            ),
            {"iso": "TR", "slug": f"antalya-test-{suffix}", "name": "Анталія"},
        )
    ).scalar_one()

    hotel_id = (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, stars, destination_id, photos_jsonb) "
                "VALUES (:slug, :name, :stars, :dest, CAST(:photos AS jsonb)) RETURNING id"
            ),
            {
                "slug": f"test-hotel-pegasos-kemer-tr-{suffix}",
                "name": "Pegasos Resort (тест)",
                "stars": 4,
                "dest": destination_id,
                "photos": '[{"url":"https://cdn.example.test/hotel.jpg","alt":"Hotel"}]',
            },
        )
    ).scalar_one()

    deal_id = (
        await session.execute(
            text(
                "INSERT INTO deals (hotel_id, operator_id, check_in, nights, "
                "meal_plan, price_uah, baseline_p50, discount_pct, deep_link, "
                "detected_at, source, detection_method) "
                "VALUES (:h, :o, :ci, :n, :m, :p, :b, :d, :dl, :dt, :source, :method) "
                "RETURNING id"
            ),
            {
                "h": hotel_id,
                "o": operator_id,
                "ci": date(2026, 6, 15),
                "n": nights,
                "m": "AI",
                "p": deal_price,
                "b": baseline_p50,
                "d": discount_pct,
                "dl": "https://example.com/affiliate?h=1",
                # Sprint 2.4 added a 48h freshness filter to deal_service.
                # Seed with a "just now" timestamp so the public endpoint
                # returns the row; tests that need an explicitly stale
                # deal can override `detected_at` via kwargs.
                "dt": datetime.now(timezone.utc),
                "source": source,
                "method": detection_method,
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
    assert body["hotel_slug"].startswith("test-hotel-pegasos-kemer-tr-")
    assert body["hotel_name_uk"] == "Pegasos Resort (тест)"
    assert body["hotel_stars"] == 4
    assert body["hotel_photo_url"] == "https://cdn.example.test/hotel.jpg"
    assert body["destination_name"] == "Анталія"


@pytest.mark.asyncio
async def test_get_deal_by_id_includes_historical_promo_discount_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(
        db_session,
        detection_method="promo_discount",
        discount_pct=50.0,
    )

    response = await client.get(f"/api/deals/{seeded.deal_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded.deal_id
    assert body["detection_method"] == "promo_discount"
    assert body["discount_pct"] == 50.0


@pytest.mark.asyncio
async def test_get_deal_by_id_includes_historical_percentile_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(db_session, detection_method="percentile")

    response = await client.get(f"/api/deals/{seeded.deal_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded.deal_id
    assert body["detection_method"] == "percentile"


@pytest.mark.asyncio
async def test_get_deal_by_id_returns_404_when_missing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # No seeding — table is empty inside this savepoint.
    response = await client.get("/api/deals/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "deal not found"


@pytest.mark.asyncio
async def test_get_deal_by_id_hides_legacy_or_synthetic_deals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(db_session, source=None)

    response = await client.get(f"/api/deals/{seeded.deal_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "deal not found"


@pytest.mark.asyncio
async def test_get_deal_by_id_hides_zero_discount_deals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(
        db_session,
        deal_price=12000,
        baseline_p50=12000,
        discount_pct=0.0,
        source="farvater_scrape",
    )

    response = await client.get(f"/api/deals/{seeded.deal_id}")

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
    assert "hotel_photo_url" in first
    assert "destination_name" in first


@pytest.mark.asyncio
async def test_list_deals_preserves_peer_anomaly_detection_method(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(
        db_session,
        deal_price=120,
        detection_method="peer_anomaly",
        discount_pct=99.0,
    )

    response = await client.get("/api/deals?limit=200")

    assert response.status_code == 200
    body = response.json()
    matching = [item for item in body["items"] if item["id"] == seeded.deal_id]
    assert matching, "seeded peer_anomaly deal should be visible in the public feed"
    assert matching[0]["detection_method"] == "peer_anomaly"


@pytest.mark.asyncio
async def test_list_deals_filters_by_nights_range(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Three deals across the three buttons we expose in /best: 7n, 9n, 12n.
    d7 = await _seed_minimal_deal(db_session, nights=7)
    d9 = await _seed_minimal_deal(db_session, nights=9)
    d12 = await _seed_minimal_deal(db_session, nights=12)

    # Exact match — only the 9-night deal.
    resp = await client.get("/api/deals?limit=200&nights_min=9&nights_max=9")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert d9.deal_id in ids
    assert d7.deal_id not in ids
    assert d12.deal_id not in ids

    # 10-14 bucket — should include 12n but not 7n / 9n.
    resp = await client.get("/api/deals?limit=200&nights_min=10&nights_max=14")
    ids = {item["id"] for item in resp.json()["items"]}
    assert d12.deal_id in ids
    assert d7.deal_id not in ids
    assert d9.deal_id not in ids


@pytest.mark.asyncio
async def test_list_deals_excludes_zero_discount_deals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed_minimal_deal(
        db_session,
        deal_price=12000,
        baseline_p50=12000,
        discount_pct=0.0,
        source="farvater_scrape",
    )

    response = await client.get("/api/deals?limit=200")

    assert response.status_code == 200
    body = response.json()
    assert all(item["id"] != seeded.deal_id for item in body["items"])
