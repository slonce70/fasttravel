"""Tests for the shared cheapest-tours SQL / service.

Each test seeds the minimal graph (operator + country-root destination +
hotels + price_observations) inside the SAVEPOINT, REFRESHes the
``current_prices`` MV (rebuilt from the rows visible in the txn), and asserts on
the service output. All assertions are scoped to the seeded ``country_iso2`` so
the test is robust against any ambient data in the MV.

What's covered (per the spec):
  * stars >= min_stars enforced (a 2-star hotel never appears);
  * distinct hotels per country (one row per hotel);
  * rank <= per_country (TOP-3 by default);
  * ordering by absolute price ascending;
  * freshness gate drops a stale-observed row;
  * future-window filter (check_in < +3d and > +90d excluded).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from shared.cheapest_tours import cheapest_tours_sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.cheapest_tours_service import list_cheapest_tours


async def _seed_operator(session: AsyncSession, suffix: str) -> int:
    return (
        await session.execute(
            text(
                "INSERT INTO operators (code, display_name) " "VALUES (:code, :name) RETURNING id"
            ),
            {"code": f"cheapest-op-{suffix}", "name": "Cheapest Op (test)"},
        )
    ).scalar_one()


async def _seed_root_destination(session: AsyncSession, *, iso: str, suffix: str) -> int:
    """A country-root destination (parent_id IS NULL) — country_name resolves
    from its name_uk."""
    return (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk, parent_id) "
                "VALUES (:iso, :slug, :name, NULL) RETURNING id"
            ),
            {"iso": iso, "slug": f"root-{suffix}", "name": f"Country-{iso}"},
        )
    ).scalar_one()


async def _seed_hotel(
    session: AsyncSession, *, stars: int | None, destination_id: int, suffix: str
) -> int:
    return (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, stars, destination_id, is_active) "
                "VALUES (:slug, :name, :stars, :dest, TRUE) RETURNING id"
            ),
            {
                "slug": f"cheapest-hotel-{suffix}",
                "name": f"Hotel {suffix}",
                "stars": stars,
                "dest": destination_id,
            },
        )
    ).scalar_one()


async def _seed_price(
    session: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    check_in: date,
    price_uah: int,
    observed_at: datetime,
    nights: int = 7,
    meal_plan: str = "AI",
    room_category: str = "Standard",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                :observed_at, :hotel_id, :operator_id, :check_in, :nights, :meal_plan,
                :room_category, :price_uah, 'UAH', :deep_link
            )
            """
        ),
        {
            "observed_at": observed_at,
            "hotel_id": hotel_id,
            "operator_id": operator_id,
            "check_in": check_in,
            "nights": nights,
            "meal_plan": meal_plan,
            "room_category": room_category,
            "price_uah": price_uah,
            "deep_link": f"https://example.test/{hotel_id}-{price_uah}",
        },
    )


async def _refresh_mv(session: AsyncSession) -> None:
    await session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))


@pytest.mark.asyncio
async def test_cheapest_tours_topn_distinct_ordered_and_stars(
    db_session: AsyncSession,
) -> None:
    """TOP-3 distinct hotels per country, cheapest first, 2-star excluded."""
    suffix = uuid4().hex[:8]
    iso = "ZZ"
    op = await _seed_operator(db_session, suffix)
    dest = await _seed_root_destination(db_session, iso=iso, suffix=suffix)
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))
    assert isinstance(db_today, date)
    assert db_now is not None

    # Four >=3-star hotels at increasing prices + one 2-star cheapest-of-all.
    h_cheap = await _seed_hotel(db_session, stars=3, destination_id=dest, suffix=f"{suffix}-c")
    h_mid = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-m")
    h_exp = await _seed_hotel(db_session, stars=5, destination_id=dest, suffix=f"{suffix}-e")
    h_fourth = await _seed_hotel(db_session, stars=3, destination_id=dest, suffix=f"{suffix}-4")
    h_two_star = await _seed_hotel(db_session, stars=2, destination_id=dest, suffix=f"{suffix}-2")

    ci = db_today + timedelta(days=10)
    await _seed_price(
        db_session,
        hotel_id=h_cheap,
        operator_id=op,
        check_in=ci,
        price_uah=20000,
        observed_at=db_now,
    )
    await _seed_price(
        db_session, hotel_id=h_mid, operator_id=op, check_in=ci, price_uah=30000, observed_at=db_now
    )
    await _seed_price(
        db_session, hotel_id=h_exp, operator_id=op, check_in=ci, price_uah=40000, observed_at=db_now
    )
    await _seed_price(
        db_session,
        hotel_id=h_fourth,
        operator_id=op,
        check_in=ci,
        price_uah=50000,
        observed_at=db_now,
    )
    # 2-star is the absolute cheapest but must be filtered out by min_stars.
    await _seed_price(
        db_session,
        hotel_id=h_two_star,
        operator_id=op,
        check_in=ci,
        price_uah=5000,
        observed_at=db_now,
    )
    await _refresh_mv(db_session)

    rows = await list_cheapest_tours(db_session, per_country=3, min_stars=3)
    mine = [r for r in rows if r.country_iso2 == iso]

    # TOP-3 only: the 4th-cheapest hotel is dropped.
    assert [r.hotel_id for r in mine] == [h_cheap, h_mid, h_exp]
    # Ranked 1..3 by ascending price.
    assert [r.rank for r in mine] == [1, 2, 3]
    assert [r.price_uah for r in mine] == [20000, 30000, 40000]
    # Distinct hotels.
    assert len({r.hotel_id for r in mine}) == len(mine)
    # 2-star never appears.
    assert h_two_star not in {r.hotel_id for r in mine}
    # country_name resolved from the root destination.
    assert all(r.country_name == f"Country-{iso}" for r in mine)
    # carried offer fields.
    assert mine[0].nights == 7 and mine[0].meal_plan == "AI"
    assert mine[0].deep_link is not None


@pytest.mark.asyncio
async def test_cheapest_tours_per_hotel_cheapest_offer(db_session: AsyncSession) -> None:
    """One row per hotel = the hotel's cheapest fresh offer (not its priciest)."""
    suffix = uuid4().hex[:8]
    iso = "ZY"
    op = await _seed_operator(db_session, suffix)
    dest = await _seed_root_destination(db_session, iso=iso, suffix=suffix)
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))

    hotel = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=suffix)
    # Two offers for the same hotel; only the cheapest should surface.
    await _seed_price(
        db_session,
        hotel_id=hotel,
        operator_id=op,
        check_in=db_today + timedelta(days=20),
        price_uah=33000,
        observed_at=db_now,
    )
    await _seed_price(
        db_session,
        hotel_id=hotel,
        operator_id=op,
        check_in=db_today + timedelta(days=21),
        price_uah=27000,
        observed_at=db_now,
        meal_plan="BB",
    )
    await _refresh_mv(db_session)

    rows = await list_cheapest_tours(db_session, per_country=3, min_stars=3)
    mine = [r for r in rows if r.country_iso2 == iso]
    assert len(mine) == 1
    assert mine[0].price_uah == 27000
    assert mine[0].meal_plan == "BB"


@pytest.mark.asyncio
async def test_cheapest_tours_freshness_gate_drops_stale(db_session: AsyncSession) -> None:
    """A row whose only offer was observed >36h ago is dropped (stays in the MV
    within its 14-day window, but the freshness gate filters it out)."""
    suffix = uuid4().hex[:8]
    iso = "ZX"
    op = await _seed_operator(db_session, suffix)
    dest = await _seed_root_destination(db_session, iso=iso, suffix=suffix)
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))

    fresh_hotel = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-f")
    stale_hotel = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-s")
    ci = db_today + timedelta(days=15)
    # Stale hotel is cheaper, but observed 48h ago -> must be excluded.
    await _seed_price(
        db_session,
        hotel_id=stale_hotel,
        operator_id=op,
        check_in=ci,
        price_uah=10000,
        observed_at=db_now - timedelta(hours=48),
    )
    await _seed_price(
        db_session,
        hotel_id=fresh_hotel,
        operator_id=op,
        check_in=ci,
        price_uah=25000,
        observed_at=db_now,
    )
    await _refresh_mv(db_session)

    rows = await list_cheapest_tours(db_session, per_country=3, min_stars=3)
    mine = [r for r in rows if r.country_iso2 == iso]
    assert [r.hotel_id for r in mine] == [fresh_hotel]
    assert stale_hotel not in {r.hotel_id for r in mine}


@pytest.mark.asyncio
async def test_cheapest_tours_future_window_filter(db_session: AsyncSession) -> None:
    """check_in before +3d or after +90d is excluded; +3..+90 included."""
    suffix = uuid4().hex[:8]
    iso = "ZW"
    op = await _seed_operator(db_session, suffix)
    dest = await _seed_root_destination(db_session, iso=iso, suffix=suffix)
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))

    too_soon = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-soon")
    in_window = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-in")
    too_far = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-far")

    # +1d (too soon) and +91d (too far) are dropped; +30d stays. The MV itself
    # only retains check_in up to +90d, so +91d also can't enter the MV.
    await _seed_price(
        db_session,
        hotel_id=too_soon,
        operator_id=op,
        check_in=db_today + timedelta(days=1),
        price_uah=9000,
        observed_at=db_now,
    )
    await _seed_price(
        db_session,
        hotel_id=in_window,
        operator_id=op,
        check_in=db_today + timedelta(days=30),
        price_uah=22000,
        observed_at=db_now,
    )
    await _seed_price(
        db_session,
        hotel_id=too_far,
        operator_id=op,
        check_in=db_today + timedelta(days=91),
        price_uah=8000,
        observed_at=db_now,
    )
    await _refresh_mv(db_session)

    rows = await list_cheapest_tours(db_session, per_country=3, min_stars=3)
    mine = {r.hotel_id for r in rows if r.country_iso2 == iso}
    assert mine == {in_window}


def test_cheapest_tours_sql_has_expected_shape() -> None:
    """The rendered SQL reuses the freshness constant and the right gates."""
    from shared.cheapest_tours import FRESHNESS_HOURS

    sql = cheapest_tours_sql()
    assert "h.stars >= :min_stars" in sql
    assert "r.rank <= :per_country" in sql
    assert f"INTERVAL '{FRESHNESS_HOURS} hours'" in sql
    assert "ROW_NUMBER() OVER" in sql
    # Honest copy: this surface never computes a discount / baseline.
    assert "discount" not in sql.lower()
    assert "baseline" not in sql.lower()
    # Default (API/web/bot) variant carries no digest-only params.
    assert "meal_codes" not in sql
    assert "priority" not in sql


def test_cheapest_tours_sql_digest_variant_adds_meal_and_priority_clauses() -> None:
    """The digest variant gates on all-inclusive meal codes and gives priority
    countries a larger per-country cap; both are opt-in (default off)."""
    sql = cheapest_tours_sql(meal_filtered=True, prioritized=True)
    # Meal filter on the all-inclusive codes (array bind, cast for asyncpg).
    assert "cp.meal_plan = ANY(CAST(:meal_codes AS text[]))" in sql
    # Priority countries get a larger per-country cap via a CASE on the rank.
    assert "r.country_iso2 = ANY(CAST(:priority_countries AS text[]))" in sql
    assert ":priority_per_country" in sql


@pytest.mark.asyncio
async def test_cheapest_tours_meal_filter_keeps_only_all_inclusive(
    db_session: AsyncSession,
) -> None:
    """With meal_filtered, a hotel surfaces its cheapest ALL-INCLUSIVE offer
    (not a cheaper RO/BB), and a hotel with no AI offer drops entirely."""
    suffix = uuid4().hex[:8]
    iso = "QM"
    op = await _seed_operator(db_session, suffix)
    dest = await _seed_root_destination(db_session, iso=iso, suffix=suffix)
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))
    ci = db_today + timedelta(days=12)

    a = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-a")
    b = await _seed_hotel(db_session, stars=4, destination_id=dest, suffix=f"{suffix}-b")
    # Hotel A: cheaper RO + pricier AI → the AI filter surfaces the AI offer.
    await _seed_price(
        db_session,
        hotel_id=a,
        operator_id=op,
        check_in=ci,
        price_uah=10000,
        observed_at=db_now,
        meal_plan="RO",
        room_category="Std RO",
    )
    await _seed_price(
        db_session,
        hotel_id=a,
        operator_id=op,
        check_in=ci,
        price_uah=15000,
        observed_at=db_now,
        meal_plan="AI",
        room_category="Std AI",
    )
    # Hotel B: only RO → excluded by the AI filter.
    await _seed_price(
        db_session,
        hotel_id=b,
        operator_id=op,
        check_in=ci,
        price_uah=9000,
        observed_at=db_now,
        meal_plan="RO",
        room_category="Std RO",
    )
    await _refresh_mv(db_session)

    rows = (
        await db_session.execute(
            text(cheapest_tours_sql(meal_filtered=True)),
            {"min_stars": 3, "per_country": 3, "meal_codes": ["AI", "UAI"]},
        )
    ).all()
    mine = [r for r in rows if r.country_iso2 == iso]
    assert [r.hotel_id for r in mine] == [a]
    assert mine[0].meal_plan == "AI"
    assert mine[0].price_uah == 15000
    assert b not in {r.hotel_id for r in mine}


@pytest.mark.asyncio
async def test_cheapest_tours_priority_countries_get_more_variants(
    db_session: AsyncSession,
) -> None:
    """Priority countries get up to priority_per_country (5); others stay at
    per_country (3)."""
    suffix = uuid4().hex[:8]
    op = await _seed_operator(db_session, suffix)
    prio_iso, norm_iso = "QP", "QN"
    prio_dest = await _seed_root_destination(db_session, iso=prio_iso, suffix=f"{suffix}-p")
    norm_dest = await _seed_root_destination(db_session, iso=norm_iso, suffix=f"{suffix}-n")
    db_today = await db_session.scalar(text("SELECT CURRENT_DATE"))
    db_now = await db_session.scalar(text("SELECT NOW()"))
    ci = db_today + timedelta(days=14)

    # 4 hotels in each country (so priority shows 4 of up-to-5, normal caps at 3).
    for i in range(4):
        hp = await _seed_hotel(
            db_session, stars=4, destination_id=prio_dest, suffix=f"{suffix}-p{i}"
        )
        await _seed_price(
            db_session,
            hotel_id=hp,
            operator_id=op,
            check_in=ci,
            price_uah=20000 + i * 1000,
            observed_at=db_now,
        )
        hn = await _seed_hotel(
            db_session, stars=4, destination_id=norm_dest, suffix=f"{suffix}-n{i}"
        )
        await _seed_price(
            db_session,
            hotel_id=hn,
            operator_id=op,
            check_in=ci,
            price_uah=20000 + i * 1000,
            observed_at=db_now,
        )
    await _refresh_mv(db_session)

    rows = (
        await db_session.execute(
            text(cheapest_tours_sql(prioritized=True)),
            {
                "min_stars": 3,
                "per_country": 3,
                "priority_countries": [prio_iso],
                "priority_per_country": 5,
            },
        )
    ).all()
    assert len([r for r in rows if r.country_iso2 == prio_iso]) == 4
    assert len([r for r in rows if r.country_iso2 == norm_iso]) == 3
