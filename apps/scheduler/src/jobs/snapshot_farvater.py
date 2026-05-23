"""Full farvater.travel ingest — discovers all hotels in all supported
countries and snapshots their price calendars.

Pattern (discovered via tools/explore/):

  catalog page:  GET  /uk/hotelscatalog/strana-{slug}/
                       → HTML containing /uk/hotel/{iso2}/{slug}/ links
  hotel page:    GET  /uk/hotel/{iso2}/{slug}/
                       → HTML; `hotelId:NNNN` in inline JS is the ittour mapKey,
                         og:image is the canonical photo, meta description is
                         a usable short description.
  prices:        POST /uk/tour/stat/low-price-calendar/auto
                       ?hotelKey={id}&adults=2&meals=all&checkIn=DD.MM.YYYY
                  body: {"dateShift":7,"nights":[7,10,14],"townFroms":"all"}
                  → {data: {items: [{item: {night, dates: [{date, price,
                                                              priceUAH, meal,
                                                              room, systemKey}]}}]}}

How this differs from the one-shot tools/explore/fetch_farvater_prices.py:
  * runs as an APScheduler job inside the scheduler container
  * INSERTs are idempotent — re-running the snapshot only writes new
    observations (dedup by (hotel_id, operator_id, check_in, nights,
    meal_plan, price_uah) within the last 12h)
  * concurrency-3 per host, plus 1s spacing per worker, so we stay polite
    even when the catalog grows
  * records progress to scrape_runs so the dashboards can track success rate
  * captures ALL countries we have in destinations (TR, EG, AE, GR, ES, BG,
    ME, HR, CY, TH, MV) and ALL hotels per country (no per-country cap)
  * tries 6 check-in offsets so hotels with sparse near-term availability
    still get represented

This module is imported by src/main.py and scheduled cron('0 6,18 * * *')
in Europe/Kyiv. A standalone CLI is provided for ad-hoc runs.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import AsyncIterator

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


# ── tunables ──────────────────────────────────────────────────────────────
USER_AGENT = (
    "FastTravel-Bot/1.0 (+https://fasttravel.com.ua/about; "
    "snapshot 2x/day; respects robots.txt)"
)
PER_REQUEST_DELAY_S = 1.0
CONCURRENCY = 3
CHECK_IN_OFFSETS_DAYS = [3, 14, 30, 45, 60, 75]
NIGHTS = [7, 10, 14]
DEDUP_WINDOW_HOURS = 12

CATALOG_COUNTRIES = [
    ("turkey",     "TR"),
    ("egypt",      "EG"),
    ("uae",        "AE"),
    ("greece",     "GR"),
    ("spain",      "ES"),
    ("bulgaria",   "BG"),
    ("thailand",   "TH"),
    ("cyprus",     "CY"),
    ("croatia",    "HR"),
    ("montenegro", "ME"),
    ("maldives",   "MV"),
]

HOTEL_URL_RE = re.compile(
    r'href="(/uk/hotel/[a-z]{2,3}/[a-z0-9-]+/)"', re.IGNORECASE
)
HOTEL_ID_RE = re.compile(r'hotelId:(\d+)')
TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.IGNORECASE)
DESC_RE = re.compile(r'<meta name="description" content="([^"]+)"', re.IGNORECASE)
OG_IMG_RE = re.compile(r'<meta property="og:image" content="([^"]+)"', re.IGNORECASE)

# Star rating. Primary signal: JSON-LD `"starRating":{"ratingValue":"N"}`
# (present on most rated farvater hotels). Fallback: H1/title pattern like
# `Sunset 3*` / `Pickalbatros Vita Resort - Portofino 5*` — digit must be
# preceded by whitespace or `-` and immediately followed by `*` to avoid
# false positives on years / model numbers. Constrained to [1-5] because
# `hotels.stars` carries `CHECK (stars BETWEEN 1 AND 5)`.
STAR_JSONLD_RE = re.compile(
    r'"starRating"\s*:\s*\{[^}]*?"ratingValue"\s*:\s*"?([1-5])"?',
    re.IGNORECASE,
)
STAR_TITLE_RE = re.compile(r'[\s\-]([1-5])\*')

OPERATOR_CODE = "farvater"


# ── data classes ─────────────────────────────────────────────────────────
@dataclass
class HotelMeta:
    hotel_id: int          # ittour mapKey == farvater hotelKey
    url_path: str
    name: str
    country_iso2: str
    photo_url: str
    description: str
    stars: int | None      # 1..5 when extractable; None for villas/apartments


@dataclass
class PriceRow:
    hotel_id: int          # farvater hotelKey
    check_in: date
    nights: int
    meal_plan: str
    room_category: str
    price_uah: int
    price_usd: int
    system_key: str


# ── helpers ──────────────────────────────────────────────────────────────
def _clean_title(raw: str) -> str:
    """farvater titles look like 'ᐉ Pickalbatros Vita ✈ Ціни ... ☛ Farvater'.
    Pull the hotel-name segment; fall back to the canonical_slug if we strike out.
    """
    t = re.sub(r'^[ᐉ\s]+', '', raw.strip())
    m = re.search(r'(?:готель|hotel)\s+(.+)', t, re.IGNORECASE)
    if m:
        t = m.group(1)
    for sep in ('✈', '★', '☛', '☆', '·', ' - ', '|', ','):
        i = t.find(sep)
        if i > 3:
            t = t[:i]
    cleaned = t.strip()
    return cleaned if len(cleaned) > 3 else raw.strip()


def _make_slug(country_iso2: str, url_path: str) -> str:
    tail = url_path.rstrip("/").rsplit("/", 1)[-1]
    return f"fv-{country_iso2.lower()}-{tail}"[:140]


def _extract_stars(html: str) -> int | None:
    """Return 1..5 if a star rating is unambiguous in the page, else None.

    JSON-LD `starRating` is preferred — it's the schema.org canonical and
    farvater emits it for rated hotels. Falls back to the `N*` suffix in
    H1/title for hotels where JSON-LD is missing. Apartments / villas
    legitimately have no rating and return None (the DB column is nullable).
    """
    m = STAR_JSONLD_RE.search(html)
    if m:
        return int(m.group(1))
    title = TITLE_RE.search(html)
    if title:
        t = STAR_TITLE_RE.search(title.group(1))
        if t:
            return int(t.group(1))
    return None


# ── network ──────────────────────────────────────────────────────────────
async def _list_country_hotels(client: httpx.AsyncClient,
                               country_slug: str) -> list[str]:
    url = f"https://farvater.travel/uk/hotelscatalog/strana-{country_slug}/"
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    seen: set[str] = set()
    out: list[str] = []
    for m in HOTEL_URL_RE.finditer(r.text):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


async def _fetch_hotel_meta(client: httpx.AsyncClient, url_path: str,
                            iso2: str) -> HotelMeta | None:
    url = f"https://farvater.travel{url_path}"
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    except Exception as exc:
        log.warning("farvater.hotel_fetch_failed", url=url, error=str(exc))
        return None
    if r.status_code != 200:
        log.warning("farvater.hotel_fetch_http", url=url, status=r.status_code)
        return None
    html = r.text
    hid = HOTEL_ID_RE.search(html)
    if not hid:
        log.warning("farvater.no_hotel_id_in_html", url=url)
        return None
    title_m = TITLE_RE.search(html)
    desc_m = DESC_RE.search(html)
    img_m = OG_IMG_RE.search(html)
    return HotelMeta(
        hotel_id=int(hid.group(1)),
        url_path=url_path.rstrip("/"),
        name=_clean_title(title_m.group(1)) if title_m else f"Hotel {hid.group(1)}",
        country_iso2=iso2,
        photo_url=(img_m.group(1) if img_m else "")[:512],
        description=(desc_m.group(1) if desc_m else "")[:1000],
        stars=_extract_stars(html),
    )


async def _fetch_calendar(client: httpx.AsyncClient, hotel_id: int,
                          check_in: date) -> list[PriceRow]:
    url = (
        f"https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
        f"?hotelKey={hotel_id}&adults=2&ages=0&meals=all"
        f"&checkIn={check_in.strftime('%d.%m.%Y')}"
    )
    body = {"dateShift": 7, "nights": NIGHTS, "townFroms": "all"}
    try:
        r = await client.post(
            url, json=body, timeout=30,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    except Exception as exc:
        log.warning("farvater.calendar_fetch_failed",
                    hotel_id=hotel_id, error=str(exc))
        return []
    if r.status_code != 200:
        return []
    payload = r.json()
    if payload.get("statusCode") != 200:
        return []
    out: list[PriceRow] = []
    for w in payload["data"]["items"]:
        item = w["item"]
        n = int(item["night"])
        for d in item["dates"]:
            try:
                check_date = datetime.strptime(d["date"], "%d.%m.%Y").date()
            except Exception:
                continue
            out.append(PriceRow(
                hotel_id=hotel_id,
                check_in=check_date,
                nights=n,
                meal_plan=(d.get("meal") or "OTHER")[:8],
                room_category=(d.get("room") or "")[:64],
                price_uah=int(d.get("priceUAH") or 0),
                price_usd=int(d.get("price") or 0),
                system_key=str(d.get("systemKey") or ""),
            ))
    return out


# ── DB writes ────────────────────────────────────────────────────────────
async def _ensure_operator(db: AsyncSession) -> int:
    row = (await db.execute(
        text("SELECT id FROM operators WHERE code = :c"), {"c": OPERATOR_CODE}
    )).first()
    if row:
        return row[0]
    row = (await db.execute(
        text("""INSERT INTO operators (code, display_name,
                                       affiliate_url_template, is_active)
                VALUES (:c, :n, :t, TRUE)
                RETURNING id"""),
        {"c": OPERATOR_CODE,
         "n": "Фарватер",
         "t": "https://farvater.travel{external_id}"},
    )).first()
    await db.commit()
    return row[0]


async def _country_dest_id(db: AsyncSession, iso2: str) -> int | None:
    row = (await db.execute(
        text("""SELECT id FROM destinations
                WHERE country_iso2 = :iso AND parent_id IS NULL
                LIMIT 1"""),
        {"iso": iso2},
    )).first()
    return row[0] if row else None


async def _upsert_hotel(db: AsyncSession, hotel: HotelMeta,
                        dest_id: int | None) -> int:
    """Upsert one hotel and stamp `last_seen_at = NOW()` — this is the
    catalog-freshness heartbeat that both `snapshot_catalog_farvater` and
    `snapshot_farvater` share. `last_priced_at` / `has_active_prices` are
    bumped separately by `_mark_priced` only when new prices land.
    """
    slug = _make_slug(hotel.country_iso2, hotel.url_path)
    existing = (await db.execute(
        text("SELECT id FROM hotels WHERE canonical_slug = :s"),
        {"s": slug},
    )).first()
    if existing:
        # Keep clean name + fresh photo/description. `stars` is COALESCEd so
        # a one-off regex miss on a future page render never wipes a value
        # we previously extracted — extraction is monotonic.
        await db.execute(
            text("""UPDATE hotels
                    SET name_uk = :n, name_en = :n,
                        photos_jsonb = CAST(:p AS jsonb),
                        description_uk = :d,
                        stars = COALESCE(:stars, stars),
                        last_seen_at = NOW(),
                        last_updated = NOW()
                    WHERE id = :id"""),
            {
                "id": existing[0], "n": hotel.name,
                "p": json.dumps([{"url": hotel.photo_url, "alt": hotel.name}]
                                 if hotel.photo_url else []),
                "d": hotel.description,
                "stars": hotel.stars,
            },
        )
        return existing[0]

    photos = json.dumps(
        [{"url": hotel.photo_url, "alt": hotel.name}] if hotel.photo_url else []
    )
    row = (await db.execute(
        text("""INSERT INTO hotels (
                  canonical_slug, name_uk, name_en, stars, destination_id,
                  description_uk, photos_jsonb, amenities, review_score,
                  review_count, is_active, last_seen_at, last_updated)
                VALUES (:slug, :n, :n, :stars, :dest, :d, CAST(:p AS jsonb),
                        '{}', NULL, 0, TRUE, NOW(), NOW())
                RETURNING id"""),
        {"slug": slug, "n": hotel.name, "stars": hotel.stars, "dest": dest_id,
         "d": hotel.description, "p": photos},
    )).first()
    return row[0]


async def _mark_priced(db: AsyncSession, hotel_db_id: int) -> None:
    """Flip a hotel into the live-priced cohort.

    Called only when `_insert_prices` actually wrote new rows — runs that
    fetched and dedup'd to zero shouldn't claim the hotel has fresh
    prices. Keeps `has_active_prices` honest as a search-time gate.
    """
    await db.execute(
        text("""UPDATE hotels
                SET last_priced_at = NOW(),
                    has_active_prices = TRUE
                WHERE id = :id"""),
        {"id": hotel_db_id},
    )


async def _decay_active_prices(db: AsyncSession,
                               stale_after_days: int = 7) -> int:
    """Flip hotels back to `has_active_prices = FALSE` once their
    `last_priced_at` ages past the threshold. Returns the number of
    hotels demoted in this pass.

    Runs at the tail of `snapshot_farvater` so the search gate stays in
    sync without needing a separate cleanup job. `last_seen_at` is left
    alone — the hotel still exists in the catalog; only its price
    freshness is in question.
    """
    res = await db.execute(
        text("""UPDATE hotels
                SET has_active_prices = FALSE
                WHERE has_active_prices = TRUE
                  AND (last_priced_at IS NULL
                       OR last_priced_at < NOW()
                          - make_interval(days => :d))"""),
        {"d": stale_after_days},
    )
    return res.rowcount or 0


async def _upsert_mapping(db: AsyncSession, hotel_db_id: int,
                          operator_id: int, hotel: HotelMeta) -> None:
    await db.execute(
        text("""INSERT INTO hotel_operator_mapping
                      (operator_id, external_id, hotel_id, external_name)
                VALUES (:op, :ext, :h, :n)
                ON CONFLICT (operator_id, external_id) DO NOTHING"""),
        {"op": operator_id, "ext": str(hotel.hotel_id),
         "h": hotel_db_id, "n": hotel.name},
    )


async def _dedup_existing(db: AsyncSession, hotel_db_id: int,
                          operator_id: int) -> set[tuple]:
    """Return (check_in, nights, meal_plan, price_uah) tuples already in DB
    within the dedup window. We use that to skip identical inserts."""
    rows = (await db.execute(
        text("""SELECT check_in, nights, meal_plan, price_uah
                FROM price_observations
                WHERE hotel_id = :h AND operator_id = :op
                  AND observed_at >= NOW() - make_interval(hours => :hh)"""),
        {"h": hotel_db_id, "op": operator_id, "hh": DEDUP_WINDOW_HOURS},
    )).all()
    return {(r[0], r[1], r[2], r[3]) for r in rows}


async def _insert_prices(db: AsyncSession, hotel_db_id: int,
                         operator_id: int, hotel: HotelMeta,
                         rows: list[PriceRow]) -> int:
    if not rows:
        return 0
    existing = await _dedup_existing(db, hotel_db_id, operator_id)
    new_rows = [r for r in rows
                if (r.check_in, r.nights, r.meal_plan, r.price_uah) not in existing]
    if not new_rows:
        return 0

    observed_at = datetime.now(UTC)
    fx = (Decimal(rows[0].price_uah) / Decimal(rows[0].price_usd)
          if rows[0].price_usd else Decimal("41.5"))
    deep_link_base = f"https://farvater.travel{hotel.url_path}"

    payload = [
        {
            "obs": observed_at, "h": hotel_db_id, "op": operator_id,
            "ci": r.check_in, "n": r.nights, "m": r.meal_plan, "rm": r.room_category,
            "ad": 2, "dc": "",
            "puah": r.price_uah, "porig": r.price_usd, "cur": "USD", "fx": fx,
            "dl": f"{deep_link_base}?systemKey={r.system_key}",
            "raw": json.dumps({"systemKey": r.system_key,
                                "source": "farvater_scrape"}),
        }
        for r in new_rows
    ]

    await db.execute(
        text("""INSERT INTO price_observations
                  (observed_at, hotel_id, operator_id, check_in, nights,
                   meal_plan, room_category, adults, departure_city,
                   price_uah, price_original, currency, fx_rate_to_uah,
                   deep_link, raw_payload)
                VALUES (:obs, :h, :op, :ci, :n, :m, :rm, :ad, :dc,
                        :puah, :porig, :cur, :fx, :dl, CAST(:raw AS jsonb))"""),
        payload,
    )
    return len(payload)


async def _record_run(db: AsyncSession, operator_id: int,
                      status: str, rows_inserted: int,
                      error: str = "", started_at: datetime | None = None) -> None:
    await db.execute(
        text("""INSERT INTO scrape_runs
                  (started_at, finished_at, operator_id, source, status,
                   rows_inserted, error_text)
                VALUES (:s, NOW(), :op, 'farvater_scrape', :st, :n, :e)"""),
        {"s": started_at or datetime.now(UTC), "op": operator_id,
         "st": status, "n": rows_inserted, "e": error[:500]},
    )


# ── orchestration ────────────────────────────────────────────────────────
@asynccontextmanager
async def _http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        timeout=30,
    ) as c:
        yield c


async def _process_hotel(
    client: httpx.AsyncClient, url_path: str, iso2: str,
    operator_id: int, dest_id: int | None,
    semaphore: asyncio.Semaphore,
) -> int:
    """Fetch one hotel's meta + calendar(s) and write them. Returns rows inserted."""
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await _fetch_hotel_meta(client, url_path, iso2)
        if meta is None:
            return 0

        all_prices: list[PriceRow] = []
        seen_keys: set[str] = set()
        for offset in CHECK_IN_OFFSETS_DAYS:
            await asyncio.sleep(PER_REQUEST_DELAY_S)
            chunk = await _fetch_calendar(
                client, meta.hotel_id,
                check_in=date.today() + timedelta(days=offset),
            )
            new = [r for r in chunk if r.system_key not in seen_keys]
            all_prices.extend(new)
            seen_keys.update(r.system_key for r in new)

    # Write outside the semaphore to keep network slots free.
    async with async_session_factory() as db:
        hotel_db_id = await _upsert_hotel(db, meta, dest_id)
        await _upsert_mapping(db, hotel_db_id, operator_id, meta)
        inserted = await _insert_prices(db, hotel_db_id, operator_id, meta, all_prices)
        # Only flip the live-prices flag when we actually wrote new rows.
        # A dedup-only pass shouldn't pretend the hotel is fresh-priced.
        if inserted > 0:
            await _mark_priced(db, hotel_db_id)
        await db.commit()
    log.info("farvater.hotel.done", hotel=meta.name[:60],
             hotel_key=meta.hotel_id, calendar=len(all_prices),
             inserted=inserted)
    return inserted


async def snapshot_farvater(*, max_hotels_per_country: int | None = None) -> int:
    """Top-level entrypoint. Returns total rows inserted.

    Args:
      max_hotels_per_country: optional cap for dev/testing; None = all hotels.
    """
    started_at = datetime.now(UTC)
    log.info("farvater.snapshot.start",
             countries=len(CATALOG_COUNTRIES),
             concurrency=CONCURRENCY)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    total_inserted = 0

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    try:
        async with _http_client() as client:
            for country_slug, iso2 in CATALOG_COUNTRIES:
                async with async_session_factory() as db:
                    dest_id = await _country_dest_id(db, iso2)

                try:
                    hotel_paths = await _list_country_hotels(client, country_slug)
                except Exception as exc:
                    log.error("farvater.catalog_failed",
                              country=country_slug, error=str(exc))
                    continue
                if max_hotels_per_country:
                    hotel_paths = hotel_paths[:max_hotels_per_country]
                log.info("farvater.country.start",
                         country=country_slug, iso2=iso2,
                         hotels=len(hotel_paths))

                tasks = [
                    _process_hotel(client, p, iso2, operator_id, dest_id,
                                    semaphore)
                    for p in hotel_paths
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                country_inserted = sum(r for r in results if isinstance(r, int))
                country_errors = sum(1 for r in results if isinstance(r, Exception))
                total_inserted += country_inserted
                log.info("farvater.country.done",
                         country=country_slug, hotels=len(hotel_paths),
                         inserted=country_inserted, errors=country_errors)

        # Final MV refresh so /api reads see fresh data this same tick.
        async with async_session_factory() as db:
            for mv in ("current_prices", "hotel_calendar_prices",
                        "price_baselines"):
                await db.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))
            await db.commit()

        # Decay the search gate for hotels that stopped surfacing prices.
        # Run after the MV refresh so the cohort the next /search hits is
        # consistent with the freshly written observations.
        async with async_session_factory() as db:
            decayed = await _decay_active_prices(db)
            await db.commit()
        log.info("farvater.snapshot.decayed",
                 hotels_demoted=decayed,
                 threshold_days=7)

        async with async_session_factory() as db:
            await _record_run(db, operator_id, "success", total_inserted,
                              started_at=started_at)
            await db.commit()
        log.info("farvater.snapshot.done", inserted=total_inserted)
        return total_inserted

    except Exception as exc:
        async with async_session_factory() as db:
            await _record_run(db, operator_id, "failed", total_inserted,
                              error=str(exc), started_at=started_at)
            await db.commit()
        log.error("farvater.snapshot.failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(snapshot_farvater(max_hotels_per_country=cap))
