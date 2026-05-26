"""End-to-end test for the Sprint 1D bucket-deal detection branch.

Sits in the api/ test suite (not scheduler/) because it needs the
docker-compose Postgres + the existing SAVEPOINT fixture from
`apps/api/tests/conftest.py`. Mirrors the bucket SQL that
`apps/scheduler/src/jobs/detect_deals.py` runs.

The bucket branch reads from `promo_offers` (written by
`static_tours_sweep`) and inserts `deals` rows only when Farvater provides a
real strike-through with `detection_method = 'promo_discount'`.
The key behaviours under test:

  1. A fresh promo_offer in the +5..+90d window with real discount becomes a deal.
  2. detection_method is promo_discount, not the bucket slug.
  3. Stale promo_offers (>24h old) do NOT become deals.
  4. The per-hotel cooldown blocks repeats within the cooldown window.
  5. Same hotel in multiple buckets produces one best promo_discount deal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.deal import Deal

# Mirror of production detect_deals._BUCKET_SQL with one tweak: a
# `po.hotel_id = :scoped_hotel_id` filter that lets the test scope to
# the row it just seeded, so the shared dev DB's existing promo_offers
# don't pollute the assertion.
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
            'https://farvater.travel/test?q=' || po.system_key AS deep_link
        FROM promo_offers po
        WHERE po.hotel_id = :scoped_hotel_id
          AND po.observed_at >= NOW() - INTERVAL '24 hours'
          AND po.red_price_uah IS NOT NULL
          AND po.red_price_uah > po.price_uah
          AND po.check_in BETWEEN CURRENT_DATE + INTERVAL '5 days'
                              AND CURRENT_DATE + INTERVAL '90 days'
          AND po.operator_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM deals d2
              WHERE d2.hotel_id = po.hotel_id
                AND d2.detection_method = 'promo_discount'
                AND d2.detected_at >= NOW() - make_interval(hours => :cooldown_hours)
          )
    ) cand
    ORDER BY cand.hotel_id, cand.discount_pct DESC
    LIMIT :max_per_run
    RETURNING id
    """
)


async def _seed(session: AsyncSession, *, suffix: str | None = None) -> tuple[int, int]:
    """Insert minimal operator + destination + hotel; return (hotel_id, operator_id)."""
    suffix = suffix or uuid4().hex[:8]
    operator_id = (
        await session.execute(
            text("INSERT INTO operators (code, display_name) " "VALUES (:c, :n) RETURNING id"),
            {"c": f"farvater-bucket-{suffix}", "n": "Farvater (bucket test)"},
        )
    ).scalar_one()
    destination_id = (
        await session.execute(
            text(
                "INSERT INTO destinations (country_iso2, region_slug, name_uk) "
                "VALUES ('TR', :slug, 'Туреччина') RETURNING id"
            ),
            {"slug": f"tr-bucket-{suffix}"},
        )
    ).scalar_one()
    hotel_id = (
        await session.execute(
            text(
                "INSERT INTO hotels (canonical_slug, name_uk, destination_id, is_active) "
                "VALUES (:slug, 'Hotel', :dest, TRUE) RETURNING id"
            ),
            {"slug": f"fv-tr-bucket-{suffix}", "dest": destination_id},
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
    pid = (
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
    return int(pid)


async def _run_bucket(
    session: AsyncSession,
    *,
    scoped_hotel_id: int,
    cooldown_hours: int = 24,
    max_per_run: int = 20,
) -> int:
    """Run the bucket-detect SQL scoped to one seeded hotel — see the
    SQL above for the `:scoped_hotel_id` injection point."""
    result = await session.execute(
        _BUCKET_SQL,
        {
            "scoped_hotel_id": scoped_hotel_id,
            "cooldown_hours": cooldown_hours,
            "max_per_run": max_per_run,
        },
    )
    rows = result.all()
    return len(rows)


# ── tests ───────────────────────────────────────────────────────────────


async def test_fresh_promo_becomes_deal(db_session: AsyncSession) -> None:
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        price_uah=29847,
        red_price_uah=39847,
    )

    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 1

    deal = (await db_session.execute(select(Deal).where(Deal.hotel_id == hotel_id))).scalar_one()
    assert deal.detection_method == "promo_discount"
    assert deal.source == "farvater_scrape"


async def test_detection_method_is_promo_discount(db_session: AsyncSession) -> None:
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="rannee-bronirovanie",
        price_uah=29847,
        red_price_uah=39847,
    )
    await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    deal = (await db_session.execute(select(Deal).where(Deal.hotel_id == hotel_id))).scalar_one()
    assert deal.detection_method == "promo_discount"


async def test_stale_promo_does_not_become_deal(db_session: AsyncSession) -> None:
    """observed_at >24h ago — should be filtered out."""
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        observed_at=datetime.now(UTC) - timedelta(hours=48),
    )
    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 0


async def test_check_in_outside_window_skipped(db_session: AsyncSession) -> None:
    """check_in <+5d or >+90d — outside the deal window."""
    hotel_id, operator_id = await _seed(db_session)
    # Too soon
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        check_in=datetime.now(UTC).date() + timedelta(days=2),
        bucket="gorjashhie-tury",
    )
    # Too far
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        check_in=datetime.now(UTC).date() + timedelta(days=120),
        bucket="rannee-bronirovanie",
    )
    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 0


async def test_cooldown_blocks_repeat_in_same_bucket(db_session: AsyncSession) -> None:
    """Two promo rows in same bucket → cooldown lets only the first through."""
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        system_key="sk-1",
        price_uah=29847,
        red_price_uah=39847,
    )
    first_count = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert first_count == 1

    # Second promo, same bucket, 1h later — cooldown should block it.
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        system_key="sk-2",
        observed_at=datetime.now(UTC) + timedelta(hours=1),
        price_uah=29847,
        red_price_uah=39847,
    )
    second_count = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert second_count == 0


async def test_same_hotel_two_buckets_inserts_one_best_discount(db_session: AsyncSession) -> None:
    """Bucket membership is promo metadata; deals keep one best real discount."""
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="gorjashhie-tury",
        system_key="sk-a",
        price_uah=30000,
        red_price_uah=40000,
    )
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket="akcionnye-tury",
        system_key="sk-b",
        price_uah=25000,
        red_price_uah=50000,
    )
    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 1

    deal = (await db_session.execute(select(Deal).where(Deal.hotel_id == hotel_id))).scalar_one()
    assert deal.detection_method == "promo_discount"
    assert int(deal.price_uah) == 25000


async def test_real_strike_through_yields_discount_pct(
    db_session: AsyncSession,
) -> None:
    """When red_price_uah > price_uah, discount_pct is computed
    correctly. Today HAR shows red==price, but the schema supports a
    real strike-through whenever farvater starts emitting one."""
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        price_uah=42000,
        red_price_uah=58000,
    )
    await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    deal = (await db_session.execute(select(Deal).where(Deal.hotel_id == hotel_id))).scalar_one()
    assert float(deal.discount_pct) == pytest.approx(27.59, abs=0.1)
    assert deal.baseline_p50 == 58000


async def test_no_red_price_does_not_become_deal(db_session: AsyncSession) -> None:
    """Bucket membership without a strike-through stays in promo_offers."""
    hotel_id, operator_id = await _seed(db_session)
    await _add_promo(
        db_session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        price_uah=29847,
        red_price_uah=None,
    )
    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 0


async def test_promo_without_operator_skipped(db_session: AsyncSession) -> None:
    """operator_id IS NULL → skip (FK to operators is SET NULL, but the
    deals.operator_id is NOT NULL — we won't insert a row that would
    fail FK)."""
    hotel_id, operator_id = await _seed(db_session)

    # Insert promo with operator_id NULL by direct SQL — the helper
    # always sets it.
    sk = f"sk-{uuid4().hex[:12]}"
    await db_session.execute(
        text(
            """INSERT INTO promo_offers
                 (observed_at, hotel_id, operator_id, bucket_slug, system_key,
                  check_in, nights, meal_plan, price_uah)
               VALUES (NOW(), :h, NULL, 'gorjashhie-tury', :sk,
                       CURRENT_DATE + INTERVAL '30 days', 7, 'AI', 30000)"""
        ),
        {"h": hotel_id, "sk": sk},
    )
    inserted = await _run_bucket(db_session, scoped_hotel_id=hotel_id)
    assert inserted == 0
