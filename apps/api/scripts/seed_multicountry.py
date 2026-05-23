"""Multi-country seed for FastTravel — extends seed_demo (Turkey) with 9 more countries.

Goal: expand the demo dataset from 1 country / 50 hotels to 10 countries /
~252 hotels so the price calendar, country filters, and discovery UI have
something meaningful to render.

Run inside the api container (seed_demo MUST have run first — we rely on
existing operator rows):
    docker compose run --rm api python -m scripts.seed_multicountry
    docker compose run --rm api python -m scripts.seed_multicountry --full

Idempotency
-----------
Sentinel slug: "steigenberger-aldau-resort-hurghada-eg" (Hurghada / Egypt).
If present the script exits without touching the DB.

Notes on isolation from seed_demo
---------------------------------
We import small pure helpers from seed_demo (_nights_multiplier,
_meal_multiplier, _seasonal_multiplier, _affiliate_deep_link, OPERATORS,
FX_USD_TO_UAH) but keep our own random.Random instance and our own
_base_price_usd so:

- this script's reproducibility is independent of seed_demo's RNG state, and
- pricing can be modulated per-country via a price modifier without rewriting
  base price tables.

External_id collisions
----------------------
seed_demo already burned ~125 random ints/operator in the range 10000..99999.
Before generating new mapping rows we SELECT existing external_ids per
operator and seed our `used` set with them so we don't trip the
(operator_id, external_id) primary key.

Operators
---------
We SELECT operators by code rather than INSERT. If any of the three expected
codes are missing we error out with a clear message — running this script
before seed_demo is a user error, not a state we can repair.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import unicodedata
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.infra.db import async_engine, dispose_engine

from scripts.seed_demo import (
    AMENITIES_POOL,
    DESC_INTROS,
    DESC_MIDS,
    DESC_TAILS,
    FX_USD_TO_UAH,
    OPERATORS,
    _affiliate_deep_link,
    _meal_multiplier,
    _nights_multiplier,
    _seasonal_multiplier,
)

# ---------------------------------------------------------------------------
# Local RNG — DIFFERENT seed than seed_demo so the deal-candidate picks and
# pricing noise are not correlated.
# ---------------------------------------------------------------------------
RNG_SEED_MC = 20260601
_rng = random.Random(RNG_SEED_MC)

SENTINEL_SLUG = "steigenberger-aldau-resort-hurghada-eg"


# ---------------------------------------------------------------------------
# Country / region / hotel reference data
# Real, public-domain hotel names. Per-country price modifier applied on
# top of the base star-band price.
# ---------------------------------------------------------------------------

# (region_slug, name_uk, name_en, hotel_count, centre_lat, centre_lon)
RegionTuple = tuple[str, str, str, int, float, float]


@dataclass(frozen=True)
class CountrySeed:
    iso2: str
    country_slug: str  # destinations.region_slug for the country-root row
    name_uk: str
    name_en: str
    price_modifier: float
    regions: list[RegionTuple]
    hotel_names: list[str]


COUNTRIES: list[CountrySeed] = [
    # ----------------------------------------------------------------- Egypt
    CountrySeed(
        iso2="EG",
        country_slug="egypt",
        name_uk="Єгипет",
        name_en="Egypt",
        price_modifier=0.85,
        regions=[
            ("sharm-el-sheikh", "Шарм-ель-Шейх", "Sharm El Sheikh", 10, 27.9158, 34.3300),
            ("hurghada", "Хургада", "Hurghada", 10, 27.2579, 33.8116),
            ("marsa-alam", "Марса-Алам", "Marsa Alam", 5, 25.0676, 34.8932),
        ],
        hotel_names=[
            # Sharm El Sheikh (10)
            "Rixos Premium Seagate",
            "Four Seasons Resort Sharm El Sheikh",
            "Savoy Sharm El Sheikh",
            "Royal Savoy Sharm El Sheikh",
            "Baron Resort Sharm El Sheikh",
            "Sunrise Arabian Beach Resort",
            "Jaz Mirabel Beach Resort",
            "Coral Sea Sensatori Resort",
            "Hyatt Regency Sharm El Sheikh",
            "Sultan Gardens Resort",
            # Hurghada (10)
            "Steigenberger Aldau Resort",
            "Steigenberger Al Dau Beach Hotel",
            "Sunrise Holidays Resort",
            "Jaz Aquamarine Resort",
            "Albatros Palace Resort",
            "Pickalbatros Dana Beach Resort",
            "Sunny Days El Palacio Resort",
            "Hilton Hurghada Plaza",
            "Sahl Hasheesh Pyramisa Beach Resort",
            "Tropitel Sahl Hasheesh",
            # Marsa Alam (5)
            "Steigenberger Coraya Beach Resort",
            "Jaz Maraya Beach Resort",
            "Hilton Marsa Alam Nubian Resort",
            "Three Corners Equinox Beach Resort",
            "Aurora Bay Resort Marsa Alam",
        ],
    ),
    # ------------------------------------------------------------------- UAE
    CountrySeed(
        iso2="AE",
        country_slug="uae",
        name_uk="ОАЕ",
        name_en="United Arab Emirates",
        price_modifier=1.40,
        regions=[
            ("dubai", "Дубай", "Dubai", 10, 25.2048, 55.2708),
            ("abu-dhabi", "Абу-Дабі", "Abu Dhabi", 7, 24.4539, 54.3773),
            ("ras-al-khaimah", "Рас-Аль-Хайма", "Ras Al Khaimah", 5, 25.7895, 55.9432),
        ],
        hotel_names=[
            # Dubai (10)
            "Atlantis The Palm",
            "Burj Al Arab Jumeirah",
            "Jumeirah Beach Hotel",
            "Rixos Premium Dubai JBR",
            "Hilton Dubai Jumeirah",
            "Madinat Jumeirah Resort",
            "Le Royal Meridien Beach Resort",
            "Sofitel Dubai The Palm",
            "Movenpick Hotel Jumeirah Beach",
            "JA The Resort Dubai",
            # Abu Dhabi (7)
            "Emirates Palace Mandarin Oriental",
            "Saadiyat Rotana Resort",
            "Park Hyatt Abu Dhabi",
            "St Regis Saadiyat Island Resort",
            "Rixos Saadiyat Island",
            "Anantara Eastern Mangroves",
            "Bab Al Qasr Hotel",
            # Ras Al Khaimah (5)
            "Waldorf Astoria Ras Al Khaimah",
            "Hilton Ras Al Khaimah Beach Resort",
            "Rixos Bab Al Bahr",
            "Movenpick Resort Al Marjan Island",
            "Hampton by Hilton Marjan Island",
        ],
    ),
    # ---------------------------------------------------------------- Greece
    CountrySeed(
        iso2="GR",
        country_slug="greece",
        name_uk="Греція",
        name_en="Greece",
        price_modifier=1.10,
        regions=[
            ("crete", "Крит", "Crete", 8, 35.2401, 24.8093),
            ("rhodes", "Родос", "Rhodes", 7, 36.4341, 28.2176),
            ("kos", "Кос", "Kos", 5, 36.8938, 27.2877),
            ("corfu", "Корфу", "Corfu", 5, 39.6243, 19.9217),
        ],
        hotel_names=[
            # Crete (8)
            "Iberostar Creta Panorama",
            "Grecotel Creta Palace",
            "Atlantica Caldera Palace",
            "Mitsis Rinela Beach Resort",
            "Aldemar Knossos Royal",
            "Stella Palace Resort & Spa",
            "Blue Palace Elounda",
            "Daios Cove Luxury Resort",
            # Rhodes (7)
            "Mitsis Grand Hotel Rhodes",
            "Atrium Palace Thalasso Spa Resort",
            "Esperides Beach Family Resort",
            "Lindos Imperial Resort & Spa",
            "Sentido Apollo Blue",
            "Rodos Palace Hotel",
            "Mitsis Rodos Village Beach Hotel",
            # Kos (5)
            "Mitsis Blue Domes Resort",
            "Atlantica Belvedere Resort",
            "Neptune Hotels Resort",
            "Ikos Aria",
            "Akti Imperial Deluxe Resort",
            # Corfu (5)
            "Ikos Dassia",
            "Marbella Corfu",
            "Domes Miramare Corfu",
            "Atlantica Grand Mediterraneo",
            "Mareblue Beach Resort",
        ],
    ),
    # ----------------------------------------------------------------- Spain
    CountrySeed(
        iso2="ES",
        country_slug="spain",
        name_uk="Іспанія",
        name_en="Spain",
        price_modifier=1.15,
        regions=[
            ("costa-brava", "Коста-Брава", "Costa Brava", 7, 41.9794, 3.0500),
            ("tenerife", "Тенерифе", "Tenerife", 8, 28.2916, -16.6291),
            ("mallorca", "Майорка", "Mallorca", 7, 39.6953, 3.0176),
        ],
        hotel_names=[
            # Costa Brava (7)
            "Hotel Rigat Park & Spa Beach",
            "Gran Hotel Reymar",
            "Hotel Santa Marta",
            "Salles Hotel & Spa Cala del Pi",
            "Aqua Hotel Aquamarina & Spa",
            "Hotel Alva Park Costa Brava",
            "Hotel Allioli",
            # Tenerife (8)
            "Royal Hideaway Corales Beach",
            "Iberostar Selection Anthelia",
            "Bahia Principe Sunlight San Felipe",
            "Hotel Riu Palace Tenerife",
            "Gran Melia Palacio de Isora",
            "Hard Rock Hotel Tenerife",
            "Sheraton La Caleta Resort",
            "Hotel Botanico Tenerife",
            # Mallorca (7)
            "Iberostar Selection Playa de Palma",
            "Hipotels Playa de Palma Palace",
            "Riu Bravo",
            "Melia Palma Bay",
            "Be Live Collection Palace de Muro",
            "Zafiro Palace Alcudia",
            "Iberostar Albufera Park",
        ],
    ),
    # -------------------------------------------------------------- Bulgaria
    CountrySeed(
        iso2="BG",
        country_slug="bulgaria",
        name_uk="Болгарія",
        name_en="Bulgaria",
        price_modifier=0.65,
        regions=[
            ("sunny-beach", "Сонячний берег", "Sunny Beach", 10, 42.6886, 27.7140),
            ("golden-sands", "Золоті піски", "Golden Sands", 8, 43.2867, 28.0419),
        ],
        hotel_names=[
            # Sunny Beach (10)
            "Melia Sunny Beach",
            "Riu Helios Bay",
            "Hotel Iberostar Sunny Beach Resort",
            "DIT Evrika Beach Club Hotel",
            "Barcelo Royal Beach",
            "Sol Nessebar Bay Mare",
            "Grifid Hotel Encanto Beach",
            "Bellevue Beach Hotel",
            "Hotel Glarus Beach",
            "Hotel Trakia Plaza",
            # Golden Sands (8)
            "Melia Grand Hermitage",
            "Riu Palace Sunny Beach Golden Sands",
            "International Hotel Casino & Tower Suites",
            "Grifid Hotel Bolero",
            "Grifid Arabella Hotel",
            "Astera Hotel & Spa",
            "Admiral Hotel Golden Sands",
            "Atlas Hotel Golden Sands",
        ],
    ),
    # ------------------------------------------------------------ Montenegro
    CountrySeed(
        iso2="ME",
        country_slug="montenegro",
        name_uk="Чорногорія",
        name_en="Montenegro",
        price_modifier=0.90,
        regions=[
            ("budva", "Будва", "Budva", 9, 42.2911, 18.8403),
            ("kotor", "Котор", "Kotor", 6, 42.4247, 18.7712),
        ],
        hotel_names=[
            # Budva (9)
            "Splendid Conference & Spa Resort",
            "Hotel Avala Resort & Villas",
            "Iberostar Slavija",
            "Hotel Mediteran Budva",
            "Aleksandar Hotel Budva",
            "Hotel Palas Petrovac",
            "Maestral Resort & Casino",
            "Hotel Castellastva Petrovac",
            "Falkensteiner Hotel Montenegro",
            # Kotor (6)
            "Hyatt Regency Kotor Bay Resort",
            "Boutique Hotel Hippocampus",
            "Hotel Vardar Kotor",
            "Hotel Marija Kotor",
            "Forza Mare Hotel",
            "Hotel Cattaro",
        ],
    ),
    # --------------------------------------------------------------- Croatia
    CountrySeed(
        iso2="HR",
        country_slug="croatia",
        name_uk="Хорватія",
        name_en="Croatia",
        price_modifier=1.20,
        regions=[
            ("dubrovnik", "Дубровник", "Dubrovnik", 7, 42.6507, 18.0944),
            ("split", "Спліт", "Split", 6, 43.5081, 16.4402),
            ("istria", "Істрія", "Istria", 5, 45.2553, 13.9408),
        ],
        hotel_names=[
            # Dubrovnik (7)
            "Hotel Excelsior Dubrovnik",
            "Hotel Bellevue Dubrovnik",
            "Valamar Lacroma Dubrovnik",
            "Sun Gardens Dubrovnik",
            "Rixos Premium Dubrovnik",
            "Hotel Dubrovnik Palace",
            "Hotel Kompas Dubrovnik",
            # Split (6)
            "Le Meridien Lav Split",
            "Radisson Blu Resort Split",
            "Hotel Park Split",
            "Hotel Atrium Split",
            "Hotel Cornaro Split",
            "Hotel Ambasador Split",
            # Istria (5)
            "Hotel Lone Rovinj",
            "Grand Park Hotel Rovinj",
            "Maistra Eden Rovinj",
            "Valamar Riviera Hotel Porec",
            "Kempinski Hotel Adriatic Istria",
        ],
    ),
    # ----------------------------------------------------------------- Cyprus
    CountrySeed(
        iso2="CY",
        country_slug="cyprus",
        name_uk="Кіпр",
        name_en="Cyprus",
        price_modifier=1.05,
        regions=[
            ("ayia-napa", "Айя-Напа", "Ayia Napa", 7, 34.9823, 33.9991),
            ("paphos", "Пафос", "Paphos", 6, 34.7720, 32.4297),
            ("limassol", "Лімассол", "Limassol", 7, 34.7071, 33.0226),
        ],
        hotel_names=[
            # Ayia Napa (7)
            "Atlantica Aeneas Resort",
            "Nissi Beach Resort",
            "Grecian Bay Hotel",
            "Asterias Beach Hotel",
            "Olympic Lagoon Resort Ayia Napa",
            "Adams Beach Hotel",
            "Capo Bay Hotel",
            # Paphos (6)
            "Annabelle Hotel Paphos",
            "Constantinou Bros Athena Beach Hotel",
            "Elysium Hotel Paphos",
            "Coral Beach Hotel & Resort",
            "Aquamare Beach Hotel & Spa",
            "Olympic Lagoon Resort Paphos",
            # Limassol (7)
            "Amathus Beach Hotel Limassol",
            "Four Seasons Hotel Limassol",
            "Mediterranean Beach Hotel",
            "St Raphael Resort Limassol",
            "Atlantica Miramare Beach",
            "Parklane Luxury Collection Resort",
            "Crowne Plaza Limassol",
        ],
    ),
    # -------------------------------------------------------------- Thailand
    CountrySeed(
        iso2="TH",
        country_slug="thailand",
        name_uk="Таїланд",
        name_en="Thailand",
        price_modifier=1.30,
        regions=[
            ("phuket", "Пхукет", "Phuket", 10, 7.8804, 98.3923),
            ("pattaya", "Паттайя", "Pattaya", 8, 12.9236, 100.8825),
            ("krabi", "Крабі", "Krabi", 7, 8.0863, 98.9063),
        ],
        hotel_names=[
            # Phuket (10)
            "Centara Grand Beach Resort Phuket",
            "Le Meridien Phuket Beach Resort",
            "Hilton Phuket Arcadia Resort",
            "JW Marriott Phuket Resort & Spa",
            "Phuket Marriott Resort Merlin Beach",
            "Holiday Inn Resort Phuket",
            "Katathani Phuket Beach Resort",
            "Andaman White Beach Resort",
            "Movenpick Resort Bangtao Beach",
            "Banyan Tree Phuket",
            # Pattaya (8)
            "Centara Grand Mirage Beach Resort Pattaya",
            "Hilton Pattaya",
            "Holiday Inn Pattaya",
            "Amari Pattaya",
            "Pullman Pattaya Hotel G",
            "Royal Cliff Beach Hotel",
            "Hard Rock Hotel Pattaya",
            "Long Beach Garden Hotel & Spa",
            # Krabi (7)
            "Centara Grand Beach Resort Krabi",
            "Sofitel Krabi Phokeethra Golf & Spa Resort",
            "Dusit Thani Krabi Beach Resort",
            "Beyond Krabi Resort",
            "Holiday Inn Resort Krabi Ao Nang",
            "Aonang Princeville Villa Resort",
            "Krabi Resort",
        ],
    ),
    # -------------------------------------------------------------- Maldives
    CountrySeed(
        iso2="MV",
        country_slug="maldives",
        name_uk="Мальдіви",
        name_en="Maldives",
        price_modifier=2.50,
        regions=[
            ("male-atoll", "Мале-атолл", "Male Atoll", 6, 4.1755, 73.5093),
            ("ari-atoll", "Арі-атолл", "Ari Atoll", 6, 3.8500, 72.8333),
        ],
        hotel_names=[
            # Male Atoll (6)
            "Adaaran Prestige Vadoo",
            "Bandos Maldives",
            "Kurumba Maldives",
            "Sheraton Maldives Full Moon Resort",
            "Velassaru Maldives",
            "Anantara Veli Maldives Resort",
            # Ari Atoll (6)
            "Constance Halaveli Maldives",
            "Lily Beach Resort & Spa",
            "Vilamendhoo Island Resort & Spa",
            "Sun Siyam Vilu Reef",
            "W Maldives",
            "Conrad Maldives Rangali Island",
        ],
    ),
]


# Sanity assertions — fail loudly at import time if a country definition
# has mismatched counts.
for _c in COUNTRIES:
    _expected = sum(r[3] for r in _c.regions)
    assert (
        len(_c.hotel_names) == _expected
    ), f"{_c.iso2}: {len(_c.hotel_names)} names != {_expected} region capacity"


# ---------------------------------------------------------------------------
# Local helpers (kept independent of seed_demo._rng)
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """ASCII kebab-case slug."""
    decomposed = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    decomposed = decomposed.lower()
    decomposed = re.sub(r"[^a-z0-9]+", "-", decomposed).strip("-")
    return decomposed


def _base_price_usd(stars: int) -> int:
    """Base 7-night HB price band per star rating, in USD.

    Matches seed_demo._base_price_usd but uses our local _rng.
    """
    if stars == 5:
        return _rng.randint(2500, 3500)
    if stars == 4:
        return _rng.randint(1500, 2500)
    return _rng.randint(800, 1500)


@dataclass(frozen=True)
class HotelRow:
    canonical_slug: str
    name_uk: str
    name_en: str
    stars: int
    destination_id: int
    region_slug: str
    country_iso2: str
    country_modifier: float
    coords_point: str  # "(lat,lon)"
    description_uk: str
    photos_jsonb: list[dict[str, str]]
    amenities: list[str]
    review_score: float
    review_count: int


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _table_already_seeded(conn: AsyncConnection) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM hotels WHERE canonical_slug = :slug LIMIT 1"),
        {"slug": SENTINEL_SLUG},
    )
    return result.first() is not None


async def _load_operator_ids(conn: AsyncConnection) -> dict[str, int]:
    """SELECT operator ids by code. Error out if any expected code is missing."""
    expected_codes = {op["code"] for op in OPERATORS}
    result = await conn.execute(
        text("SELECT id, code FROM operators WHERE code = ANY(:codes)"),
        {"codes": list(expected_codes)},
    )
    found = {row.code: row.id for row in result.all()}
    missing = expected_codes - set(found.keys())
    if missing:
        raise RuntimeError(
            f"Operators not found in DB: {sorted(missing)}. "
            "Run `python -m scripts.seed_demo` first — this script depends "
            "on the operator rows it creates."
        )
    return found


async def _load_existing_external_ids(
    conn: AsyncConnection, operator_id_by_code: dict[str, int]
) -> set[tuple[int, str]]:
    """Load all (operator_id, external_id) pairs already in
    hotel_operator_mapping so we can avoid PK collisions when generating
    new ids on top of the TR seed.
    """
    result = await conn.execute(
        text(
            "SELECT operator_id, external_id FROM hotel_operator_mapping "
            "WHERE operator_id = ANY(:ids)"
        ),
        {"ids": list(operator_id_by_code.values())},
    )
    return {(row.operator_id, row.external_id) for row in result.all()}


async def _ensure_partitions_cover_history(
    conn: AsyncConnection, history_days: int
) -> None:
    """Same check as seed_demo — confirm the `default` partition exists.

    pg_partman's `default` catch-all partition handles any historical
    rows whose week is not explicitly provisioned.
    """
    result = await conn.execute(
        text(
            """
            SELECT bool_or(inhrelid::regclass::text = 'price_observations_default')
                AS has_default
            FROM pg_inherits
            WHERE inhparent = 'public.price_observations'::regclass
            """
        )
    )
    row = result.first()
    if row is None or not row.has_default:
        raise RuntimeError(
            "price_observations has no `default` partition — historical seed "
            "rows would be rejected. Re-run alembic migrations."
        )
    _ = history_days


async def _insert_destinations(
    conn: AsyncConnection,
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """INSERT country rows + region rows for the 9 new countries.

    Returns:
        country_id_by_iso2 — {"EG": 12, ...}
        region_id_by_country_region — {("EG", "hurghada"): 13, ...}
    """
    country_id_by_iso2: dict[str, int] = {}
    region_id_by_country_region: dict[tuple[str, str], int] = {}

    for c in COUNTRIES:
        result = await conn.execute(
            text(
                """
                INSERT INTO destinations
                    (country_iso2, region_slug, name_uk, name_en, parent_id)
                VALUES (:country_iso2, :region_slug, :name_uk, :name_en, NULL)
                RETURNING id
                """
            ),
            {
                "country_iso2": c.iso2,
                "region_slug": c.country_slug,
                "name_uk": c.name_uk,
                "name_en": c.name_en,
            },
        )
        country_id = result.scalar_one()
        country_id_by_iso2[c.iso2] = country_id

        for region_slug, name_uk, name_en, _count, _lat, _lon in c.regions:
            r = await conn.execute(
                text(
                    """
                    INSERT INTO destinations
                        (country_iso2, region_slug, name_uk, name_en, parent_id)
                    VALUES (:country_iso2, :region_slug, :name_uk, :name_en, :parent_id)
                    RETURNING id
                    """
                ),
                {
                    "country_iso2": c.iso2,
                    "region_slug": region_slug,
                    "name_uk": name_uk,
                    "name_en": name_en,
                    "parent_id": country_id,
                },
            )
            region_id_by_country_region[(c.iso2, region_slug)] = r.scalar_one()
    return country_id_by_iso2, region_id_by_country_region


def _build_hotel_rows(
    region_id_by_country_region: dict[tuple[str, str], int],
) -> list[HotelRow]:
    rows: list[HotelRow] = []
    for c in COUNTRIES:
        cursor = 0
        for region_slug, _name_uk, _name_en, count, lat, lon in c.regions:
            dest_id = region_id_by_country_region[(c.iso2, region_slug)]
            for i in range(count):
                name = c.hotel_names[cursor + i]
                stars = _rng.choices([3, 4, 5], weights=[1, 4, 5])[0]
                base_slug = f"{_slugify(name)}-{region_slug}-{c.iso2.lower()}"
                jitter_lat = lat + _rng.uniform(-0.05, 0.05)
                jitter_lon = lon + _rng.uniform(-0.05, 0.05)
                n_amenities = _rng.randint(3, 7)
                amenities = _rng.sample(AMENITIES_POOL, n_amenities)
                n_photos = _rng.randint(3, 5)
                photos = [
                    {
                        "url": f"https://picsum.photos/seed/{base_slug}-{n}/1200/800",
                        "alt": f"{name} — фото {n + 1}",
                    }
                    for n in range(n_photos)
                ]
                review_score = round(_rng.uniform(7.5, 9.5), 1)
                review_count = _rng.randint(50, 1500)
                desc = " ".join(
                    [
                        f"{_rng.choice(DESC_INTROS)} {_rng.choice(DESC_MIDS)}.",
                        _rng.choice(DESC_TAILS),
                    ]
                )
                rows.append(
                    HotelRow(
                        canonical_slug=base_slug,
                        name_uk=name,
                        name_en=name,
                        stars=stars,
                        destination_id=dest_id,
                        region_slug=region_slug,
                        country_iso2=c.iso2,
                        country_modifier=c.price_modifier,
                        coords_point=f"({jitter_lat:.6f},{jitter_lon:.6f})",
                        description_uk=desc,
                        photos_jsonb=photos,
                        amenities=amenities,
                        review_score=review_score,
                        review_count=review_count,
                    )
                )
            cursor += count
    return rows


async def _insert_hotels(
    conn: AsyncConnection, hotels: list[HotelRow]
) -> dict[str, int]:
    """INSERT hotels, return {canonical_slug: hotel_id}.

    Same `point` literal trick as seed_demo: inlined `point '(lat,lon)'`
    bypasses asyncpg's resistance to ::point casts on bind params.
    Coords come from hard-coded centres + jitter, no user input.
    """
    out: dict[str, int] = {}
    for h in hotels:
        sql = text(
            f"""
            INSERT INTO hotels (
                canonical_slug, name_uk, name_en, stars, destination_id,
                coords, description_uk, photos_jsonb, amenities,
                review_score, review_count, is_active, last_updated
            )
            VALUES (
                :canonical_slug, :name_uk, :name_en, :stars, :destination_id,
                point '{h.coords_point}', :description_uk, CAST(:photos AS jsonb),
                :amenities, :review_score, :review_count, TRUE, NOW()
            )
            RETURNING id, canonical_slug
            """
        )
        result = await conn.execute(
            sql,
            {
                "canonical_slug": h.canonical_slug,
                "name_uk": h.name_uk,
                "name_en": h.name_en,
                "stars": h.stars,
                "destination_id": h.destination_id,
                "description_uk": h.description_uk,
                "photos": json.dumps(h.photos_jsonb, ensure_ascii=False),
                "amenities": h.amenities,
                "review_score": h.review_score,
                "review_count": h.review_count,
            },
        )
        row = result.first()
        assert row is not None
        out[row.canonical_slug] = row.id
    return out


async def _insert_mappings(
    conn: AsyncConnection,
    hotels: list[HotelRow],
    hotel_id_by_slug: dict[str, int],
    operator_id_by_code: dict[str, int],
    existing_external_ids: set[tuple[int, str]],
) -> list[tuple[int, int, str]]:
    """Map each hotel to 2-3 operators. Collisions with existing TR seed
    ids are caught via `existing_external_ids`."""
    operator_codes = list(operator_id_by_code.keys())
    rows: list[dict[str, Any]] = []
    triples: list[tuple[int, int, str]] = []
    used = set(existing_external_ids)  # copy; we add to it as we go

    for h in hotels:
        hotel_id = hotel_id_by_slug[h.canonical_slug]
        n_ops = _rng.choice([2, 2, 3])
        chosen_ops = _rng.sample(operator_codes, n_ops)
        for code in chosen_ops:
            op_id = operator_id_by_code[code]
            while True:
                ext = str(_rng.randint(10000, 99999))
                if (op_id, ext) not in used:
                    used.add((op_id, ext))
                    break
            rows.append(
                {
                    "operator_id": op_id,
                    "external_id": ext,
                    "hotel_id": hotel_id,
                    "external_name": h.name_en,
                }
            )
            triples.append((hotel_id, op_id, ext))

    await conn.execute(
        text(
            """
            INSERT INTO hotel_operator_mapping
                (operator_id, external_id, hotel_id, external_name)
            VALUES (:operator_id, :external_id, :hotel_id, :external_name)
            """
        ),
        rows,
    )
    return triples


async def _insert_price_observations(
    conn: AsyncConnection,
    hotels: list[HotelRow],
    hotel_id_by_slug: dict[str, int],
    mapping_triples: list[tuple[int, int, str]],
    operator_id_by_code: dict[str, int],
    full: bool,
) -> int:
    """Bulk INSERT into price_observations, chunked at 5000 rows.

    Pricing formula:
        base_usd = _base_price_usd(stars) * country_modifier * op_offset
        price_usd = base_usd * nights_mult * meal_mult * season * noise
        if deal_day: price_usd *= 1 - uniform(0.25, 0.40)
    """
    operator_template_by_id: dict[int, str | None] = {}
    for op_row in OPERATORS:
        operator_template_by_id[operator_id_by_code[op_row["code"]]] = op_row[
            "affiliate_url_template"
        ]

    hotel_by_id: dict[int, HotelRow] = {}
    for h in hotels:
        hotel_by_id[hotel_id_by_slug[h.canonical_slug]] = h

    base_price_by_hotel_op: dict[tuple[int, int], int] = {}
    for hotel_id, op_id, _ext in mapping_triples:
        h = hotel_by_id[hotel_id]
        base = _base_price_usd(h.stars) * h.country_modifier
        op_offset_pct = _rng.uniform(-0.08, 0.08)
        base_price_by_hotel_op[(hotel_id, op_id)] = int(base * (1 + op_offset_pct))

    # 5-7 deal-candidate hotels across the entire 9-country pool.
    n_deals = _rng.randint(5, 7)
    deal_hotel_ids = set(_rng.sample(list(hotel_by_id.keys()), n_deals))
    deal_days_by_hotel: dict[int, set[date]] = {}
    today = date.today()
    for hid in deal_hotel_ids:
        n_deal_days = _rng.randint(1, 3)
        chosen_days = set(
            today + timedelta(days=_rng.randint(7, 50)) for _ in range(n_deal_days)
        )
        deal_days_by_hotel[hid] = chosen_days

    history_days = 30 if full else 7
    snapshots_per_day = 2  # 06:00 and 18:00 UTC
    check_in_horizon = 60
    nights_options = (7, 10, 14)
    meal_options = ("AI", "HB")

    insert_sql = text(
        """
        INSERT INTO price_observations (
            observed_at, hotel_id, operator_id, check_in, nights, meal_plan,
            adults, departure_city, price_uah, price_original, currency,
            fx_rate_to_uah, deep_link
        )
        VALUES (
            :observed_at, :hotel_id, :operator_id, :check_in, :nights, :meal_plan,
            2, 'KBP', :price_uah, :price_original, 'USD',
            :fx_rate_to_uah, :deep_link
        )
        """
    )

    chunk_size = 5_000
    buffer: list[dict[str, Any]] = []
    total = 0

    snapshot_offsets = list(range(history_days + 1))
    snapshot_hours = (6, 18)
    deep_link_cache: dict[tuple[int, str], str | None] = {}

    for day_offset in snapshot_offsets:
        observed_day = today - timedelta(days=day_offset)
        for hour in snapshot_hours[:snapshots_per_day]:
            observed_at = datetime.combine(observed_day, time(hour, 0), tzinfo=UTC)
            for hotel_id, op_id, ext_id in mapping_triples:
                h = hotel_by_id[hotel_id]
                base_usd = base_price_by_hotel_op[(hotel_id, op_id)]
                template = operator_template_by_id[op_id]
                cache_key = (op_id, ext_id)
                if cache_key not in deep_link_cache:
                    deep_link_cache[cache_key] = _affiliate_deep_link(template, ext_id)
                deep_link = deep_link_cache[cache_key]
                deal_days = deal_days_by_hotel.get(hotel_id, set())
                for check_offset in range(1, check_in_horizon + 1):
                    check_in = today + timedelta(days=check_offset)
                    season = _seasonal_multiplier(check_in)
                    is_deal_day = check_in in deal_days
                    for nights in nights_options:
                        nights_mult = _nights_multiplier(nights)
                        for meal in meal_options:
                            meal_mult = _meal_multiplier(meal)
                            noise = _rng.uniform(0.90, 1.10)
                            price_usd = (
                                base_usd * nights_mult * meal_mult * season * noise
                            )
                            if is_deal_day:
                                price_usd *= 1.0 - _rng.uniform(0.25, 0.40)
                            price_usd_int = int(round(price_usd))
                            price_uah = int(round(price_usd * FX_USD_TO_UAH))
                            buffer.append(
                                {
                                    "observed_at": observed_at,
                                    "hotel_id": hotel_id,
                                    "operator_id": op_id,
                                    "check_in": check_in,
                                    "nights": nights,
                                    "meal_plan": meal,
                                    "price_uah": price_uah,
                                    "price_original": price_usd_int,
                                    "fx_rate_to_uah": FX_USD_TO_UAH,
                                    "deep_link": deep_link,
                                }
                            )
                            if len(buffer) >= chunk_size:
                                await conn.execute(insert_sql, buffer)
                                total += len(buffer)
                                buffer.clear()
        if day_offset % 5 == 0:
            print(
                f"  ... day_offset={day_offset}/{history_days}  "
                f"rows so far: {total + len(buffer):,}",
                flush=True,
            )

    if buffer:
        await conn.execute(insert_sql, buffer)
        total += len(buffer)
        buffer.clear()

    return total


async def _refresh_materialized_views(conn: AsyncConnection) -> None:
    """Refresh the three MVs that materialize price aggregates.

    After the TR seed they were populated WITH DATA, so we can use the
    CONCURRENTLY variant — but it requires a unique index on each MV.
    We can't assume that index exists, so do a plain (locking) refresh
    here. The MVs are small enough that the brief lock is acceptable.
    """
    for view in ("current_prices", "hotel_calendar_prices", "price_baselines"):
        print(f"  REFRESH MATERIALIZED VIEW {view} ...", flush=True)
        await conn.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))


async def seed(full: bool = False) -> None:
    """Idempotent multi-country seed entrypoint."""
    total_hotels = sum(len(c.hotel_names) for c in COUNTRIES)
    print(
        f"FastTravel multi-country seed — "
        f"mode={'FULL (30d history)' if full else 'DEFAULT (7d history)'} "
        f"| {len(COUNTRIES)} countries / {total_hotels} hotels",
        flush=True,
    )

    async with async_engine.begin() as conn:
        if await _table_already_seeded(conn):
            print(
                f"Sentinel hotel '{SENTINEL_SLUG}' already present — skipping seed.",
                flush=True,
            )
            return

        print("[1/7] Verifying price_observations partition coverage ...", flush=True)
        history_days = 30 if full else 7
        await _ensure_partitions_cover_history(conn, history_days=history_days)

        print("[2/7] Loading operator ids (SELECT, no insert) ...", flush=True)
        operator_id_by_code = await _load_operator_ids(conn)
        print(f"  -> {operator_id_by_code}", flush=True)

        print("[3/7] Loading existing external_ids for collision avoidance ...", flush=True)
        existing_ext_ids = await _load_existing_external_ids(conn, operator_id_by_code)
        print(f"  -> {len(existing_ext_ids)} existing mapping rows", flush=True)

        print(
            f"[4/7] Inserting destinations "
            f"({len(COUNTRIES)} countries + "
            f"{sum(len(c.regions) for c in COUNTRIES)} regions) ...",
            flush=True,
        )
        _country_ids, region_ids = await _insert_destinations(conn)

        print(f"[5/7] Building and inserting {total_hotels} hotels ...", flush=True)
        hotel_rows = _build_hotel_rows(region_ids)
        # Sanity-check the sentinel slug we promised to produce.
        slugs = {h.canonical_slug for h in hotel_rows}
        assert SENTINEL_SLUG in slugs, (
            f"Sentinel slug '{SENTINEL_SLUG}' not in generated slugs — "
            "the Hurghada hotel list or slug rule was edited inconsistently."
        )
        hotel_id_by_slug = await _insert_hotels(conn, hotel_rows)

        print("[6/7] Inserting hotel_operator_mapping rows ...", flush=True)
        mapping_triples = await _insert_mappings(
            conn,
            hotel_rows,
            hotel_id_by_slug,
            operator_id_by_code,
            existing_ext_ids,
        )
        print(f"  -> {len(mapping_triples)} new mapping rows", flush=True)

        print("[7/7] Inserting price_observations (heavy step) ...", flush=True)
        total_obs = await _insert_price_observations(
            conn,
            hotel_rows,
            hotel_id_by_slug,
            mapping_triples,
            operator_id_by_code,
            full=full,
        )
        print(f"  -> {total_obs:,} new price_observations rows", flush=True)

    # MV refresh runs outside the main transaction (mirrors seed_demo).
    async with async_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        print("[post] Refreshing materialized views ...", flush=True)
        await _refresh_materialized_views(conn)

    # Per-country summary
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT d.country_iso2,
                       COUNT(DISTINCT h.id)       AS hotels,
                       COUNT(p.*)                 AS observations
                FROM destinations d
                JOIN hotels h          ON h.destination_id = d.id
                LEFT JOIN price_observations p ON p.hotel_id = h.id
                GROUP BY d.country_iso2
                ORDER BY d.country_iso2
                """
            )
        )
        per_country = result.all()
        sample_mv_slug = await conn.scalar(
            text(
                """
                SELECT h.canonical_slug
                FROM hotels h
                JOIN destinations d ON d.id = h.destination_id
                WHERE d.country_iso2 = 'MV'
                ORDER BY h.id
                LIMIT 1
                """
            )
        )

    print("\nSeed complete. Hotels and observations per country:", flush=True)
    for row in per_country:
        print(
            f"  {row.country_iso2}  hotels={row.hotels:>4}  observations={row.observations:>10,}",
            flush=True,
        )
    if sample_mv_slug:
        print(f"\nSample Maldives slug: {sample_mv_slug}", flush=True)


async def _main_async(full: bool) -> None:
    try:
        await seed(full=full)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed FastTravel demo data for 9 additional countries."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Insert 30 days of price history (default: 7 days).",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_main_async(full=args.full))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
