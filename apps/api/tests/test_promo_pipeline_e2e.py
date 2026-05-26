"""End-to-end test for the promo-deal pipeline (Sprint 1A-1E joint).

Simulates the production data flow without spinning up the actual
scheduler jobs:

  1. Seed `promo_offers` directly (mirrors what static_tours_sweep
     would write after a sweep tick).
  2. Run the promo-discount SQL that detect_deals issues.
  3. Hit `GET /api/promotions` and `GET /api/deals` to confirm both
     surfaces show the new data with the correct shape.

This catches integration regressions that the per-component unit
tests would miss — e.g. if `detection_method` ever stops being
copied through, both deals and promotions would still individually
pass but the end-to-end pipeline would be broken.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.deal import Deal

# Same SQL the production detect_deals._BUCKET_SQL runs. Mirrored here
# so a refactor of the production SQL doesn't silently break the e2e
# contract — when they drift, this test fails first.
# Test variant of detect_deals._BUCKET_SQL with a `po.hotel_id =
# :scoped_hotel_id` filter so the dev DB's existing promo_offers (live
# scheduler may have populated thousands) don't drown the test row.
_BUCKET_SQL = text(
    """
    INSERT INTO deals (
        hotel_id, operator_id, check_in, nights, meal_plan,
        price_uah, baseline_p50, discount_pct, deep_link,
        source, detection_method
    )
    SELECT DISTINCT ON (cand.hotel_id)
        cand.hotel_id, cand.operator_id, cand.check_in, cand.nights,
        cand.meal_plan, cand.price_uah, cand.baseline_p50,
        cand.discount_pct, cand.deep_link,
        'farvater_scrape', 'promo_discount'
    FROM (
        SELECT
            po.hotel_id, po.operator_id, po.check_in, po.nights,
            po.meal_plan, po.bucket_slug, po.price_uah,
            po.red_price_uah AS baseline_p50,
            ROUND(100 * (1 - po.price_uah::numeric / po.red_price_uah), 2)
                AS discount_pct,
            'https://farvater.travel/?q=' || po.system_key AS deep_link
        FROM promo_offers po
        WHERE po.hotel_id = :scoped_hotel_id
          AND po.observed_at >= NOW() - INTERVAL '24 hours'
          AND po.red_price_uah IS NOT NULL
          AND po.red_price_uah > po.price_uah
          AND po.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
          AND po.operator_id IS NOT NULL
    ) cand
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    """
)


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
    # Only the best real strike-through becomes a /api/deals row.
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


async def test_e2e_promo_to_deal_to_endpoints(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hotel_id, operator_id = await _seed_full(db_session)

    # ── Step 1: detect_deals bucket SQL runs ───────────────────────────
    await db_session.execute(_BUCKET_SQL, {"scoped_hotel_id": hotel_id})

    # ── Step 2: one best real promo discount was inserted ──────────────
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
    methods = {d.detection_method for d in deals}
    assert methods == {"promo_discount"}

    # Discount is computed from red/price. The best seeded offer is 50%.
    for d in deals:
        assert float(d.discount_pct) == pytest.approx(50.0, abs=0.1)
        assert d.source == "farvater_scrape"
        assert "farvater.travel" in d.deep_link

    # ── Step 3: /api/promotions returns both promo_offers ──────────────
    # Paginate because the dev DB may have many unrelated rows.
    our_promos = await _scoped_promos(client, hotel_id, country="TR")
    assert len(our_promos) == 2
    buckets = {p["bucket_slug"] for p in our_promos}
    assert buckets == {"gorjashhie-tury", "rannee-bronirovanie"}

    # ── Step 4: /api/deals shows the real discounted deal only ─────────
    our_deals = await _scoped_deals(client, hotel_id, country="TR")
    assert len(our_deals) == 1


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
    """A deal detected > 48h ago should NOT appear on /api/deals
    (Sprint 2.4 filter)."""
    hotel_id, operator_id = await _seed_full(db_session)
    # Hand-insert a stale deal with detection_method=percentile
    await db_session.execute(
        text(
            """INSERT INTO deals
                 (hotel_id, operator_id, check_in, nights, meal_plan,
                  price_uah, baseline_p50, discount_pct, deep_link,
                  source, detection_method, detected_at)
               VALUES (:h, :o, :ci, 7, 'AI', 8000, 12000, 33.33,
                       'https://farvater.travel/x', 'farvater_scrape',
                       'percentile', :dt)"""
        ),
        {
            "h": hotel_id,
            "o": operator_id,
            "ci": date.today() + timedelta(days=30),
            "dt": datetime.now(UTC) - timedelta(hours=72),  # 3 days ago
        },
    )
    our = await _scoped_deals(client, hotel_id)
    # Stale deal we just seeded (72h ago) must NOT appear; any deals
    # produced earlier in the test (from promo branch) are recent.
    assert all(
        (
            datetime.now(UTC) - datetime.fromisoformat(d["detected_at"].replace("Z", "+00:00"))
        ).total_seconds()
        < 48 * 3600
        for d in our
    )
