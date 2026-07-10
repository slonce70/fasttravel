from __future__ import annotations

import importlib
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jobs.notify_subscribers import _MATCH_SQL
from src.jobs.post_deals import (
    _PENDING_TELEGRAM_MSG_ID,
    _POSTING_CLAIM_TTL_MINUTES,
    _SELECT_UNPOSTED,
    MIN_BROADCAST_DISCOUNT_PCT,
)

detect_deals_module = importlib.import_module("src.jobs.detect_deals")


class _SessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


async def _seed_market(
    session: AsyncSession,
    *,
    country_iso2: str = "ZZ",
    suffix: str | None = None,
) -> tuple[int, int, int]:
    suffix = suffix or uuid4().hex[:10]
    operator_id = (
        await session.execute(
            text("INSERT INTO operators (code, display_name) VALUES (:code, :name) RETURNING id"),
            {"code": f"test-op-{suffix}", "name": "Test Operator"},
        )
    ).scalar_one()
    country_id = (
        await session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk)
                VALUES (:country, :slug, :name)
                RETURNING id
                """
            ),
            {
                "country": country_iso2,
                "slug": f"country-{suffix}",
                "name": f"Country {suffix}",
            },
        )
    ).scalar_one()
    region_id = (
        await session.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, parent_id)
                VALUES (:country, :slug, :name, :parent_id)
                RETURNING id
                """
            ),
            {
                "country": country_iso2,
                "slug": f"region-{suffix}",
                "name": f"Region {suffix}",
                "parent_id": country_id,
            },
        )
    ).scalar_one()
    hotel_id = (
        await session.execute(
            text(
                """
                INSERT INTO hotels (canonical_slug, name_uk, stars, destination_id, is_active)
                VALUES (:slug, :name, 4, :destination_id, TRUE)
                RETURNING id
                """
            ),
            {
                "slug": f"test-hotel-{suffix}",
                "name": f"Test Hotel {suffix}",
                "destination_id": region_id,
            },
        )
    ).scalar_one()
    return int(hotel_id), int(operator_id), int(region_id)


async def _seed_deal(
    session: AsyncSession,
    *,
    country_iso2: str = "ZZ",
    detection_method: str = "calendar_anomaly",
    discount_pct: float = 12,
    source: str | None = "farvater_scrape",
    age_hours: int = 1,
    suffix: str | None = None,
    hotel_id: int | None = None,
    operator_id: int | None = None,
    check_in_days: int = 30,
) -> int:
    if hotel_id is None or operator_id is None:
        hotel_id, operator_id, _ = await _seed_market(
            session,
            country_iso2=country_iso2,
            suffix=suffix,
        )
    deal_id = (
        await session.execute(
            text(
                """
                INSERT INTO deals (
                    hotel_id, operator_id, check_in, nights, meal_plan,
                    price_uah, baseline_p50, discount_pct, deep_link,
                    detected_at, source, detection_method
                )
                VALUES (
                    :hotel_id, :operator_id,
                    CURRENT_DATE + make_interval(days => :check_in_days),
                    7, 'AI', 32000, 39000, :discount_pct,
                    'https://example.test/deal',
                    NOW() - make_interval(hours => :age_hours),
                    :source, :detection_method
                )
                RETURNING id
                """
            ),
            {
                "hotel_id": hotel_id,
                "operator_id": operator_id,
                "check_in_days": check_in_days,
                "discount_pct": discount_pct,
                "age_hours": age_hours,
                "source": source,
                "detection_method": detection_method,
            },
        )
    ).scalar_one()
    return int(deal_id)


async def _seed_filter(
    session: AsyncSession,
    *,
    country_iso2: str,
    chat_id: int,
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO telegram_subscribers (chat_id, username, is_blocked)
            VALUES (:chat_id, :username, FALSE)
            """
        ),
        {"chat_id": chat_id, "username": f"test_{chat_id}"},
    )
    filter_id = (
        await session.execute(
            text(
                """
                INSERT INTO telegram_subscriber_filters (
                    chat_id, country_iso2, max_price_uah, min_stars,
                    meal_plan, is_active
                )
                VALUES (:chat_id, :country, 100000, 3, 'AI', TRUE)
                RETURNING id
                """
            ),
            {"chat_id": chat_id, "country": country_iso2},
        )
    ).scalar_one()
    return int(filter_id)


async def _seed_promo_offer(
    session: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    red_price_uah: int | None = 50000,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO promo_offers (
                observed_at, hotel_id, operator_id, bucket_slug, system_key,
                check_in, nights, meal_plan, is_hot, price_uah, red_price_uah
            )
            VALUES (
                NOW(), :hotel_id, :operator_id, 'gorjashhie-tury', :system_key,
                CURRENT_DATE + INTERVAL '30 days', 7, 'AI', TRUE, 25000, :red_price_uah
            )
            """
        ),
        {
            "hotel_id": hotel_id,
            "operator_id": operator_id,
            "red_price_uah": red_price_uah,
            "system_key": f"promo-{uuid4().hex[:12]}",
        },
    )


async def _seed_price_rows(
    session: AsyncSession,
    *,
    hotel_id: int,
    operator_id: int,
    rows: list[tuple[int, str, int]],
) -> None:
    db_today = await session.scalar(text("SELECT CURRENT_DATE"))
    assert isinstance(db_today, date)
    await session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            )
            VALUES (
                NOW(), :hotel_id, :operator_id,
                :check_in, 7, 'AI', :room_category,
                :price_uah, 'UAH', :deep_link
            )
            """
        ),
        [
            {
                "hotel_id": hotel_id,
                "operator_id": operator_id,
                "check_in": db_today + timedelta(days=date_offset),
                "room_category": room_category,
                "price_uah": price_uah,
                "deep_link": f"https://example.test/date-dip/{idx}",
            }
            for idx, (date_offset, room_category, price_uah) in enumerate(rows)
        ],
    )
    await session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))


@pytest.mark.asyncio
async def test_post_deals_selects_only_recent_real_non_peer_channel_deals(
    session: AsyncSession,
) -> None:
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))

    expected_id = await _seed_deal(session, discount_pct=12)
    await _seed_deal(session, detection_method="peer_anomaly", discount_pct=80)
    await _seed_deal(session, discount_pct=90, age_hours=7)
    await _seed_deal(session, discount_pct=95, source=None)
    await _seed_deal(session, discount_pct=3)

    rows = (
        await session.execute(
            _SELECT_UNPOSTED,
            {
                "lim": 20,
                "min_discount_pct": MIN_BROADCAST_DISCOUNT_PCT,
                "pending_msg_id": _PENDING_TELEGRAM_MSG_ID,
                "claim_ttl_minutes": _POSTING_CLAIM_TTL_MINUTES,
            },
        )
    ).all()

    assert [int(row.id) for row in rows] == [expected_id]


@pytest.mark.asyncio
async def test_notify_match_sql_applies_thresholds_and_notification_ledger(
    session: AsyncSession,
) -> None:
    await session.execute(text("UPDATE telegram_subscriber_filters SET is_active = FALSE"))

    general_filter = await _seed_filter(session, country_iso2="GA", chat_id=-910001)
    general_deal = await _seed_deal(session, country_iso2="GA", discount_pct=5)
    await _seed_deal(session, country_iso2="GA", discount_pct=3)

    peer_low_filter = await _seed_filter(session, country_iso2="PL", chat_id=-910002)
    await _seed_deal(
        session,
        country_iso2="PL",
        detection_method="peer_anomaly",
        discount_pct=24,
    )

    peer_high_filter = await _seed_filter(session, country_iso2="PH", chat_id=-910003)
    peer_high_deal = await _seed_deal(
        session,
        country_iso2="PH",
        detection_method="peer_anomaly",
        discount_pct=26,
    )

    ledger_filter = await _seed_filter(session, country_iso2="LD", chat_id=-910004)
    ledger_deal = await _seed_deal(session, country_iso2="LD", discount_pct=40)
    await session.execute(
        text(
            """
            INSERT INTO telegram_filter_notifications (filter_id, deal_id)
            VALUES (:filter_id, :deal_id)
            """
        ),
        {"filter_id": ledger_filter, "deal_id": ledger_deal},
    )

    rows = (
        await session.execute(
            _MATCH_SQL,
            {
                "max_per_run": 20,
                "min_discount_pct": 4,
                "min_peer_discount_pct": 25,
                "freshness_hours": 6,
            },
        )
    ).all()

    matches = {int(row.filter_id): int(row.deal_id) for row in rows}
    assert matches == {
        general_filter: general_deal,
        peer_high_filter: peer_high_deal,
    }
    assert peer_low_filter not in matches
    assert ledger_filter not in matches


@pytest.mark.asyncio
async def test_notify_subscribers_uses_same_freshness_window_as_public_channel(
    session: AsyncSession,
) -> None:
    fresh_filter = await _seed_filter(session, country_iso2="FR", chat_id=-910005)
    fresh_deal = await _seed_deal(session, country_iso2="FR", discount_pct=25, age_hours=5)

    stale_filter = await _seed_filter(session, country_iso2="ST", chat_id=-910006)
    await _seed_deal(session, country_iso2="ST", discount_pct=25, age_hours=7)

    rows = (
        await session.execute(
            _MATCH_SQL,
            {
                "max_per_run": 20,
                "min_discount_pct": 4,
                "min_peer_discount_pct": 25,
                "freshness_hours": 6,
            },
        )
    ).all()

    matches = {int(row.filter_id): int(row.deal_id) for row in rows}
    assert matches[fresh_filter] == fresh_deal
    assert stale_filter not in matches


@pytest.mark.asyncio
async def test_detect_deals_inserts_calendar_anomaly_for_local_v_dip(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="VZ")
    # A flat 100000 run with a single V-bottom at +27 (85000): >=3 matching
    # neighbours on each side within +-7d, so it is a genuine regime-local dip.
    rows = [(o, "Standard Room", 100000) for o in range(20, 35) if o != 27]
    rows.append((27, "Standard Room", 85000))
    await _seed_price_rows(session, hotel_id=hotel_id, operator_id=operator_id, rows=rows)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                    price_uah,
                    baseline_p50,
                    discount_pct,
                    source,
                    detection_method
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'calendar_anomaly'
                """
                ),
                {"hotel_id": hotel_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["price_uah"] == 85000
    # baseline = matched-side average of the surrounding flat run.
    assert row["baseline_p50"] == 100000
    assert float(row["discount_pct"]) == 15.0
    assert row["source"] == "farvater_scrape"
    assert row["detection_method"] == "calendar_anomaly"


@pytest.mark.asyncio
async def test_detect_deals_skips_dip_on_stale_candidate_price(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="SL")
    db_today = await session.scalar(text("SELECT CURRENT_DATE"))
    assert isinstance(db_today, date)
    # Fresh flat shoulders at 100000; the +27 V-bottom (85000) is a 2-day-old
    # observation. The freshness gate must refuse to advertise a stale price
    # even though the shape is a textbook dip.
    await _seed_price_rows(
        session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        rows=[(o, "Standard Room", 100000) for o in range(20, 35) if o != 27],
    )
    await session.execute(
        text(
            """
            INSERT INTO price_observations (
                observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
                room_category, price_uah, currency, deep_link
            ) VALUES (
                NOW() - INTERVAL '2 days', :hotel_id, :operator_id,
                :check_in, 7, 'AI', 'Standard Room', 85000, 'UAH',
                'https://example.test/stale-dip'
            )
            """
        ),
        {
            "hotel_id": hotel_id,
            "operator_id": operator_id,
            "check_in": db_today + timedelta(days=27),
        },
    )
    await session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    deals = (
        await session.execute(
            text(
                """
                SELECT id FROM deals
                WHERE hotel_id = :hotel_id AND detection_method = 'calendar_anomaly'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    assert deals == []


@pytest.mark.asyncio
async def test_detect_deals_does_not_compare_standard_target_to_premium_neighbors(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="TZ")
    # Standard family is flat (no dip); a parallel deluxe family sits far higher.
    # The detector partitions by room_family, so the flat standard target is
    # never turned into a "dip" by the pricier deluxe rows — a naive cross-room
    # baseline (~150k) would otherwise read 100k as a 33% drop.
    rows = [(o, "Standard Room", 100000) for o in range(24, 31)]
    rows += [(o, "Deluxe Room", 200000) for o in range(24, 31)]
    await _seed_price_rows(session, hotel_id=hotel_id, operator_id=operator_id, rows=rows)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    deals = (
        await session.execute(
            text(
                """
                SELECT id
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'calendar_anomaly'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    assert deals == []


@pytest.mark.asyncio
async def test_detect_deals_rejects_dip_deeper_than_depth_cap(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean V-bottom deeper than max_depth_pct must NOT become a deal.

    Real same-hotel date-dips are modest; a drop deeper than ~35% is almost
    always a glitch cliff or a synthetic placeholder price, so the depth cap
    rejects it even though the V-shape and matching shoulders are otherwise valid.
    """
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="SY")
    # Flat 100000 run with a 40%-deep bottom at +27 (60000) — above the 35% cap.
    rows = [(o, "Standard Room", 100000) for o in range(20, 35) if o != 27]
    rows.append((27, "Standard Room", 60000))
    await _seed_price_rows(session, hotel_id=hotel_id, operator_id=operator_id, rows=rows)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    deals = (
        await session.execute(
            text(
                """
                SELECT discount_pct
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'calendar_anomaly'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    # The only V-bottom here is 40% deep — above the 35% cap — so nothing posts.
    assert deals == []


@pytest.mark.asyncio
async def test_detect_deals_rejects_seasonal_step_via_side_ratio(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate that is a two-sided V-bottom but whose shoulders are DIFFERENT
    price regimes (a seasonal step) must not produce a deal.

    This is the Ugur class: the candidate sits at its own cheap-season floor with
    a cheap preceding shoulder and a peak-season following shoulder. The discount
    vs the blended baseline is under the depth cap, so only the return-to-baseline
    side-ratio guard catches it — genuine dips return to ONE level on both sides.
    """
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="MZ")
    # Cheap regime before (+20..+26 = 50000), a V-bottom at +27 (49000), then a
    # peak-season step after (+28..+34 = 90000). side_ratio 90000/50000 = 1.8 > 1.15.
    rows = [(o, "Standard Room", 50000) for o in range(20, 27)]
    rows.append((27, "Standard Room", 49000))
    rows += [(o, "Standard Room", 90000) for o in range(28, 35)]
    await _seed_price_rows(session, hotel_id=hotel_id, operator_id=operator_id, rows=rows)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    deals = (
        await session.execute(
            text(
                """
                SELECT discount_pct
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'calendar_anomaly'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    # Discount vs blended baseline is ~30% (under the cap) but the two shoulders
    # are a step (side_ratio 1.8 > 1.15) — the return-to-baseline guard rejects it.
    assert deals == []


@pytest.mark.asyncio
async def test_detect_deals_ignores_same_room_casing_phantom(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await session.execute(text("UPDATE deals SET posted_at = NOW() WHERE posted_at IS NULL"))
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="QZ")
    # A flat 100000 run, but +27 also carries a phantom cheap re-listing of the
    # SAME room under a different casing ('Deluxe Room' 70000 vs 'DELUXE ROOM'
    # 100000). The same-room MAX-collapse neutralises it, so +27 stays at 100000
    # (no dip). Without the collapse this would be a false 30% dip.
    rows = [(o, "DELUXE ROOM", 100000) for o in range(20, 35)]
    rows.append((27, "Deluxe Room", 70000))
    await _seed_price_rows(session, hotel_id=hotel_id, operator_id=operator_id, rows=rows)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=200)

    deals = (
        await session.execute(
            text(
                """
                SELECT id
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'calendar_anomaly'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    assert deals == []


@pytest.mark.asyncio
async def test_detect_deals_converts_real_promo_offers_to_promo_discount_deals(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="PO")
    await _seed_promo_offer(session, hotel_id=hotel_id, operator_id=operator_id)
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=20)

    promo_deals = (
        await session.execute(
            text(
                """
                SELECT id
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'promo_discount'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    assert len(promo_deals) == 1


@pytest.mark.asyncio
async def test_detect_deals_ignores_bucket_promos_without_real_strike_through(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hotel_id, operator_id, _ = await _seed_market(session, country_iso2="PB")
    await _seed_promo_offer(
        session,
        hotel_id=hotel_id,
        operator_id=operator_id,
        red_price_uah=None,
    )
    monkeypatch.setattr(
        detect_deals_module,
        "async_session_factory",
        lambda: _SessionContext(session),
    )

    await detect_deals_module.detect_deals(cooldown_hours=0, max_per_run=20)

    promo_deals = (
        await session.execute(
            text(
                """
                SELECT id
                FROM deals
                WHERE hotel_id = :hotel_id
                  AND detection_method = 'promo_discount'
                """
            ),
            {"hotel_id": hotel_id},
        )
    ).all()
    assert promo_deals == []
