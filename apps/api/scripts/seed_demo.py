"""Demo seed for FastTravel — realistic but synthetic data.

Goal: make `/hotels/[slug]` and `/api/*` endpoints render meaningful content
on a freshly migrated database, weeks before real ingest clients exist.

Run inside the api container:
    docker compose run --rm api python -m scripts.seed_demo
    docker compose run --rm api python -m scripts.seed_demo --full

Idempotency
-----------
We check for a sentinel slug ("rixos-premium-belek-belek-tr"). If present,
the script exits without touching the DB. To re-seed, truncate the schema
or drop/recreate the database.

Why raw SQL for price_observations
----------------------------------
The parent table is partitioned (pg_partman 5.x, weekly range). The ORM
layer would force per-row INSERT statements which makes ~315k (default)
or ~2.7M (--full) rows unusably slow. We use Core `execute(text, [rows])`
with executemany over chunks of 5_000 rows. On a laptop default mode
finishes in well under a minute.

Why we backfill partitions
--------------------------
Migration 001 only calls `partman.create_parent(..., p_premake := 4)` which
provisions four *future* weeks. The seed writes observations dated up to
30 days in the past — those need partitions too, otherwise INSERT raises
`no partition of relation "price_observations" found for row`. We call
`partman.create_partition_time` for every Monday in the historical window
before any price inserts.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta  # noqa: F401
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.infra.db import async_engine, dispose_engine

# ---------------------------------------------------------------------------
# Deterministic pseudo-randomness so re-seeds produce comparable data
# (and so the "deal candidate" hotels stay the same across runs).
# ---------------------------------------------------------------------------
RNG_SEED = 20260523
_rng = random.Random(RNG_SEED)

SENTINEL_SLUG = "rixos-premium-belek-belek-tr"
FX_USD_TO_UAH = 41.5

# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

OPERATORS: list[dict[str, Any]] = [
    {
        "code": "joinup",
        "display_name": "Join UP!",
        "affiliate_url_template": (
            "https://joinup.ua/?utm_source=fasttravel&utm_medium=referral&hotel={external_id}"
        ),
    },
    {
        "code": "coral",
        "display_name": "Coral Travel Ukraine",
        "affiliate_url_template": "https://coral.com.ua/?ref=fasttravel&hotel={external_id}",
    },
    {
        "code": "alf",
        "display_name": "ALF",
        "affiliate_url_template": "https://alf.ua/?utm=fasttravel&id={external_id}",
    },
]

COUNTRY_TR: dict[str, Any] = {
    "country_iso2": "TR",
    "region_slug": "turkey",
    "name_uk": "Туреччина",
    "name_en": "Turkey",
}

# (region_slug, name_uk, name_en, hotel_count, centre_lat, centre_lon)
REGIONS: list[tuple[str, str, str, int, float, float]] = [
    ("antalya", "Анталія", "Antalya", 15, 36.8969, 30.7133),
    ("kemer", "Кемер", "Kemer", 12, 36.5950, 30.5601),
    ("belek", "Белек", "Belek", 10, 36.8625, 31.0556),
    ("side", "Сіде", "Side", 8, 36.7673, 31.3890),
    ("alanya", "Аланія", "Alanya", 5, 36.5444, 31.9990),
]

# Real-ish Turkish all-inclusive resort names. Ordering matters: hotels are
# assigned to regions in chunks matching REGIONS above (15 / 12 / 10 / 8 / 5).
HOTEL_NAMES: list[str] = [
    # Antalya (15)
    "Delphin Imperial Lara",
    "Delphin BE Grand Resort",
    "Royal Holiday Palace",
    "Concorde De Luxe Resort",
    "Titanic Beach Lara",
    "Titanic Deluxe Lara",
    "Rixos Downtown Antalya",
    "Akra Hotel Antalya",
    "Crystal Waterworld Resort & Spa",
    "Lara Barut Collection",
    "Kervansaray Lara Convention",
    "Sherwood Exclusive Lara",
    "Limak Lara Deluxe Hotel & Resort",
    "Miracle Resort Hotel",
    "IC Hotels Green Palace",
    # Kemer (12)
    "Maxx Royal Kemer Resort",
    "Rixos Sungate",
    "Rixos Premium Tekirova",
    "Amara Premier Palace",
    "Crystal De Luxe Resort & Spa",
    "Akka Antedon",
    "Catamaran Resort Hotel",
    "Kilikya Palace Goynuk",
    "TT Hotels Pegasos Resort",
    "Sentido Perissia Kemer",
    "Mirage Park Resort",
    "Club Hotel Phaselis Rose",
    # Belek (10)
    "Rixos Premium Belek",
    "Maxx Royal Belek Golf Resort",
    "Regnum Carya Golf & Spa Resort",
    "Calista Luxury Resort",
    "Gloria Serenity Resort",
    "Gloria Golf Resort",
    "Granada Luxury Belek",
    "Cornelia Diamond Golf Resort & Spa",
    "Ela Quality Resort Belek",
    "Voyage Belek Golf & Spa",
    # Side (8)
    "Crystal Sunset Luxury Resort & Spa",
    "Crystal Palace Luxury Resort & Spa",
    "Side Crown Charm Palace",
    "Barut Hemera",
    "Manavgat Trendy Aspendos Beach",
    "Asteria Sorgun Resort",
    "Side Star Elegance",
    "Royal Dragon Hotel",
    # Alanya (5)
    "Justiniano Deluxe Resort",
    "Long Beach Resort Hotel & Spa",
    "Mukarnas Spa Resort",
    "Saphir Resort & Spa",
    "Vikingen Infinity Resort & Spa",
]
assert len(HOTEL_NAMES) == sum(r[3] for r in REGIONS) == 50

AMENITIES_POOL: list[str] = [
    "wifi",
    "pool",
    "aqua_park",
    "kids_club",
    "spa",
    "beach",
    "gym",
    "restaurant",
    "animation",
    "all_inclusive",
    "pet_friendly",
]

# Short, varied description fragments — combined to feel less templated.
DESC_INTROS = [
    "Розкішний курорт прямо на узбережжі",
    "Сучасний готель у мальовничій бухті",
    "Сімейний резорт із власним пляжем",
    "Елегантний комплекс у пальмовому парку",
    "Просторий all-inclusive у тихій частині курорту",
]
DESC_MIDS = [
    "пропонує великий басейн, аквапарк і анімаційні програми",
    "відомий високим рівнем сервісу та різноманітним харчуванням",
    "поєднує приватну територію з широким спектром розваг",
    "має кілька ресторанів a-la-carte та водні гірки",
    "славиться SPA-центром і власним піщано-гальковим пляжем",
]
DESC_TAILS = [
    "Чудовий вибір для родин з дітьми.",
    "Ідеально підходить для відпочинку парами.",
    "Гарне співвідношення ціни та якості.",
    "Один з найпопулярніших готелів регіону.",
    "Рекомендуємо для активного відпочинку.",
]


@dataclass(frozen=True)
class HotelRow:
    canonical_slug: str
    name_uk: str
    name_en: str
    stars: int
    destination_id: int
    region_slug: str
    coords_point: str  # already formatted as "(lat,lon)" for Postgres point type
    description_uk: str
    photos_jsonb: list[dict[str, str]]
    amenities: list[str]
    review_score: float
    review_count: int


def _slugify(value: str) -> str:
    """ASCII kebab-case slug."""
    decomposed = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    decomposed = decomposed.lower()
    decomposed = re.sub(r"[^a-z0-9]+", "-", decomposed).strip("-")
    return decomposed


def _build_hotel_rows(region_id_by_slug: dict[str, int]) -> list[HotelRow]:
    rows: list[HotelRow] = []
    cursor = 0
    for region_slug, _name_uk, _name_en, count, lat, lon in REGIONS:
        dest_id = region_id_by_slug[region_slug]
        for i in range(count):
            name = HOTEL_NAMES[cursor + i]
            # Star distribution: most 4/5*, a few 3*.
            stars = _rng.choices([3, 4, 5], weights=[1, 4, 5])[0]
            base_slug = f"{_slugify(name)}-{region_slug}-tr"
            jitter_lat = lat + _rng.uniform(-0.05, 0.05)
            jitter_lon = lon + _rng.uniform(-0.05, 0.05)
            n_amenities = _rng.randint(3, 7)
            amenities = _rng.sample(AMENITIES_POOL, n_amenities)
            n_photos = _rng.randint(3, 5)
            slug_for_photo = base_slug
            photos = [
                {
                    "url": f"https://picsum.photos/seed/{slug_for_photo}-{n}/1200/800",
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


def _base_price_usd(stars: int) -> int:
    if stars == 5:
        return _rng.randint(2500, 3500)
    if stars == 4:
        return _rng.randint(1500, 2500)
    return _rng.randint(800, 1500)


def _nights_multiplier(nights: int) -> float:
    return {7: 1.0, 10: 1.35, 14: 1.85}[nights]


def _meal_multiplier(meal: str) -> float:
    return {"AI": 1.25, "HB": 1.0}[meal]


def _seasonal_multiplier(check_in: date) -> float:
    """Smooth seasonality with peak in late July / early August.

    Returns multiplier in roughly [0.80, 1.25].
    """
    # day-of-year, normalized so day 213 (Aug 1) is peak
    day = check_in.timetuple().tm_yday
    angle = 2 * math.pi * (day - 213) / 365.0
    return 1.0 + 0.225 * math.cos(angle)


async def _table_already_seeded(conn: AsyncConnection) -> bool:
    """Sentinel check — cheap and partition-safe."""
    result = await conn.execute(
        text("SELECT 1 FROM hotels WHERE canonical_slug = :slug LIMIT 1"),
        {"slug": SENTINEL_SLUG},
    )
    return result.first() is not None


async def _ensure_partitions_cover_history(
    conn: AsyncConnection, history_days: int
) -> None:
    """Sanity-check that the partition set covers the historical seed window.

    pg_partman 5.x already creates a `default` partition (catch-all) and
    pre-creates several weekly partitions when `create_parent` runs in the
    migration. That means any historical observed_at value is guaranteed to
    land *somewhere*: either an explicit weekly partition or the default.

    Trying to backfill with `partman.create_partition_time(...)` is brittle
    because partman's week boundaries do not align with calendar Mondays
    (it picks Saturdays in our installation) — passing a Monday triggers
    an "overlap" error against the existing weekly partition that already
    spans that day. So we don't backfill; we verify the default exists and
    log the earliest covered week.
    """
    result = await conn.execute(
        text(
            """
            SELECT MIN(inhrelid::regclass::text) AS earliest_partition,
                   bool_or(inhrelid::regclass::text = 'price_observations_default') AS has_default
            FROM pg_inherits
            WHERE inhparent = 'public.price_observations'::regclass
            """
        )
    )
    row = result.first()
    if row is None or not row.has_default:
        raise RuntimeError(
            "price_observations has no `default` partition — historical seed rows "
            "would be rejected. Re-run alembic migrations on a clean cluster, or "
            "manually CREATE TABLE ... PARTITION OF price_observations DEFAULT."
        )
    print(
        f"  default partition present; earliest weekly = {row.earliest_partition}",
        flush=True,
    )
    # history_days reference is kept so future tightening of this check
    # (e.g. require a weekly partition for every day in window) is a one-line
    # change rather than a new function signature.
    _ = history_days


async def _insert_operators(conn: AsyncConnection) -> dict[str, int]:
    """INSERT operators, return {code: id} map."""
    sql = text(
        """
        INSERT INTO operators (code, display_name, affiliate_url_template, is_active)
        VALUES (:code, :display_name, :affiliate_url_template, TRUE)
        RETURNING id, code
        """
    )
    out: dict[str, int] = {}
    for op_row in OPERATORS:
        result = await conn.execute(sql, op_row)
        row = result.first()
        assert row is not None
        out[row.code] = row.id
    return out


async def _insert_destinations(conn: AsyncConnection) -> dict[str, int]:
    """INSERT country + regions, return {region_slug: id} map.

    Country gets its own slug ("turkey") inserted first so children can
    point at it via parent_id. We deliberately namespace the country slug
    so a region lookup by slug "turkey" never collides with a region.
    """
    out: dict[str, int] = {}
    # Country (root)
    result = await conn.execute(
        text(
            """
            INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en, parent_id)
            VALUES (:country_iso2, :region_slug, :name_uk, :name_en, NULL)
            RETURNING id
            """
        ),
        COUNTRY_TR,
    )
    country_id = result.scalar_one()
    out["__country__"] = country_id

    for region_slug, name_uk, name_en, _count, _lat, _lon in REGIONS:
        result = await conn.execute(
            text(
                """
                INSERT INTO destinations (country_iso2, region_slug, name_uk, name_en, parent_id)
                VALUES (:country_iso2, :region_slug, :name_uk, :name_en, :parent_id)
                RETURNING id
                """
            ),
            {
                "country_iso2": "TR",
                "region_slug": region_slug,
                "name_uk": name_uk,
                "name_en": name_en,
                "parent_id": country_id,
            },
        )
        out[region_slug] = result.scalar_one()
    return out


async def _insert_hotels(
    conn: AsyncConnection, hotels: list[HotelRow]
) -> dict[str, int]:
    """INSERT hotels, return {canonical_slug: hotel_id} map.

    `coords` is Postgres' `point` type, which is awkward to bind through
    asyncpg: it tries to interpret a string bind as a real number and
    refuses any explicit ::point cast on a bind parameter. The cleanest
    fix is to inline the literal as `point '(lat,lon)'` per row — that
    bypasses parameter binding for that column without losing the type.
    Coords come from a hard-coded list, not user input, so SQL injection
    is not in scope here.
    """
    import json

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
) -> list[tuple[int, int, str]]:
    """Map each hotel to 2-3 operators. Return list of (hotel_id, operator_id, external_id)."""
    operator_codes = list(operator_id_by_code.keys())
    rows: list[dict[str, Any]] = []
    triples: list[tuple[int, int, str]] = []
    used_external_ids: set[tuple[int, str]] = set()
    for h in hotels:
        hotel_id = hotel_id_by_slug[h.canonical_slug]
        n_ops = _rng.choice([2, 2, 3])
        chosen_ops = _rng.sample(operator_codes, n_ops)
        for code in chosen_ops:
            op_id = operator_id_by_code[code]
            # Pick a unique external_id within (operator). Loop is microscopic.
            while True:
                ext = str(_rng.randint(10000, 99999))
                if (op_id, ext) not in used_external_ids:
                    used_external_ids.add((op_id, ext))
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
            INSERT INTO hotel_operator_mapping (operator_id, external_id, hotel_id, external_name)
            VALUES (:operator_id, :external_id, :hotel_id, :external_name)
            """
        ),
        rows,
    )
    return triples


def _affiliate_deep_link(template: str | None, external_id: str) -> str | None:
    if template is None:
        return None
    return template.replace("{external_id}", external_id)


async def _insert_price_observations(
    conn: AsyncConnection,
    hotels: list[HotelRow],
    hotel_id_by_slug: dict[str, int],
    mapping_triples: list[tuple[int, int, str]],
    operator_id_by_code: dict[str, int],
    full: bool,
) -> int:
    """Bulk INSERT into the partitioned price_observations table.

    Returns the number of rows inserted.
    """
    operator_template_by_id: dict[int, str | None] = {}
    operator_code_by_id = {v: k for k, v in operator_id_by_code.items()}
    for op_row in OPERATORS:
        operator_template_by_id[operator_id_by_code[op_row["code"]]] = op_row[
            "affiliate_url_template"
        ]

    hotel_by_id: dict[int, HotelRow] = {}
    for h in hotels:
        hotel_by_id[hotel_id_by_slug[h.canonical_slug]] = h

    base_price_by_hotel_op: dict[tuple[int, int], int] = {}
    # Each (hotel, operator) pair gets a slight pricing offset so the same
    # hotel shows different prices across operators.
    for hotel_id, op_id, _ext in mapping_triples:
        h = hotel_by_id[hotel_id]
        base = _base_price_usd(h.stars)
        op_offset_pct = _rng.uniform(-0.08, 0.08)  # ±8% per operator
        base_price_by_hotel_op[(hotel_id, op_id)] = int(base * (1 + op_offset_pct))

    # Pick 6 "deal candidate" hotels that will have a few abnormally low days.
    deal_hotel_ids = set(
        _rng.sample(list(hotel_by_id.keys()), 6)
    )
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

    # Iterate snapshots outer (so partitions fill sequentially), then per-mapping
    snapshot_offsets = list(range(history_days + 1))  # 0..N inclusive
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
                            price_usd = base_usd * nights_mult * meal_mult * season * noise
                            if is_deal_day:
                                # 25-40% off
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
        # Periodic progress log so a slow `--full` run isn't silent.
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

    # Silence linter — operator_code_by_id intended for future debug use.
    _ = operator_code_by_id
    return total


async def _refresh_materialized_views(conn: AsyncConnection) -> None:
    """First refresh after seed — MUST be non-concurrent (MVs were WITH NO DATA)."""
    for view in ("current_prices", "hotel_calendar_prices", "price_baselines"):
        print(f"  REFRESH MATERIALIZED VIEW {view} ...", flush=True)
        await conn.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))


async def seed(full: bool = False) -> None:
    """Idempotent seed entrypoint."""
    print(
        f"FastTravel demo seed — mode={'FULL (30d history)' if full else 'DEFAULT (7d history)'}",
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

        print("[2/7] Inserting operators ...", flush=True)
        operator_id_by_code = await _insert_operators(conn)

        print("[3/7] Inserting destinations (country + 5 regions) ...", flush=True)
        region_id_by_slug = await _insert_destinations(conn)

        print("[4/7] Building and inserting 50 hotels ...", flush=True)
        hotel_rows = _build_hotel_rows(region_id_by_slug)
        hotel_id_by_slug = await _insert_hotels(conn, hotel_rows)

        print("[5/7] Inserting hotel_operator_mapping rows ...", flush=True)
        mapping_triples = await _insert_mappings(
            conn, hotel_rows, hotel_id_by_slug, operator_id_by_code
        )
        print(f"  -> {len(mapping_triples)} mapping rows", flush=True)

        print("[6/7] Inserting price_observations (this is the heavy step) ...", flush=True)
        total_obs = await _insert_price_observations(
            conn,
            hotel_rows,
            hotel_id_by_slug,
            mapping_triples,
            operator_id_by_code,
            full=full,
        )
        print(f"  -> {total_obs:,} price_observations rows", flush=True)

    # MV refresh must NOT run inside the same outer transaction (Postgres
    # rejects REFRESH MATERIALIZED VIEW in a transaction block in some edge
    # cases — and we want a fresh snapshot for the subsequent COUNT queries).
    async with async_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        print("[7/7] Refreshing materialized views ...", flush=True)
        await _refresh_materialized_views(conn)

    # Stats summary
    async with async_engine.connect() as conn:
        counts = {}
        for tbl in (
            "operators",
            "destinations",
            "hotels",
            "hotel_operator_mapping",
            "price_observations",
            "current_prices",
            "hotel_calendar_prices",
            "price_baselines",
        ):
            r = await conn.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            counts[tbl] = r.scalar_one()
        sample_slug = await conn.scalar(
            text("SELECT canonical_slug FROM hotels ORDER BY id LIMIT 1")
        )

    print("\nSeed complete. Row counts:", flush=True)
    for tbl, n in counts.items():
        print(f"  {tbl:30s} {n:>12,}", flush=True)
    if sample_slug:
        print(f"\nTry: GET /api/hotels/{sample_slug}", flush=True)


async def _main_async(full: bool) -> None:
    try:
        await seed(full=full)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed FastTravel demo data.")
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
