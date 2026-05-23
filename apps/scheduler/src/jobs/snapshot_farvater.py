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
import html
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
# Pulls all unique hotel-photo UUIDs farvater renders on the page. The
# extractor is intentionally permissive — same UUID appears as `?size=catalog`,
# `?size=detail`, `?size=original` in different DOM positions. We strip the
# query string and dedupe so photos_jsonb stores stable, normalised URLs.
GALLERY_RE = re.compile(
    r'img\d?\.farvater\.travel/hotelimages/([a-f0-9-]{20,})', re.IGNORECASE
)
# JSON-LD `<script type="application/ld+json">{...}</script>` is the canonical
# place farvater emits structured data (description, aggregateRating). We pick
# the first block — it's always the Hotel object.
JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
    re.DOTALL | re.IGNORECASE,
)

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
    photos: list[str]      # all gallery URLs (dedup'd, normalised)
    review_score: float | None  # aggregateRating.ratingValue, 0..10
    review_count: int      # aggregateRating.reviewCount


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
def _name_from_url_path(url_path: str) -> str:
    tail = url_path.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(part.capitalize() for part in tail.split("-") if part)


_BOILERPLATE_SUBSTRINGS = (
    "ціни на відпочинок",
    "ціна на відпочинок",
    "замовити тур",
    "купити тур",
    "тур в готель",
    "гіпермаркет турів",
)

# "5* - Греція", "3* - Таїланд", "4* в Туреччині" — the title cleaner
# strips brand prefixes too aggressively on apartment/villa pages, leaving
# just the rating + country. Bounce these to the URL-slug fallback.
_RATING_ONLY_TITLE_RE = re.compile(r"^[1-5]\*\s*[-—]?\s*[А-ЯҐЄІЇа-яґєії]+$")


def _looks_like_farvater_boilerplate(value: str) -> bool:
    normalized = value.strip().lower()
    if (
        len(normalized) <= 3
        or normalized in {"- farvater travel", "farvater travel"}
        or normalized.startswith("-")
        or normalized.startswith("(ex")
        or normalized.startswith("від farvater")
        or normalized.endswith("farvater travel")
    ):
        return True
    if _RATING_ONLY_TITLE_RE.match(value.strip()):
        return True
    return any(s in normalized for s in _BOILERPLATE_SUBSTRINGS)


_DESC_BOILERPLATE_MARKERS = (
    "гіпермаркет турів",
    "замовити тур",
    "купити тур",
    "фарватер",
    "farvater",
    "❶ціни",
    "❶цени",
    "❷фото",
    "❸отзиви",
    "❸відгуки",
)


def _clean_description(raw: str | None) -> str | None:
    """Drop farvater's meta-description boilerplate.

    The site emits descriptions like
    "🌴 Готель X 4 ★ в Y - замовити тур в готель X. ❶Цени ❷Фото ❸Отзиви туристів.
     Гіпермаркет турів №❶ ☛ Фарватер." — useful to no real user.

    Returns the cleaned text or None when the description is just SEO chum.
    """
    if not raw:
        return None
    text = html.unescape(raw).strip()
    if not text:
        return None
    low = text.lower()
    boilerplate_hits = sum(1 for m in _DESC_BOILERPLATE_MARKERS if m in low)
    if boilerplate_hits >= 2:
        return None
    return text[:1000]


def _clean_title(raw: str, fallback_url_path: str | None = None) -> str:
    """farvater titles look like 'ᐉ Pickalbatros Vita ✈ Ціни ... ☛ Farvater'.
    Pull the hotel-name segment; fall back to the canonical_slug if we strike out.
    """
    # Two unescape passes: HTML rendered with double-escape (&amp;#39;) shows
    # up occasionally in farvater pages. Idempotent on clean text.
    t = html.unescape(html.unescape(re.sub(r'^[ᐉ\s]+', '', raw.strip())))
    m = re.search(r'(?:готель|hotel)\s+(.+)', t, re.IGNORECASE)
    if m:
        t = m.group(1)
    t = re.sub(r'\s*\((?:наприклад|например|example)\b.*$', '', t, flags=re.IGNORECASE)
    for sep in ('✈', '★', '☛', '☆', '·', ' - ', '|', ','):
        i = t.find(sep)
        if i > 3:
            t = t[:i]
    cleaned = t.strip()
    if not _looks_like_farvater_boilerplate(cleaned):
        return cleaned
    if fallback_url_path:
        fallback = _name_from_url_path(fallback_url_path)
        if fallback:
            return fallback
    return cleaned if len(cleaned) > 3 else raw.strip()


def _make_slug(country_iso2: str, url_path: str) -> str:
    tail = url_path.rstrip("/").rsplit("/", 1)[-1]
    return f"fv-{country_iso2.lower()}-{tail}"[:140]


def _extract_gallery(html_text: str) -> list[str]:
    """Pull all unique `img4.farvater.travel/hotelimages/{uuid}` URLs.

    farvater duplicates each UUID at three sizes (catalog/detail/original)
    plus inline `background:url(...)` references. We normalise to a single
    `?size=original` URL per UUID, preserving page order so the og:image
    naturally tends to sort first.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in GALLERY_RE.finditer(html_text):
        uid = m.group(1).lower()
        if uid in seen:
            continue
        seen.add(uid)
        out.append(f"https://img4.farvater.travel/hotelimages/{uid}?size=original")
    return out


def _parse_jsonld(html_text: str) -> dict | None:
    """Best-effort JSON-LD parse. farvater emits one `Hotel` block per page;
    if it parses cleanly we get description + aggregateRating for free.
    Returns None on any error — callers fall through to other signals.
    """
    m = JSONLD_RE.search(html_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _review_from_jsonld(data: dict | None) -> tuple[float | None, int]:
    if not data:
        return (None, 0)
    agg = data.get("aggregateRating") or {}
    try:
        score_raw = agg.get("ratingValue")
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None
    try:
        count = int(agg.get("reviewCount") or 0)
    except (TypeError, ValueError):
        count = 0
    if score is not None and not (0 <= score <= 10):
        score = None
    return (score, count)


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


# Sitemap index — has 9 hotel-page shards × ~50k URLs each ≈ 420k total.
# The /uk/hotelscatalog/strana-X/ page only exposes farvater's curated
# top ~67 per country, so the sitemap is the only way to reach the long tail.
SITEMAP_INDEX_URL = "https://farvater.travel/sitemap.xml"
_SHARD_RE = re.compile(r"<loc>(https://farvater\.travel/[^<]*sitemap-hotelpages-\d+\.xml)</loc>")
_HOTEL_LOC_RE = re.compile(
    r"<loc>https://farvater\.travel(/uk/hotel/([a-z]{2,3})/[a-z0-9-]+/)</loc>",
    re.IGNORECASE,
)


async def _list_sitemap_hotels(
    client: httpx.AsyncClient, iso2_filter: set[str] | None = None,
) -> dict[str, list[str]]:
    """Return `{iso2: [url_path, ...]}` from farvater's hotelpages sitemap.

    Pass `iso2_filter` (uppercase) to keep only countries you care about.
    The sitemap holds ~420k URLs across 9 shards; without a filter you'll
    cap RAM somewhere awful and burn an afternoon. Defaults to *all* — the
    caller must opt out explicitly.
    """
    idx = await client.get(
        SITEMAP_INDEX_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    idx.raise_for_status()
    shards = _SHARD_RE.findall(idx.text)
    log.info("farvater.sitemap.shards_found", count=len(shards))

    by_iso: dict[str, list[str]] = {}
    seen: set[str] = set()
    for shard_url in shards:
        try:
            r = await client.get(
                shard_url,
                headers={"User-Agent": USER_AGENT},
                timeout=60,
            )
            r.raise_for_status()
        except Exception as exc:
            log.warning("farvater.sitemap.shard_failed", url=shard_url, error=str(exc))
            continue
        added = 0
        for m in _HOTEL_LOC_RE.finditer(r.text):
            path, iso = m.group(1), m.group(2).upper()
            if iso2_filter and iso not in iso2_filter:
                continue
            if path in seen:
                continue
            seen.add(path)
            by_iso.setdefault(iso, []).append(path)
            added += 1
        log.info("farvater.sitemap.shard_done", url=shard_url, kept=added,
                 cumulative=len(seen))
    return by_iso


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
    page = r.text
    hid = HOTEL_ID_RE.search(page)
    if not hid:
        log.warning("farvater.no_hotel_id_in_html", url=url)
        return None
    title_m = TITLE_RE.search(page)
    desc_m = DESC_RE.search(page)
    img_m = OG_IMG_RE.search(page)
    jsonld = _parse_jsonld(page)
    # Prefer JSON-LD description — it's the real "this hotel is ..."
    # human text farvater editors wrote, not the SEO chum meta tag.
    jsonld_desc = (jsonld or {}).get("description") if jsonld else None
    description = (
        _clean_description(jsonld_desc)
        or _clean_description(desc_m.group(1) if desc_m else None)
        or ""
    )
    gallery = _extract_gallery(page)
    og_url = (img_m.group(1) if img_m else "")[:512]
    # og:image first so the hero photo stays consistent across pages.
    if og_url and og_url not in gallery:
        gallery = [og_url] + gallery
    review_score, review_count = _review_from_jsonld(jsonld)
    return HotelMeta(
        hotel_id=int(hid.group(1)),
        url_path=url_path.rstrip("/"),
        name=_clean_title(title_m.group(1), url_path) if title_m else _name_from_url_path(url_path),
        country_iso2=iso2,
        photo_url=og_url,
        description=description,
        stars=_extract_stars(page),
        photos=gallery[:30],   # cap so a future site rewrite can't blow up the row
        review_score=review_score,
        review_count=review_count,
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
    new_photos_list = [{"url": u, "alt": hotel.name} for u in hotel.photos]
    # Fall back to single og:image when gallery extraction yielded nothing
    # — better that than wiping a previously-extracted gallery on a transient
    # regex miss.
    if not new_photos_list and hotel.photo_url:
        new_photos_list = [{"url": hotel.photo_url, "alt": hotel.name}]
    new_photos = json.dumps(new_photos_list) if new_photos_list else None

    if existing:
        # All extracted-from-HTML fields are *monotonic*: a one-off regex miss
        # on a future page render must never wipe a value we previously had.
        # We send NULL for fields we couldn't extract this run; the SQL uses
        # COALESCE so existing non-empty values win over fresh empties.
        new_desc = hotel.description if hotel.description else None
        new_name = hotel.name if (hotel.name and len(hotel.name) > 3) else None
        # photos_jsonb: only overwrite when the new pull is at least as wide
        # as what's stored. A one-photo run shouldn't clobber a 20-photo
        # gallery we already have on file.
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
                "p": new_photos,
                "d": new_desc,
                "stars": hotel.stars,
                "rs": hotel.review_score,
                "rc": hotel.review_count,
            },
        )
        return existing[0]

    row = (await db.execute(
        text("""INSERT INTO hotels (
                  canonical_slug, name_uk, name_en, stars, destination_id,
                  description_uk, photos_jsonb, amenities, review_score,
                  review_count, is_active, last_seen_at, last_updated)
                VALUES (:slug, :n, :n, :stars, :dest, :d, CAST(:p AS jsonb),
                        '{}', :rs, :rc, TRUE, NOW(), NOW())
                RETURNING id"""),
        {"slug": slug, "n": hotel.name, "stars": hotel.stars, "dest": dest_id,
         "d": hotel.description, "p": new_photos or "[]",
         "rs": hotel.review_score, "rc": hotel.review_count},
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
            # `?q=<systemKey>` is farvater's internal booking-preselect
            # param — discovered via tools/explore/explore_price_grid.py:
            # every price cell in farvater's own grid is
            # `<a href=".../?q=2m...c25">`. We previously used `?systemKey=`
            # which farvater silently ignored, leaving the user on the
            # generic hotel page instead of the per-operator offer.
            "dl": f"{deep_link_base}?q={r.system_key}",
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


_PRICE_REFRESH_TARGETS_SQL = text(
    """
    -- Daily-price-refresh source. Picks every priced hotel + a thin slice
    -- of unpriced ones for re-probing. Iterating /hotelscatalog/strana-X/
    -- would only cover farvater's curated top ~67 per country — after the
    -- sitemap ingest landed we have ~4-5k priced hotels that the curated
    -- page never mentions.
    --
    -- Ordering:
    --   1. has_active_prices=true first (refresh what users actually see)
    --   2. then the oldest-last-priced cohort (re-probe candidates that
    --      went quiet — farvater may have new inventory)
    --   3. unpriced hotels last, capped per country so a never-priced
    --      backlog can't starve the priced-cohort refresh
    SELECT
        h.id,
        h.canonical_slug,
        d.country_iso2,
        COALESCE(hom.external_id, '') AS external_id,
        h.has_active_prices,
        h.last_priced_at
    FROM hotels h
    JOIN destinations d ON d.id = h.destination_id
    LEFT JOIN hotel_operator_mapping hom
           ON hom.hotel_id = h.id
          AND hom.operator_id =
              (SELECT id FROM operators WHERE code = 'farvater')
    WHERE h.is_active
      AND d.country_iso2 = ANY(:iso_filter)
    ORDER BY
      h.has_active_prices DESC NULLS LAST,
      h.last_priced_at NULLS LAST,
      h.id
    """
)


def _path_from_slug(slug: str) -> str | None:
    parts = slug.split("-", 2)
    if len(parts) != 3 or parts[0] != "fv":
        return None
    return f"/uk/hotel/{parts[1]}/{parts[2]}/"


async def _refresh_targets(
    db: AsyncSession,
    iso_filter: list[str],
    max_per_country: int | None,
) -> list[tuple[str, str, int, str]]:
    """Return list of (url_path, iso2, hotel_db_id, external_id) tuples in
    refresh-priority order. `max_per_country` caps per-iso2 to keep a long
    backlog of unpriced hotels from monopolising a single run."""
    rows = (
        await db.execute(_PRICE_REFRESH_TARGETS_SQL, {"iso_filter": iso_filter})
    ).all()
    out: list[tuple[str, str, int, str]] = []
    per_country: dict[str, int] = {}
    for row in rows:
        iso2 = (row.country_iso2 or "").upper()
        if max_per_country is not None and per_country.get(iso2, 0) >= max_per_country:
            continue
        path = _path_from_slug(row.canonical_slug)
        if not path:
            continue
        out.append((path, iso2, row.id, row.external_id or ""))
        per_country[iso2] = per_country.get(iso2, 0) + 1
    return out


async def snapshot_farvater(*, max_hotels_per_country: int | None = None) -> int:
    """Top-level entrypoint. Returns total rows inserted.

    Drives the refresh from the `hotels` table (priced cohort first, then
    long tail), not from farvater's curated catalog page. See
    `_PRICE_REFRESH_TARGETS_SQL` for the ordering rationale.

    Args:
      max_hotels_per_country: optional cap for dev/testing; None = all
        active+catalogued hotels.
    """
    started_at = datetime.now(UTC)
    iso_filter = [iso2 for _, iso2 in CATALOG_COUNTRIES]
    log.info("farvater.snapshot.start",
             countries=len(CATALOG_COUNTRIES),
             concurrency=CONCURRENCY,
             max_per_country=max_hotels_per_country)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    total_inserted = 0

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    try:
        async with async_session_factory() as db:
            targets = await _refresh_targets(db, iso_filter, max_hotels_per_country)

        # Group by country for logging only — execution stays flat so a
        # single asyncio.gather can saturate the semaphore across countries.
        by_country: dict[str, int] = {}
        for _, iso2, _, _ in targets:
            by_country[iso2] = by_country.get(iso2, 0) + 1
        log.info("farvater.snapshot.targets",
                 total=len(targets), by_country=by_country)

        async with _http_client() as client:
            # Resolve dest_id once per country to avoid round-trips per task.
            dest_ids: dict[str, int | None] = {}
            async with async_session_factory() as db:
                for iso2 in by_country:
                    dest_ids[iso2] = await _country_dest_id(db, iso2)

            tasks = [
                _process_hotel(client, path, iso2, operator_id,
                                dest_ids.get(iso2), semaphore)
                for path, iso2, _, _ in targets
            ]
            # Batch the gather so a 5 000-coroutine pile doesn't sit on
            # the event loop. Each chunk also gives us periodic progress.
            chunk = 200
            for i in range(0, len(tasks), chunk):
                results = await asyncio.gather(
                    *tasks[i:i + chunk], return_exceptions=True
                )
                inserted = sum(r for r in results if isinstance(r, int))
                errors = sum(1 for r in results if isinstance(r, Exception))
                total_inserted += inserted
                log.info("farvater.snapshot.progress",
                         processed=i + len(results), of=len(tasks),
                         inserted=inserted, errors=errors,
                         cumulative_inserted=total_inserted)

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
