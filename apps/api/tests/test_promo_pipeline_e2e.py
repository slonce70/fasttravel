"""End-to-end tests for promotions plus historical promo-discount deals.

`detect_deals` is production date-dip only. `promo_offers` feed
`/api/promotions`; historical/manual `promo_discount` rows remain valid
`/api/deals` data when they already exist as deals.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.deal import Deal


async def _scoped_promos(client: AsyncClient, hotel_id: int, **params) -> list:
    """Paginate /api/promotions and return only rows matching hotel_id."""
    items: list = []
    offset = 0
    while True:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/promotions?limit=200&offset={offset}"
        if qs:
            url += f"&{qs}"
        body = (await client.get(url)).json()
        items.extend(i for i in body["items"] if i["hotel_id"] == hotel_id)
        offset += 200
        if offset >= body["total"] or not body["items"]:
            return items


async def _scoped_deals(client: AsyncClient, hotel_id: int, **params) -> list:
    items: list = []
    offset = 0
    while True:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"/api/deals?limit=200&offset={offset}"
        if qs:
            url += f"&{qs}"
        body = (await client.get(url)).json()
        items.extend(i for i in body["items"] if i["hotel_id"] == hotel_id)
        offset += 200
        if offset >= body["total"] or not body["items"]:
            return items


async def _seed_full(session: AsyncSession) -> tuple[int, int]:
    """Seed minimal operator + destination + hotel + 2 promo_offers."""
    suffix = uuid4().hex[:8]
    operator_id = (
        await session.execute(
            text("INSERT INTO operators (code, display_name) VALUES (:c, :n) RETURNING id"),
            {"c": f"farvater-e2e-{suffix}", "n": "Farvater (e2e)"},
        )
    ).scalar_one()
    destination_id = (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk) "
                "VALUES ('TR', :s, 'Туреччина') RETURNING id"
            ),
            {"s": f"d-e2e-{suffix}"},
        )
    ).scalar_one()
    hotel_id = (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, destination_id, is_active) "
                "VALUES (:slug, 'E2E Hotel', :d, TRUE) RETURNING id"
            ),
            {"slug": f"fv-tr-e2e-{suffix}", "d": destination_id},
        )
    ).scalar_one()

    # Two promos in different buckets — both appear in /api/promotions.
    # Promo offers are not converted into /api/deals by the active detector.
    for bucket, sk, price, red in [
        ("gorjashhie-tury", f"sk-hot-{suffix}", 29847, 39847),
        ("rannee-bronirovanie", f"sk-early-{suffix}", 25000, 50000),
    ]:
        await session.execute(
            text(
                """INSERT INTO promo_offers
                     (observed_at, hotel_id, operator_id, bucket_slug, system_key,
                      check_in, nights, meal_plan, is_hot, price_uah, red_price_uah)
                   VALUES (:obs, :h, :o, :b, :sk, :ci, 7, 'AI', TRUE, :p, :r)"""
            ),
            {
                "obs": datetime.now(UTC),
                "h": hotel_id,
                "o": operator_id,
                "b": bucket,
                "sk": sk,
                "ci": date.today() + timedelta(days=30),
                "p": price,
                "r": red,
            },
        )
    return hotel_id, operator_id


async def _seed_historical_promo_discount_deal(
    session: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
) -> int:
    deal_id = (
        await session.execute(
            text(
                """INSERT INTO deals
                     (hotel_id, operator_id, check_in, nights, meal_plan,
                      price_uah, baseline_p50, discount_pct, deep_link,
                      source, detection_method, detected_at)
                   VALUES (:h, :o, :ci, 7, 'AI', 25000, 50000, 50.0,
                           'https://farvater.travel/?q=historical-promo',
                           'farvater_scrape', 'promo_discount', NOW())
                   RETURNING id"""
            ),
            {
                "h": hotel_id,
                "o": operator_id,
                "ci": date.today() + timedelta(days=30),
            },
        )
    ).scalar_one()
    return int(deal_id)


async def test_promotions_and_historical_promo_discount_deal_surfaces(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hotel_id, operator_id = await _seed_full(db_session)

    # Promo offers alone stay promotions at the API layer. The scheduler's
    # detect_deals job is responsible for promoting real strike-through promos
    # into `/api/deals` rows.
    before_deals = (
        (await db_session.execute(select(Deal).where(Deal.hotel_id == hotel_id))).scalars().all()
    )
    assert before_deals == []

    await _seed_historical_promo_discount_deal(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
    )

    # ── Historical promo_discount deal shape is still supported ─────────
    deals = (
        (
            await db_session.execute(
                select(Deal).where(Deal.hotel_id == hotel_id).order_by(Deal.detection_method)
            )
        )
        .scalars()
        .all()
    )
    assert len(deals) == 1
    deal = deals[0]
    assert deal.detection_method == "promo_discount"
    assert float(deal.discount_pct) == 50.0
    assert deal.source == "farvater_scrape"
    assert "farvater.travel" in deal.deep_link

    # ── /api/promotions returns both promo_offers ───────────────────────
    # Paginate because the dev DB may have many unrelated rows.
    our_promos = await _scoped_promos(client, hotel_id, country="TR")
    assert len(our_promos) == 2
    buckets = {p["bucket_slug"] for p in our_promos}
    assert buckets == {"gorjashhie-tury", "rannee-bronirovanie"}

    # ── /api/deals shows the historical promo_discount deal ─────────────
    our_deals = await _scoped_deals(client, hotel_id, country="TR")
    assert len(our_deals) == 1
    assert our_deals[0]["detection_method"] == "promo_discount"


async def test_e2e_bucket_filter_isolates_one_bucket(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """/api/promotions?bucket=gorjashhie-tury must exclude the
    rannee-bronirovanie promo even though both belong to the same hotel."""
    hotel_id, _ = await _seed_full(db_session)
    our = await _scoped_promos(client, hotel_id, bucket="gorjashhie-tury")
    assert len(our) == 1
    assert our[0]["bucket_slug"] == "gorjashhie-tury"


async def test_e2e_freshness_filter_blocks_stale_deals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A deal detected > 48h ago should NOT appear on /api/deals."""
    hotel_id, operator_id = await _seed_full(db_session)
    # Hand-insert a stale deal with detection_method=percentile
    stale_id = (
        await db_session.execute(
            text(
                """INSERT INTO deals
                     (hotel_id, operator_id, check_in, nights, meal_plan,
                      price_uah, baseline_p50, discount_pct, deep_link,
                      source, detection_method, detected_at)
                   VALUES (:h, :o, :ci, 7, 'AI', 8000, 12000, 33.33,
                           'https://farvater.travel/x', 'farvater_scrape',
                           'percentile', :dt)
                   RETURNING id"""
            ),
            {
                "h": hotel_id,
                "o": operator_id,
                "ci": date.today() + timedelta(days=30),
                "dt": datetime.now(UTC) - timedelta(hours=72),  # 3 days ago
            },
        )
    ).scalar_one()
    fresh_id = await _seed_historical_promo_discount_deal(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
    )

    our = await _scoped_deals(client, hotel_id)
    ids = {item["id"] for item in our}
    assert fresh_id in ids
    assert stale_id not in ids

    assert all(
        (
            datetime.now(UTC) - datetime.fromisoformat(d["detected_at"].replace("Z", "+00:00"))
        ).total_seconds()
        < 48 * 3600
        for d in our
    )
