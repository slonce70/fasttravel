"""Farvater hotel/operator upsert helpers.

This module owns DB writes for catalog hotel identity and operator mapping.
Price insertion and snapshot orchestration live in job modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.farvater_catalog import make_slug

OPERATOR_CODE = "farvater"

COUNTRY_ROOTS: dict[str, tuple[str, str, str]] = {
    "TR": ("turkey", "Туреччина", "Turkey"),
    "EG": ("egypt", "Єгипет", "Egypt"),
    "AE": ("uae", "ОАЕ", "United Arab Emirates"),
    "GR": ("greece", "Греція", "Greece"),
    "ES": ("spain", "Іспанія", "Spain"),
    "BG": ("bulgaria", "Болгарія", "Bulgaria"),
    "TH": ("thailand", "Таїланд", "Thailand"),
    "CY": ("cyprus", "Кіпр", "Cyprus"),
    "HR": ("croatia", "Хорватія", "Croatia"),
    "ME": ("montenegro", "Чорногорія", "Montenegro"),
    "MV": ("maldives", "Мальдіви", "Maldives"),
}


@dataclass
class HotelMeta:
    hotel_id: int  # ittour mapKey == farvater hotelKey
    url_path: str
    name: str
    country_iso2: str
    photo_url: str
    description: str
    stars: int | None  # 1..5 when extractable; None for villas/apartments
    photos: list[str]  # all gallery URLs (dedup'd, normalised)
    review_score: float | None  # aggregateRating.ratingValue, 0..10
    review_count: int  # aggregateRating.reviewCount


async def ensure_operator(db: AsyncSession) -> int:
    row = (
        await db.execute(text("SELECT id FROM operators WHERE code = :c"), {"c": OPERATOR_CODE})
    ).first()
    if row:
        return int(row[0])
    row = (
        await db.execute(
            text("""INSERT INTO operators (code, display_name,
                                       affiliate_url_template, is_active)
                VALUES (:c, :n, :t, TRUE)
                ON CONFLICT (code) DO UPDATE
                SET code = EXCLUDED.code
                RETURNING id"""),
            {"c": OPERATOR_CODE, "n": "Фарватер", "t": "https://farvater.travel{external_id}"},
        )
    ).first()
    if row is None:
        raise RuntimeError("failed to insert farvater operator")
    return int(row[0])


async def country_dest_id(db: AsyncSession, iso2: str) -> int | None:
    iso = iso2.upper()
    row = (
        await db.execute(
            text("""SELECT id FROM destinations
                WHERE country_iso2 = :iso AND parent_id IS NULL
                LIMIT 1"""),
            {"iso": iso},
        )
    ).first()
    if row:
        return int(row[0])
    root = COUNTRY_ROOTS.get(iso)
    if root is None:
        return None
    slug, name_uk, name_en = root
    row = (
        await db.execute(
            text("""INSERT INTO destinations (
                    country_iso2, region_slug, name_uk, name_en, parent_id
                )
                VALUES (:iso, :slug, :name_uk, :name_en, NULL)
                ON CONFLICT (country_iso2, region_slug) DO UPDATE
                SET name_uk = EXCLUDED.name_uk,
                    name_en = EXCLUDED.name_en,
                    parent_id = NULL
                RETURNING id"""),
            {"iso": iso, "slug": slug, "name_uk": name_uk, "name_en": name_en},
        )
    ).first()
    return int(row[0]) if row else None


async def upsert_hotel(
    db: AsyncSession, hotel: HotelMeta, dest_id: int | None, operator_id: int
) -> int:
    """Upsert a hotel and stamp catalog freshness.

    `last_priced_at` / `has_active_prices` are bumped separately only when
    price rows land.
    """
    slug = make_slug(hotel.country_iso2, hotel.url_path)
    mapped = (
        await db.execute(
            text("""SELECT hotel_id
                FROM hotel_operator_mapping
                WHERE operator_id = :op
                  AND external_id = :ext
                LIMIT 1"""),
            {"op": operator_id, "ext": str(hotel.hotel_id)},
        )
    ).first()
    existing = (
        mapped
        or (
            await db.execute(
                text("SELECT id FROM hotels WHERE canonical_slug = :s"),
                {"s": slug},
            )
        ).first()
    )
    new_photos_list = [{"url": u, "alt": hotel.name} for u in hotel.photos]
    # Fall back to single og:image when gallery extraction yielded nothing.
    if not new_photos_list and hotel.photo_url:
        new_photos_list = [{"url": hotel.photo_url, "alt": hotel.name}]
    new_photos = json.dumps(new_photos_list) if new_photos_list else None

    if existing:
        new_desc = hotel.description if hotel.description else None
        new_name = hotel.name if (hotel.name and len(hotel.name) > 3) else None
        await db.execute(
            text("""WITH new_p AS (SELECT CAST(:p AS jsonb) AS v)
                    UPDATE hotels
                    SET name_uk        = COALESCE(:n, name_uk),
                        name_en        = COALESCE(:n, name_en),
                        photos_jsonb   = CASE
                            WHEN (SELECT v FROM new_p) IS NULL THEN photos_jsonb
                            WHEN photos_jsonb IS NULL THEN (SELECT v FROM new_p)
                            WHEN jsonb_array_length((SELECT v FROM new_p))
                                 >= jsonb_array_length(photos_jsonb)
                              THEN (SELECT v FROM new_p)
                            ELSE photos_jsonb
                        END,
                        destination_id = COALESCE(destination_id, :dest),
                        description_uk = COALESCE(:d, description_uk),
                        stars          = COALESCE(:stars, stars),
                        review_score   = COALESCE(:rs, review_score),
                        review_count   = GREATEST(review_count, COALESCE(:rc, 0)),
                        last_seen_at   = NOW(),
                        last_updated   = NOW()
                    WHERE id = :id"""),
            {
                "id": existing[0],
                "n": new_name,
                "dest": dest_id,
                "p": new_photos,
                "d": new_desc,
                "stars": hotel.stars,
                "rs": hotel.review_score,
                "rc": hotel.review_count,
            },
        )
        return int(existing[0])

    row = (
        await db.execute(
            text("""INSERT INTO hotels (
                  canonical_slug, name_uk, name_en, stars, destination_id,
                  description_uk, photos_jsonb, amenities, review_score,
                  review_count, is_active, last_seen_at, last_updated)
                VALUES (:slug, :n, :n, :stars, :dest, :d, CAST(:p AS jsonb),
                        '{}', :rs, :rc, TRUE, NOW(), NOW())
                RETURNING id"""),
            {
                "slug": slug,
                "n": hotel.name,
                "stars": hotel.stars,
                "dest": dest_id,
                "d": hotel.description,
                "p": new_photos or "[]",
                "rs": hotel.review_score,
                "rc": hotel.review_count,
            },
        )
    ).first()
    if row is None:
        raise RuntimeError("failed to insert hotel")
    return int(row[0])


async def upsert_mapping(
    db: AsyncSession, hotel_db_id: int, operator_id: int, hotel: HotelMeta
) -> None:
    await db.execute(
        text("""INSERT INTO hotel_operator_mapping
                      (operator_id, external_id, hotel_id, external_name)
                VALUES (:op, :ext, :h, :n)
                ON CONFLICT (operator_id, external_id) DO UPDATE
                SET hotel_id = EXCLUDED.hotel_id,
                    external_name = EXCLUDED.external_name"""),
        {"op": operator_id, "ext": str(hotel.hotel_id), "h": hotel_db_id, "n": hotel.name},
    )
