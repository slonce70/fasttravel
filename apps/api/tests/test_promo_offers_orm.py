"""ORM + schema sanity tests for promo_offers (migration 012) and
deals.detection_method (migration 013).

We test against the real Postgres via the existing SAVEPOINT fixture
because:
  1. The migration uses partial defaults and a multi-column index with
     DESC ordering — those don't get exercised by SQLAlchemy create_all,
     so a unit test against an in-memory DB would miss schema drift.
  2. The PromoOffer ORM has 9 boolean columns with server defaults; a
     round-trip insert/select confirms the SQLAlchemy mapping matches
     the migration's column types and defaults.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.deal import Deal
from src.models.promo_offer import PromoOffer


async def _seed_hotel(session: AsyncSession) -> tuple[int, int]:
    """Insert minimal operator + destination + hotel so promo_offers FKs
    resolve. Mirrors `test_deals.py::_seed_minimal_deal` style (raw SQL
    for hotels because `coords` is a `point` column the ORM can't bind
    directly)."""
    suffix = uuid4().hex[:8]
    operator_id = (
        await session.execute(
            text("INSERT INTO operators (code, display_name) " "VALUES (:c, :n) RETURNING id"),
            {"c": f"farvater-test-{suffix}", "n": "Farvater (test)"},
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
                "INSERT INTO hotels (canonical_slug, name_uk, destination_id, is_active) "
                "VALUES (:slug, :name, :dest, TRUE) RETURNING id"
            ),
            {
                "slug": f"fv-tr-test-hotel-{suffix}",
                "name": "Test Hotel",
                "dest": destination_id,
            },
        )
    ).scalar_one()

    return hotel_id, operator_id


# ── promo_offers round-trip ──────────────────────────────────────────────


async def test_promo_offer_minimal_round_trip(db_session: AsyncSession) -> None:
    """Insert with only required columns; verify defaults match migration."""
    hotel_id, operator_id = await _seed_hotel(db_session)

    offer = PromoOffer(
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket_slug="gorjashhie-tury",
        system_key=f"SK-{uuid4().hex[:12]}",
        check_in=date(2026, 7, 15),
        nights=7,
        meal_plan="AI",
        price_uah=29847,
    )
    db_session.add(offer)
    await db_session.flush()

    fetched = (
        await db_session.execute(select(PromoOffer).where(PromoOffer.id == offer.id))
    ).scalar_one()

    # Required fields land verbatim
    assert fetched.bucket_slug == "gorjashhie-tury"
    assert fetched.hotel_id == hotel_id
    assert fetched.operator_id == operator_id
    assert fetched.check_in == date(2026, 7, 15)
    assert fetched.nights == 7
    assert fetched.meal_plan == "AI"
    assert fetched.price_uah == 29847

    # Boolean defaults from migration 012 are FALSE — verify the ORM
    # respects them on insert (rather than emitting NULL or skipping).
    assert fetched.is_hot is False
    assert fetched.is_early is False
    assert fetched.is_best_deal is False
    assert fetched.is_recommended is False
    assert fetched.is_choice_farvater is False
    assert fetched.is_otp is False
    assert fetched.is_last_seats is False
    assert fetched.is_black_friday is False
    assert fetched.is_vip is False

    # Optional fields default to NULL
    assert fetched.red_price_uah is None
    assert fetched.promotion_end_date is None
    assert fetched.loaded_date is None
    assert fetched.hot_type is None
    assert fetched.early_type is None

    # observed_at is server-set to NOW() — should be very recent
    assert (datetime.now(UTC) - fetched.observed_at) < timedelta(minutes=1)


async def test_promo_offer_full_round_trip(db_session: AsyncSession) -> None:
    """All optional fields set — matches the shape we'll get from the
    HAR-confirmed static-tours endpoint."""
    hotel_id, operator_id = await _seed_hotel(db_session)
    sk = f"SK-{uuid4().hex[:12]}"

    offer = PromoOffer(
        hotel_id=hotel_id,
        operator_id=operator_id,
        bucket_slug="gorjashhie-tury",
        system_key=sk,
        check_in=date(2026, 7, 15),
        nights=10,
        meal_plan="UAI",
        is_hot=True,
        is_recommended=True,
        is_choice_farvater=True,
        is_otp=True,
        hot_type="Last Minute",
        price_uah=42000,
        red_price_uah=58000,  # HAR finding: usually == price_uah, but
        # schema supports a real strike-through
        # whenever farvater starts emitting one.
        promotion_end_date=date(2026, 8, 1),
        loaded_date=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        operator_name="Alliance",
        operator_id_int=42,
        raw_payload={"systemKey": sk, "isPromo": False, "extra": "preserved"},
    )
    db_session.add(offer)
    await db_session.flush()

    fetched = (
        await db_session.execute(select(PromoOffer).where(PromoOffer.id == offer.id))
    ).scalar_one()

    assert fetched.is_hot is True
    assert fetched.is_recommended is True
    assert fetched.is_choice_farvater is True
    assert fetched.is_otp is True
    assert fetched.hot_type == "Last Minute"
    assert fetched.red_price_uah == 58000
    assert fetched.promotion_end_date == date(2026, 8, 1)
    assert fetched.operator_name == "Alliance"
    assert fetched.operator_id_int == 42
    assert fetched.raw_payload == {
        "systemKey": sk,
        "isPromo": False,
        "extra": "preserved",
    }


async def test_promo_offers_natural_unique_index(db_session: AsyncSession) -> None:
    """Same (system_key, bucket_slug, observed_at) tuple must reject the
    second write — this is what stops duplicate scrape passes from
    bloating the table."""
    from sqlalchemy.exc import IntegrityError

    hotel_id, _operator_id = await _seed_hotel(db_session)
    sk = f"SK-{uuid4().hex[:12]}"
    observed = datetime.now(UTC).replace(microsecond=0)

    db_session.add(
        PromoOffer(
            observed_at=observed,
            hotel_id=hotel_id,
            bucket_slug="gorjashhie-tury",
            system_key=sk,
            check_in=date(2026, 7, 1),
            nights=7,
            meal_plan="AI",
            price_uah=10000,
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                PromoOffer(
                    observed_at=observed,  # identical timestamp
                    hotel_id=hotel_id,
                    bucket_slug="gorjashhie-tury",  # identical bucket
                    system_key=sk,  # identical system_key
                    check_in=date(2026, 7, 1),
                    nights=7,
                    meal_plan="AI",
                    price_uah=10000,
                )
            )
            await db_session.flush()


async def test_promo_offers_same_system_key_different_bucket_allowed(
    db_session: AsyncSession,
) -> None:
    """A tour can legitimately appear in two buckets (e.g. both
    `gorjashhie-tury` and `IsChoiceFarvater`-derived); the unique key
    is (system_key, bucket_slug, observed_at), not system_key alone."""
    hotel_id, _operator_id = await _seed_hotel(db_session)
    sk = f"SK-{uuid4().hex[:12]}"
    observed = datetime.now(UTC).replace(microsecond=0)

    db_session.add(
        PromoOffer(
            observed_at=observed,
            hotel_id=hotel_id,
            bucket_slug="gorjashhie-tury",
            system_key=sk,
            check_in=date(2026, 7, 1),
            nights=7,
            meal_plan="AI",
            price_uah=10000,
        )
    )
    db_session.add(
        PromoOffer(
            observed_at=observed,
            hotel_id=hotel_id,
            bucket_slug="rannee-bronirovanie",  # different bucket → allowed
            system_key=sk,
            check_in=date(2026, 7, 1),
            nights=7,
            meal_plan="AI",
            price_uah=10000,
        )
    )
    await db_session.flush()

    count = (await db_session.execute(select(PromoOffer).where(PromoOffer.system_key == sk))).all()
    assert len(count) == 2


# ── deals.detection_method ───────────────────────────────────────────────


async def test_deal_detection_method_defaults_to_percentile(
    db_session: AsyncSession,
) -> None:
    """Migration 013's server_default='percentile' should kick in when
    INSERT omits the column. The ORM's default='percentile' covers the
    SQLAlchemy-side too."""
    hotel_id, operator_id = await _seed_hotel(db_session)

    deal_id = (
        await db_session.execute(
            text(
                """INSERT INTO deals
                     (hotel_id, operator_id, check_in, nights, meal_plan,
                      price_uah, baseline_p50, discount_pct, source)
                   VALUES
                     (:h, :o, :ci, 7, 'AI', 8000, 12000, 33.33, 'farvater_scrape')
                   RETURNING id"""
            ),
            {"h": hotel_id, "o": operator_id, "ci": date(2026, 8, 1)},
        )
    ).scalar_one()

    deal = (await db_session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
    assert deal.detection_method == "percentile"


async def test_deal_detection_method_accepts_promo_discount_value(
    db_session: AsyncSession,
) -> None:
    """Historical promo-discount rows keep their semantic detection method."""
    hotel_id, operator_id = await _seed_hotel(db_session)

    deal_id = (
        await db_session.execute(
            text(
                """INSERT INTO deals
                     (hotel_id, operator_id, check_in, nights, meal_plan,
                      price_uah, baseline_p50, discount_pct, source,
                      detection_method)
                   VALUES
                     (:h, :o, :ci, 7, 'AI', 8000, 12000, 33.33,
                      'farvater_scrape', 'promo_discount')
                   RETURNING id"""
            ),
            {"h": hotel_id, "o": operator_id, "ci": date(2026, 8, 1)},
        )
    ).scalar_one()

    deal = (await db_session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
    assert deal.detection_method == "promo_discount"
