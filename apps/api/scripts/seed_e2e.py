"""Seed a tiny, deterministic CI dataset for browser smoke tests.

This is intentionally not a product/demo seed path. It exists so GitHub Actions
can exercise the real API + DB + Next.js UI against an ephemeral database before
deploy. Rows are namespaced with ``ci-e2e-*`` slugs and safe to upsert.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence

from sqlalchemy import text

from src.infra.db import async_session_factory

FIXTURE_PREFIX = "ci-e2e-"
ALLOW_ENV = "FASTTRAVEL_ALLOW_E2E_SEED"
TOSSA_CANONICAL_SLUG = "fv-es-tossa-park-aparthotel"
TOSSA_OLD_SLUG = "fv-es-apart-hotel-ght-tossa-park"


def ensure_e2e_seed_allowed(*, cleanup: bool = False) -> None:
    if cleanup:
        return
    if os.getenv("ENVIRONMENT") == "prod":
        raise SystemExit("refusing to seed production with ci-e2e fixture data")
    if os.getenv(ALLOW_ENV) != "1":
        raise SystemExit(f"{ALLOW_ENV}=1 is required before seeding ci-e2e fixture data")


async def cleanup_e2e_data() -> None:
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                DELETE FROM deals
                WHERE hotel_id IN (
                    SELECT id FROM hotels WHERE canonical_slug LIKE :slug_prefix
                )
                   OR deep_link LIKE :link_prefix
                """
            ),
            {
                "slug_prefix": f"{FIXTURE_PREFIX}%",
                "link_prefix": f"%/{FIXTURE_PREFIX}%",
            },
        )
        await session.execute(
            text(
                """
                DELETE FROM price_observations
                WHERE raw_payload->>'fixture' = 'ci-e2e'
                   OR hotel_id IN (
                       SELECT id FROM hotels WHERE canonical_slug LIKE :slug_prefix
                   )
                """
            ),
            {"slug_prefix": f"{FIXTURE_PREFIX}%"},
        )
        await session.execute(
            text(
                """
                DELETE FROM hotel_operator_mapping
                WHERE external_id LIKE :slug_prefix
                   OR hotel_id IN (
                       SELECT id FROM hotels
                       WHERE canonical_slug LIKE :slug_prefix OR canonical_slug = :tossa_slug
                   )
                """
            ),
            {"slug_prefix": f"{FIXTURE_PREFIX}%", "tossa_slug": TOSSA_CANONICAL_SLUG},
        )
        await session.execute(
            text("DELETE FROM hotel_slug_aliases WHERE source_slug = :source_slug"),
            {"source_slug": TOSSA_OLD_SLUG},
        )
        await session.execute(
            text("DELETE FROM hotels WHERE canonical_slug = :slug"),
            {"slug": TOSSA_CANONICAL_SLUG},
        )
        await session.execute(
            text("DELETE FROM hotels WHERE canonical_slug LIKE :slug_prefix"),
            {"slug_prefix": f"{FIXTURE_PREFIX}%"},
        )
        await session.execute(
            text("DELETE FROM destinations WHERE region_slug LIKE :slug_prefix"),
            {"slug_prefix": f"{FIXTURE_PREFIX}%"},
        )
        await session.commit()


async def main() -> None:
    await cleanup_e2e_data()

    async with async_session_factory() as session:
        operator_id = await session.scalar(
            text(
                """
                INSERT INTO operators (code, display_name, affiliate_url_template)
                VALUES ('farvater', 'Farvater', 'https://farvater.travel/{hotel}')
                ON CONFLICT (code) DO UPDATE
                SET display_name = EXCLUDED.display_name
                RETURNING id
                """
            )
        )

        country_id = await session.scalar(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('TR', 'turkey', 'Туреччина', 'Turkey')
                ON CONFLICT (country_iso2, region_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    parent_id = NULL
                RETURNING id
                """
            )
        )

        destination_id = await session.scalar(
            text(
                """
                INSERT INTO destinations (
                    country_iso2,
                    region_slug,
                    name_uk,
                    name_en,
                    parent_id
                )
                VALUES ('TR', 'ci-e2e-kemer', 'Кемер', 'Kemer', :country_id)
                ON CONFLICT (country_iso2, region_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    parent_id = EXCLUDED.parent_id
                RETURNING id
                """
            ),
            {"country_id": country_id},
        )

        spain_id = await session.scalar(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en)
                VALUES ('ES', 'spain', 'Іспанія', 'Spain')
                ON CONFLICT (country_iso2, region_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    parent_id = NULL
                RETURNING id
                """
            )
        )

        tossa_destination_id = await session.scalar(
            text(
                """
                INSERT INTO destinations (
                    country_iso2,
                    region_slug,
                    name_uk,
                    name_en,
                    parent_id
                )
                VALUES ('ES', 'ci-e2e-tossa-de-mar', 'Тосса-де-Мар', 'Tossa de Mar', :spain_id)
                ON CONFLICT (country_iso2, region_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    parent_id = EXCLUDED.parent_id
                RETURNING id
                """
            ),
            {"spain_id": spain_id},
        )

        hotel_id = await session.scalar(
            text(
                """
                INSERT INTO hotels (
                    canonical_slug,
                    name_uk,
                    name_en,
                    stars,
                    destination_id,
                    photos_jsonb,
                    review_score,
                    review_count,
                    last_seen_at,
                    last_priced_at,
                    has_active_prices,
                    is_active
                )
                VALUES (
                    'ci-e2e-kemer-resort',
                    'CI E2E Kemer Resort',
                    'CI E2E Kemer Resort',
                    5,
                    :destination_id,
                    '[{"url":"https://images.unsplash.com/photo-1507525428034-b723cf961d3e","alt":"CI E2E Kemer Resort"}]'::jsonb,
                    9.1,
                    128,
                    NOW(),
                    NOW(),
                    TRUE,
                    TRUE
                )
                ON CONFLICT (canonical_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    stars = EXCLUDED.stars,
                    destination_id = EXCLUDED.destination_id,
                    photos_jsonb = EXCLUDED.photos_jsonb,
                    review_score = EXCLUDED.review_score,
                    review_count = EXCLUDED.review_count,
                    last_seen_at = NOW(),
                    last_priced_at = NOW(),
                    has_active_prices = TRUE,
                    is_active = TRUE
                RETURNING id
                """
            ),
            {"destination_id": destination_id},
        )

        tossa_hotel_id = await session.scalar(
            text(
                """
                INSERT INTO hotels (
                    canonical_slug,
                    name_uk,
                    name_en,
                    stars,
                    destination_id,
                    photos_jsonb,
                    review_score,
                    review_count,
                    last_seen_at,
                    last_priced_at,
                    has_active_prices,
                    is_active
                )
                VALUES (
                    :canonical_slug,
                    'Tossa Park Aparthotel',
                    'Tossa Park Aparthotel',
                    4,
                    :destination_id,
                    '[{"url":"https://images.unsplash.com/photo-1507525428034-b723cf961d3e","alt":"Tossa Park Aparthotel"}]'::jsonb,
                    8.4,
                    64,
                    NOW(),
                    NOW(),
                    TRUE,
                    TRUE
                )
                ON CONFLICT (canonical_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    stars = EXCLUDED.stars,
                    destination_id = EXCLUDED.destination_id,
                    photos_jsonb = EXCLUDED.photos_jsonb,
                    review_score = EXCLUDED.review_score,
                    review_count = EXCLUDED.review_count,
                    last_seen_at = NOW(),
                    last_priced_at = NOW(),
                    has_active_prices = TRUE,
                    is_active = TRUE
                RETURNING id
                """
            ),
            {"canonical_slug": TOSSA_CANONICAL_SLUG, "destination_id": tossa_destination_id},
        )

        await session.execute(
            text(
                """
                INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
                VALUES (:source_slug, :hotel_id, 'ci e2e duplicate slug')
                ON CONFLICT (source_slug) DO UPDATE
                SET hotel_id = EXCLUDED.hotel_id,
                    reason = EXCLUDED.reason
                """
            ),
            {"source_slug": TOSSA_OLD_SLUG, "hotel_id": tossa_hotel_id},
        )

        await session.execute(
            text(
                """
                DELETE FROM price_observations
                WHERE hotel_id = :hotel_id
                  AND raw_payload->>'fixture' = 'ci-e2e'
                """
            ),
            {"hotel_id": hotel_id},
        )

        await session.execute(
            text(
                """
                INSERT INTO price_observations (
                    observed_at,
                    hotel_id,
                    operator_id,
                    check_in,
                    nights,
                    meal_plan,
                    room_category,
                    adults,
                    departure_city,
                    price_uah,
                    price_original,
                    currency,
                    deep_link,
                    raw_payload
                )
                SELECT
                    NOW(),
                    :hotel_id,
                    :operator_id,
                    CURRENT_DATE + (days || ' days')::interval,
                    nights,
                    'AI',
                    'Standard',
                    2,
                    'WAW',
                    price_uah,
                    price_uah + 4500,
                    'UAH',
                    'https://farvater.travel/uk/hotel/ci-e2e-kemer-resort/',
                    '{"source":"farvater_scrape","fixture":"ci-e2e"}'::jsonb
                FROM (
                    VALUES
                        (21, 7, 32000),
                        (22, 7, 33500),
                        (23, 10, 47000),
                        (24, 14, 61000)
                ) AS seed(days, nights, price_uah)
                """
            ),
            {"hotel_id": hotel_id, "operator_id": operator_id},
        )

        await session.execute(
            text(
                """
                INSERT INTO price_observations (
                    observed_at,
                    hotel_id,
                    operator_id,
                    check_in,
                    nights,
                    meal_plan,
                    room_category,
                    adults,
                    departure_city,
                    price_uah,
                    price_original,
                    currency,
                    deep_link,
                    raw_payload
                )
                SELECT
                    NOW(),
                    :hotel_id,
                    :operator_id,
                    CURRENT_DATE + (days || ' days')::interval,
                    nights,
                    'AI',
                    'Standard',
                    2,
                    'WAW',
                    price_uah,
                    price_uah + 5000,
                    'UAH',
                    'https://farvater.travel/uk/hotel/es/tossa-park-aparthotel/',
                    '{"source":"farvater_scrape","fixture":"ci-e2e"}'::jsonb
                FROM (
                    VALUES
                        (21, 7, 36000),
                        (22, 8, 39000),
                        (23, 10, 52000)
                ) AS seed(days, nights, price_uah)
                """
            ),
            {"hotel_id": tossa_hotel_id, "operator_id": operator_id},
        )

        await session.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
        await session.execute(text("REFRESH MATERIALIZED VIEW hotel_calendar_prices"))
        await session.execute(text("REFRESH MATERIALIZED VIEW price_baselines"))

        await session.execute(
            text(
                """
                INSERT INTO deals (
                    hotel_id,
                    operator_id,
                    check_in,
                    nights,
                    meal_plan,
                    price_uah,
                    baseline_p50,
                    discount_pct,
                    deep_link,
                    detected_at,
                    source
                )
                VALUES (
                    :hotel_id,
                    :operator_id,
                    CURRENT_DATE + INTERVAL '21 days',
                    7,
                    'AI',
                    32000,
                    45000,
                    29.00,
                    'https://farvater.travel/uk/hotel/ci-e2e-kemer-resort/',
                    NOW(),
                    'farvater_scrape'
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {"hotel_id": hotel_id, "operator_id": operator_id},
        )

        await session.commit()

    print("seeded ci-e2e data")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed or clean the tiny ci-e2e browser-smoke fixture.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove ci-e2e fixture rows and exit",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    ensure_e2e_seed_allowed(cleanup=args.cleanup)
    if args.cleanup:
        asyncio.run(cleanup_e2e_data())
        print("removed ci-e2e data")
    else:
        asyncio.run(main())
