"""Fetch REAL prices from farvater.travel for a handful of hotels and write
them into our local Postgres. End-to-end PoC: catalog → hotel HTML → hotelKey
→ price-calendar JSON → price_observations rows → REFRESH MV → UI shows real data.

Endpoints discovered via Playwright exploration (see explore_hotel.py):

  GET  /uk/hotelscatalog/strana-{slug}/      → HTML grid with hotel URLs
  GET  /uk/hotel/{country}/{slug}/           → hotel HTML, contains `hotelId:NNNN`
  POST /uk/tour/stat/low-price-calendar/auto?hotelKey={id}&adults=2&ages=0
       &meals=all&checkIn=DD.MM.YYYY
       body: {"dateShift":7,"nights":[7,8,...,14],"townFroms":"all"}
       returns: {data: {items: [{item: {night: 7, dates: [{date, price, priceUAH,
                                                            meal, room, systemKey}]}}]}}

We DON'T touch the existing 252 synthetic hotels — we add a 'farvater'
operator + new hotels with slug prefix `fv-` so:
  * synthetic and real coexist cleanly,
  * a follow-up can run delete-from-where-operator-code='farvater' to wipe
    this PoC if anything goes wrong,
  * the UI shows real data for the new ones without affecting demo seeds.

Politeness:
  * 1.5s sleep between requests
  * User-Agent stating we're a research bot
  * Conservative — only 5 hotels per country, only Turkey + Egypt
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import asyncpg

USER_AGENT = (
    "FastTravel-Bootstrap/0.1 (+https://github.com/yourrepo "
    "research bot, conservative rate, 1.5s spacing)"
)

DB_DSN = os.getenv(
    "DATABASE_URL_PG",
    "postgresql://fasttravel:fasttravel_dev_change_me@localhost:5432/fasttravel",
)

HOTEL_ID_RE = re.compile(r'hotelId:(\d+)')

# Hand-picked countries — same country_iso2 as our destinations table.
CATALOG_TARGETS = [
    {"slug": "egypt", "iso2": "EG", "max_hotels": 10},
    {"slug": "turkey", "iso2": "TR", "max_hotels": 10},
]

# Calendar fan-out: try several start dates so we don't miss the few hotels
# whose nearest availability is two weeks out.
CHECK_IN_OFFSETS_DAYS = [3, 14, 30, 45, 60]

# Politeness.
PER_REQUEST_DELAY_S = 1.5


@dataclass
class FarvaterHotel:
    hotel_id: int                # farvater hotelKey (== ittour mapkey)
    url_path: str                # /uk/hotel/eg/albatros-palace-resort-spa
    name: str                    # from <title>
    country_iso2: str            # 'EG'
    photo_url: str               # canonical og:image
    description: str


@dataclass
class FarvaterPriceRow:
    hotel_id: int
    check_in: date
    nights: int
    meal_plan: str               # 'AI', 'HB', 'BB'
    room_category: str
    price_uah: int
    price_usd: int
    system_key: str              # opaque ittour offer id (for deep_link later)


# ────────────────────────────────────────────────────────────────────────────
# Catalog crawl — discover hotel URLs by country
# ────────────────────────────────────────────────────────────────────────────
HOTEL_URL_RE = re.compile(
    r'href="(/uk/hotel/[a-z]{2,3}/[a-z0-9-]+/)"',
    flags=re.IGNORECASE,
)


async def list_country_hotels(client: httpx.AsyncClient, country_slug: str,
                              limit: int) -> list[str]:
    """Return a deduped list of /uk/hotel/{country}/{slug}/ URLs from the catalog."""
    url = f"https://farvater.travel/uk/hotelscatalog/strana-{country_slug}/"
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    urls: list[str] = []
    seen = set()
    for m in HOTEL_URL_RE.finditer(r.text):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            urls.append(path)
        if len(urls) >= limit:
            break
    return urls


# ────────────────────────────────────────────────────────────────────────────
# Hotel HTML → metadata
# ────────────────────────────────────────────────────────────────────────────
TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.IGNORECASE)
DESCRIPTION_RE = re.compile(
    r'<meta name="description" content="([^"]+)"', re.IGNORECASE
)
OG_IMAGE_RE = re.compile(
    r'<meta property="og:image" content="([^"]+)"', re.IGNORECASE
)


def _clean_title(raw_title: str) -> str:
    """Extract the hotel name from farvater's title string.

    Observed patterns:
      "Тур в готель Albatros Palace Resort & Spa ★ Хургада, Єгипет"
      "ᐉ Pickalbatros Vita Resort Portofino ✈ Ціни на відпочинок ... ☛ Farvater"
      "- Farvater Travel"  (placeholder when hotel meta absent)
    Strategy: prefer text between an opening marker (ᐉ / готель / hotel) and
    a delimiter (✈ ★ · , ☛ ☆). Fall back to the original.
    """
    t = raw_title.strip()
    # 1) drop the "ᐉ " bullet that some pages prepend
    t = re.sub(r'^[ᐉ\s]+', '', t)
    # 2) try the "готель/hotel" prefix form
    m = re.search(r'(?:готель|hotel)\s+(.+)', t, re.IGNORECASE)
    if m:
        t = m.group(1)
    # 3) cut at the first known suffix delimiter
    for sep in ('✈', '★', '☛', '☆', '·', ' - ', '|', ','):
        idx = t.find(sep)
        if idx > 3:        # don't slice prefix-only strings
            t = t[:idx]
    cleaned = t.strip()
    return cleaned if len(cleaned) > 3 else raw_title.strip()


async def fetch_hotel_meta(client: httpx.AsyncClient, url_path: str,
                           country_iso2: str) -> FarvaterHotel | None:
    url = f"https://farvater.travel{url_path}"
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code != 200:
        print(f"  ! {url} → HTTP {r.status_code}", file=sys.stderr)
        return None
    html = r.text
    m = HOTEL_ID_RE.search(html)
    if not m:
        print(f"  ! no hotelId in {url}", file=sys.stderr)
        return None
    hotel_id = int(m.group(1))

    title_m = TITLE_RE.search(html)
    desc_m = DESCRIPTION_RE.search(html)
    img_m = OG_IMAGE_RE.search(html)
    return FarvaterHotel(
        hotel_id=hotel_id,
        url_path=url_path.rstrip("/"),
        name=_clean_title(title_m.group(1)) if title_m else f"Hotel {hotel_id}",
        country_iso2=country_iso2,
        photo_url=img_m.group(1) if img_m else "",
        description=(desc_m.group(1) if desc_m else "")[:500],
    )


# ────────────────────────────────────────────────────────────────────────────
# Price calendar
# ────────────────────────────────────────────────────────────────────────────
async def fetch_price_calendar(
    client: httpx.AsyncClient,
    hotel_id: int,
    check_in: date,
    nights: list[int],
) -> list[FarvaterPriceRow]:
    """Hit the low-price-calendar endpoint and normalize the result."""
    url = (
        f"https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
        f"?hotelKey={hotel_id}&adults=2&ages=0&meals=all"
        f"&checkIn={check_in.strftime('%d.%m.%Y')}"
    )
    body = {"dateShift": 7, "nights": nights, "townFroms": "all"}
    r = await client.post(
        url,
        json=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": f"https://farvater.travel/uk/hotel/eg/test/",
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f"  ! calendar HTTP {r.status_code} for hotel {hotel_id}",
              file=sys.stderr)
        return []
    payload = r.json()
    if payload.get("statusCode") != 200:
        print(f"  ! calendar {payload.get('statusCode')} for hotel {hotel_id}: "
              f"{payload.get('statusMessage')}", file=sys.stderr)
        return []

    out: list[FarvaterPriceRow] = []
    for item_wrap in payload["data"]["items"]:
        item = item_wrap["item"]
        n = int(item["night"])
        for d in item["dates"]:
            try:
                check_date = datetime.strptime(d["date"], "%d.%m.%Y").date()
            except Exception:
                continue
            out.append(
                FarvaterPriceRow(
                    hotel_id=hotel_id,
                    check_in=check_date,
                    nights=n,
                    meal_plan=(d.get("meal") or "OTHER")[:8],
                    room_category=(d.get("room") or "")[:64],
                    price_uah=int(d.get("priceUAH") or 0),
                    price_usd=int(d.get("price") or 0),
                    system_key=str(d.get("systemKey") or ""),
                )
            )
    return out


# ────────────────────────────────────────────────────────────────────────────
# DB writes
# ────────────────────────────────────────────────────────────────────────────
def make_slug(hotel: FarvaterHotel) -> str:
    """Stable URL-safe id we control. Prefix with `fv-` so it never clashes
    with the synthetic seed slugs."""
    # url_path ends like /uk/hotel/eg/albatros-palace-resort-spa
    tail = hotel.url_path.rsplit("/", 1)[-1]
    return f"fv-{hotel.country_iso2.lower()}-{tail}"[:140]


async def ensure_operator(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow("SELECT id FROM operators WHERE code = 'farvater'")
    if row:
        return row["id"]
    row = await conn.fetchrow(
        """INSERT INTO operators (code, display_name, affiliate_url_template, is_active)
           VALUES ('farvater', 'Фарватер', 'https://farvater.travel{external_id}', TRUE)
           RETURNING id"""
    )
    return row["id"]


async def country_destination_id(conn: asyncpg.Connection,
                                 country_iso2: str) -> int | None:
    row = await conn.fetchrow(
        "SELECT id FROM destinations WHERE country_iso2 = $1 AND parent_id IS NULL",
        country_iso2,
    )
    return row["id"] if row else None


async def upsert_hotel(conn: asyncpg.Connection, hotel: FarvaterHotel,
                       dest_id: int | None) -> int:
    slug = make_slug(hotel)
    existing = await conn.fetchrow(
        "SELECT id FROM hotels WHERE canonical_slug = $1", slug
    )
    if existing:
        return existing["id"]
    photos = json.dumps([{"url": hotel.photo_url, "alt": hotel.name}] if hotel.photo_url else [])
    row = await conn.fetchrow(
        """INSERT INTO hotels (
             canonical_slug, name_uk, name_en, stars, destination_id,
             description_uk, photos_jsonb, amenities, review_score, review_count,
             is_active, last_updated)
           VALUES ($1, $2, $3, NULL, $4, $5, $6::jsonb, $7, NULL, 0, TRUE, NOW())
           RETURNING id""",
        slug, hotel.name, hotel.name, dest_id, hotel.description,
        photos, [],
    )
    return row["id"]


async def upsert_mapping(conn: asyncpg.Connection, hotel_db_id: int,
                         operator_id: int, hotel: FarvaterHotel) -> None:
    ext = str(hotel.hotel_id)
    await conn.execute(
        """INSERT INTO hotel_operator_mapping
                 (operator_id, external_id, hotel_id, external_name)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (operator_id, external_id) DO NOTHING""",
        operator_id, ext, hotel_db_id, hotel.name,
    )


async def insert_prices(conn: asyncpg.Connection, hotel_db_id: int,
                        operator_id: int, hotel: FarvaterHotel,
                        rows: list[FarvaterPriceRow]) -> int:
    if not rows:
        return 0
    observed_at = datetime.now(UTC)
    fx_rate = (
        Decimal(rows[0].price_uah) / Decimal(rows[0].price_usd)
        if rows[0].price_usd else Decimal("41.5")
    )
    deep_link_base = f"https://farvater.travel{hotel.url_path}"

    payload = [
        (
            observed_at, hotel_db_id, operator_id, r.check_in, r.nights,
            r.meal_plan, r.room_category, 2, "", r.price_uah, r.price_usd,
            "USD", fx_rate, f"{deep_link_base}?systemKey={r.system_key}",
            json.dumps({"systemKey": r.system_key, "source": "farvater_scrape"}),
        )
        for r in rows
    ]

    await conn.executemany(
        """INSERT INTO price_observations
               (observed_at, hotel_id, operator_id, check_in, nights,
                meal_plan, room_category, adults, departure_city,
                price_uah, price_original, currency, fx_rate_to_uah,
                deep_link, raw_payload)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)""",
        payload,
    )
    return len(payload)


async def record_run(conn: asyncpg.Connection, operator_id: int,
                     rows_inserted: int, status: str, error: str = "") -> None:
    await conn.execute(
        """INSERT INTO scrape_runs
               (started_at, finished_at, operator_id, source, status,
                rows_inserted, error_text)
           VALUES (NOW() - INTERVAL '1 minute', NOW(), $1, 'farvater_scrape',
                   $2, $3, $4)""",
        operator_id, status, rows_inserted, error,
    )


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    print(f"FastTravel real-data ingest from farvater.travel\n", flush=True)

    async with httpx.AsyncClient(http2=True) as http:
        conn = await asyncpg.connect(DB_DSN)
        try:
            operator_id = await ensure_operator(conn)
            print(f"operator 'farvater' id = {operator_id}\n", flush=True)

            total_rows = 0
            for target in CATALOG_TARGETS:
                print(f"━━━ {target['iso2']} ({target['slug']}) ━━━", flush=True)
                dest_id = await country_destination_id(conn, target["iso2"])

                try:
                    hotel_paths = await list_country_hotels(
                        http, target["slug"], target["max_hotels"]
                    )
                except Exception as exc:
                    print(f"  ! catalog fetch failed: {exc}", flush=True)
                    continue
                print(f"  catalog returned {len(hotel_paths)} hotels", flush=True)

                for path in hotel_paths:
                    await asyncio.sleep(PER_REQUEST_DELAY_S)
                    try:
                        hotel = await fetch_hotel_meta(http, path, target["iso2"])
                    except Exception as exc:
                        print(f"  ! hotel meta fetch failed: {exc}", flush=True)
                        continue
                    if hotel is None:
                        continue

                    hotel_db_id = await upsert_hotel(conn, hotel, dest_id)
                    await upsert_mapping(conn, hotel_db_id, operator_id, hotel)

                    # Try several start dates — many hotels have no
                    # availability in the next 3 days but plenty further out.
                    all_prices: list[FarvaterPriceRow] = []
                    seen_keys: set[str] = set()
                    for offset in CHECK_IN_OFFSETS_DAYS:
                        await asyncio.sleep(PER_REQUEST_DELAY_S)
                        try:
                            chunk = await fetch_price_calendar(
                                http,
                                hotel.hotel_id,
                                check_in=date.today() + timedelta(days=offset),
                                nights=[7, 10, 14],
                            )
                        except Exception as exc:
                            print(f"  ! calendar fetch (+{offset}d) failed for "
                                  f"{hotel.name}: {exc}", flush=True)
                            continue
                        # Dedup across overlapping calendar windows.
                        new = [r for r in chunk if r.system_key not in seen_keys]
                        all_prices.extend(new)
                        seen_keys.update(r.system_key for r in new)

                    inserted = await insert_prices(
                        conn, hotel_db_id, operator_id, hotel, all_prices
                    )
                    total_rows += inserted
                    print(f"  ✓ {hotel.name[:50]:50} key={hotel.hotel_id} "
                          f"prices={len(all_prices):3} inserted={inserted}",
                          flush=True)

            await record_run(conn, operator_id, total_rows, "success")

            print(f"\n✅ TOTAL real rows inserted: {total_rows}", flush=True)

            print("\nRefreshing materialized views…", flush=True)
            for mv in ("current_prices", "hotel_calendar_prices", "price_baselines"):
                await conn.execute(f"REFRESH MATERIALIZED VIEW {mv}")
            print("  done.\n", flush=True)

            # Print verification
            rows = await conn.fetch(
                """SELECT h.canonical_slug, h.name_uk, COUNT(p.id) AS prices,
                          MIN(p.price_uah) AS min_uah, MAX(p.price_uah) AS max_uah
                   FROM hotels h
                   JOIN price_observations p ON p.hotel_id = h.id
                   WHERE h.canonical_slug LIKE 'fv-%'
                   GROUP BY h.canonical_slug, h.name_uk
                   ORDER BY h.id"""
            )
            print("REAL HOTELS IN DB:")
            for r in rows:
                print(f"  /{r['canonical_slug']:55} {r['name_uk'][:35]:35} "
                      f"{r['prices']:3} obs  min={r['min_uah']:>7} UAH  "
                      f"max={r['max_uah']:>7} UAH")

        finally:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
