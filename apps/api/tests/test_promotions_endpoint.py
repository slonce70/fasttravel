"""End-to-end tests for GET /api/promotions.

Uses the api SAVEPOINT fixture so each test seeds promo_offers + hotels
in its own transaction, hits the endpoint via the ASGI client, then
rolls back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_hotel_destination(
    session: AsyncSession, *, country: str = "TR", suffix: str | None = None
) -> tuple[int, int]:
    s = suffix or uuid4().hex[:8]
    operator_id = (
        await session.execute(
            text("INSERT INTO operators (code, display_name) " "VALUES (:c, :n) RETURNING id"),
            {"c": f"farvater-promo-{s}", "n": "Farvater (promo test)"},
        )
    ).scalar_one()
    destination_id = (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk) "
                "VALUES (:iso, :slug, 'D') RETURNING id"
            ),
            {"iso": country, "slug": f"d-promo-{s}"},
        )
    ).scalar_one()
    hotel_id = (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, destination_id, is_active) "
                "VALUES (:slug, 'H', :dest, TRUE) RETURNING id"
            ),
            {"slug": f"fv-{country.lower()}-promo-{s}", "dest": destination_id},
        )
    ).scalar_one()
    return hotel_id, operator_id


async def _add_promo(
    session: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    bucket: str = "gorjashhie-tury",
    observed_at: datetime | None = None,
    check_in: date | None = None,
    price_uah: int = 29847,
    red_price_uah: int | None = 29847,
    system_key: str | None = None,
) -> int:
    sk = system_key or f"sk-{uuid4().hex[:12]}"
    obs = observed_at or datetime.now(UTC)
    ci = check_in or (datetime.now(UTC).date() + timedelta(days=30))
    return int(
        (
            await session.execute(
                text(
                    """INSERT INTO promo_offers
                         (observed_at, hotel_id, operator_id, bucket_slug, system_key,
                          check_in, nights, meal_plan, is_hot, price_uah, red_price_uah)
                       VALUES (:obs, :h, :o, :b, :sk, :ci, 7, 'AI', TRUE, :p, :r)
                       RETURNING id"""
                ),
                {
                    "obs": obs,
                    "h": hotel_id,
                    "o": operator_id,
                    "b": bucket,
                    "sk": sk,
                    "ci": ci,
                    "p": price_uah,
                    "r": red_price_uah,
                },
            )
        ).scalar_one()
    )


# ── tests ───────────────────────────────────────────────────────────────
#
# NOTE: these tests share the dev database with whatever data the live
# scheduler has accumulated (static_tours_sweep may have populated
# thousands of promo_offers). Assertions therefore filter by the seeded
# hotel_id so they remain deterministic regardless of background state.
# `total` checks are scoped via the same filter where we can; otherwise
# we assert presence/absence of the seeded row inside the items list.


async def _scoped_items(client: AsyncClient, hotel_id: int, **params) -> list:
    """Pull every item for a given hotel_id by paging. The dev DB can
    hold thousands of promo_offers; iterating saves us from arbitrary
    high-limit asserts that could still miss rows on a busy DB."""
    items: list = []
    offset = 0
    while True:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/promotions?limit=200&offset={offset}"
        if qs:
            url += f"&{qs}"
        resp = await client.get(url)
        body = resp.json()
        items.extend(i for i in body["items"] if i["hotel_id"] == hotel_id)
        offset += 200
        if offset >= body["total"] or not body["items"]:
            return items


async def test_lists_fresh_promo(client: AsyncClient, db_session: AsyncSession) -> None:
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    await _add_promo(db_session, hotel_id=hotel_id, operator_id=operator_id)

    items = await _scoped_items(client, hotel_id)
    assert len(items) == 1
    item = items[0]
    assert item["bucket_slug"] == "gorjashhie-tury"
    assert item["hotel_id"] == hotel_id
    assert item["country_iso2"] == "TR"
    assert item["discount_pct"] == 0.0
    assert item["has_real_discount"] is False


async def test_stale_promo_filtered_out(client: AsyncClient, db_session: AsyncSession) -> None:
    """observed_at > 24h ago → not returned for this hotel."""
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        observed_at=datetime.now(UTC) - timedelta(hours=48),
    )
    items = await _scoped_items(client, hotel_id)
    assert items == []


async def test_filter_by_bucket(client: AsyncClient, db_session: AsyncSession) -> None:
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="gorjashhie-tury",
        system_key="sk-a",
    )
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="rannee-bronirovanie",
        system_key="sk-b",
    )

    hot = await _scoped_items(client, hotel_id, bucket="gorjashhie-tury")
    assert len(hot) == 1
    assert hot[0]["bucket_slug"] == "gorjashhie-tury"


async def test_filter_by_country(client: AsyncClient, db_session: AsyncSession) -> None:
    hotel_tr, op_tr = await _seed_hotel_destination(db_session, country="TR", suffix="tr")
    hotel_eg, op_eg = await _seed_hotel_destination(db_session, country="EG", suffix="eg")
    await _add_promo(db_session, hotel_id=hotel_tr, operator_id=op_tr, system_key="tr-1")
    await _add_promo(db_session, hotel_id=hotel_eg, operator_id=op_eg, system_key="eg-1")

    tr_items = await _scoped_items(client, hotel_tr, country="TR")
    eg_items = await _scoped_items(client, hotel_eg, country="EG")
    assert len(tr_items) == 1
    assert len(eg_items) == 1
    assert tr_items[0]["country_iso2"] == "TR"
    assert eg_items[0]["country_iso2"] == "EG"


async def test_min_discount_pct_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    """min_discount_pct=20 — only offers with a real strike-through and
    discount >= 20% should pass."""
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    # No strike-through — discount=0
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        price_uah=29847,
        red_price_uah=29847,
        system_key="sk-noredprice",
    )
    # Invalid upstream zero price must not pass SQL filtering and then
    # serialize as has_real_discount=false.
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        price_uah=0,
        red_price_uah=58000,
        system_key="sk-zero-price",
    )
    # Real strike-through — discount=~28%
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="rannee-bronirovanie",
        price_uah=42000,
        red_price_uah=58000,
        system_key="sk-realdiscount",
    )

    items = await _scoped_items(client, hotel_id, min_discount_pct=20)
    assert len(items) == 1
    assert items[0]["discount_pct"] > 20
    assert items[0]["has_real_discount"] is True


async def test_deep_link_includes_system_key(client: AsyncClient, db_session: AsyncSession) -> None:
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    sk = "magic-system-key-001"
    await _add_promo(db_session, hotel_id=hotel_id, operator_id=operator_id, system_key=sk)
    items = await _scoped_items(client, hotel_id)
    assert items
    assert items[0]["deep_link"].endswith(f"?q={sk}")
    assert "farvater.travel" in items[0]["deep_link"]


async def test_pagination(client: AsyncClient, db_session: AsyncSession) -> None:
    """Seed 5 promos for one hotel and verify limit/offset works inside
    the seeded slice. Total may include unrelated rows from the live DB;
    we assert on the per-hotel slice only."""
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    base = datetime.now(UTC)
    for i in range(5):
        await _add_promo(
            db_session,
            hotel_id=hotel_id,
            operator_id=operator_id,
            system_key=f"sk-{i}",
            observed_at=base - timedelta(minutes=i),
            bucket="gorjashhie-tury" if i % 2 == 0 else "rannee-bronirovanie",
        )
    items = await _scoped_items(client, hotel_id)
    assert len(items) == 5
    # IDs are unique within the seeded slice — confirms no double-listing.
    assert len({i["id"] for i in items}) == 5


async def test_deduplicates_promos_by_system_key_and_bucket(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hotel_id, operator_id = await _seed_hotel_destination(db_session)
    older = datetime.now(UTC) - timedelta(hours=2)
    newer = datetime.now(UTC)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        system_key="same-tour",
        bucket="gorjashhie-tury",
        observed_at=older,
        price_uah=50000,
    )
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        system_key="same-tour",
        bucket="gorjashhie-tury",
        observed_at=newer,
        price_uah=48000,
    )

    items = await _scoped_items(client, hotel_id)

    assert len(items) == 1
    assert items[0]["system_key"] == "same-tour"
    assert items[0]["price_uah"] == 48000


async def test_empty_when_no_promos(client: AsyncClient, db_session: AsyncSession) -> None:
    """A hotel with no promo_offers (no seed) returns empty for that
    hotel even if other rows exist in the table."""
    hotel_id, _operator_id = await _seed_hotel_destination(db_session)
    items = await _scoped_items(client, hotel_id)
    assert items == []
