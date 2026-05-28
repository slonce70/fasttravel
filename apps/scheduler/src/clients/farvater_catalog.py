"""Pure Farvater catalog HTML helpers.

These helpers intentionally avoid DB, HTTP, scheduler, and logging concerns.
The snapshot jobs use them to turn farvater hotel/catalog HTML into stable
names, slugs, photos, descriptions, ratings, and star metadata.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from src.infra.logging import get_logger

log = get_logger(__name__)

DEFAULT_USER_AGENT = (
    "FastTravel-Bot/1.0 (+https://fasttravel.com.ua/about; snapshot 2x/day; " "respects robots.txt)"
)

HOTEL_URL_RE = re.compile(r'href="(/uk/hotel/[a-z]{2,3}/[a-z0-9-]+/)"', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
H1_TITLE_RE = re.compile(
    r'<h1[^>]*(?:id="TP__Blocks__TourTitle"|itemprop="name")[^>]*>\s*(.*?)\s*</h1>',
    re.IGNORECASE | re.DOTALL,
)

# Pulls all unique hotel-photo UUIDs farvater renders on the page. The
# extractor is intentionally permissive: same UUID appears as `?size=catalog`,
# `?size=detail`, `?size=original` in different DOM positions. We strip the
# query string and dedupe so photos_jsonb stores stable, normalised URLs.
GALLERY_RE = re.compile(r"img\d?\.farvater\.travel/hotelimages/([a-f0-9-]{20,})", re.IGNORECASE)

# JSON-LD `<script type="application/ld+json">{...}</script>` is the canonical
# place farvater emits structured data (description, aggregateRating). We pick
# the first block; it has been the Hotel object in observed pages.
JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
    re.DOTALL | re.IGNORECASE,
)

# Star rating. Primary signal: JSON-LD `"starRating":{"ratingValue":"N"}`
# (present on most rated farvater hotels). Fallback: H1/title pattern like
# `Sunset 3*` / `Pickalbatros Vita Resort - Portofino 5*` -- digit must be
# preceded by whitespace or `-` and immediately followed by `*` to avoid
# false positives on years / model numbers. Constrained to [1-5] because
# `hotels.stars` carries `CHECK (stars BETWEEN 1 AND 5)`.
STAR_JSONLD_RE = re.compile(
    r'"starRating"\s*:\s*\{[^}]*?"ratingValue"\s*:\s*"?([1-5])"?',
    re.IGNORECASE,
)
STAR_TITLE_RE = re.compile(r"[\s\-]([1-5])\*")

SITEMAP_INDEX_URL = "https://farvater.travel/sitemap.xml"
_SHARD_RE = re.compile(r"<loc>(https://farvater\.travel/[^<]*sitemap-hotelpages-\d+\.xml)</loc>")
_HOTEL_LOC_RE = re.compile(
    r"<loc>https://farvater\.travel(/uk/hotel/([a-z]{2,3})/[a-z0-9-]+/)</loc>",
    re.IGNORECASE,
)

_BOILERPLATE_SUBSTRINGS = (
    "ціни на відпочинок",
    "ціна на відпочинок",
    "замовити тур",
    "купити тур",
    "тур в готель",
    "гіпермаркет турів",
)

# Titles like "5* - Греція", "APP - Таїланд", "VILLA - Кіпр". The cleaner
# strips brand prefixes too aggressively on apartment/villa pages, leaving
# just the rating/type + country. Bounce these to the URL-slug fallback.
_PROPERTY_TYPE_WORDS = (
    "app",
    "hotel",
    "hostel",
    "host",
    "villa",
    "apt",
    "resort",
    "guesthouse",
    "motel",
    "gh",
    "hut",
    "bnb",
    "h/h",
)
_RATING_ONLY_TITLE_RE = re.compile(
    r"^(?:[1-5]\*|" + "|".join(re.escape(w) for w in _PROPERTY_TYPE_WORDS) + r")"
    r"\s*[-—]?\s*[А-ЯҐЄІЇа-яґєії]+$",
    re.IGNORECASE,
)

# After the separator-splitter strips " - Country", we can end up with
# bare property-type words ("VILLA", "APP"). Treat those as boilerplate too.
_BARE_PROPERTY_TYPE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(w) for w in _PROPERTY_TYPE_WORDS) + r")$",
    re.IGNORECASE,
)

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


def name_from_url_path(url_path: str) -> str:
    tail = url_path.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(part.capitalize() for part in tail.split("-") if part)


def looks_like_farvater_boilerplate(value: str) -> bool:
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
    stripped = value.strip()
    if _RATING_ONLY_TITLE_RE.match(stripped):
        return True
    if _BARE_PROPERTY_TYPE_RE.match(stripped):
        return True
    return any(s in normalized for s in _BOILERPLATE_SUBSTRINGS)


def clean_description(raw: str | None) -> str | None:
    """Drop farvater's meta-description boilerplate."""
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


def clean_title(raw: str, fallback_url_path: str | None = None) -> str:
    """Extract the hotel-name segment from farvater's SEO-heavy titles."""
    # Two unescape passes: HTML rendered with double-escape (&amp;#39;) shows
    # up occasionally in farvater pages. Idempotent on clean text.
    t = html.unescape(html.unescape(re.sub(r"^[ᐉ\s]+", "", raw.strip())))
    m = re.match(
        r"^(?:[1-5]\*\s*[-–—]\s*)?"
        r"(?:(?:тури|туры)\s+в\s+(?:готель|отель)|відпочинок\s+в\s+готелі|готель|отель)\s+(.+)$",
        t,
        re.IGNORECASE,
    )
    if m:
        t = m.group(1)
    t = re.sub(r"\s*\((?:наприклад|например|example)\b.*$", "", t, flags=re.IGNORECASE)
    for sep in ("✈", "★", "☛", "☆", "·", " - ", "|", ","):
        i = t.find(sep)
        if i > 3:
            t = t[:i]
    cleaned = t.strip()
    cleaned = re.sub(r"\s+[1-5]\*\s*$", "", cleaned).strip()
    if not looks_like_farvater_boilerplate(cleaned):
        return cleaned
    if fallback_url_path:
        fallback = name_from_url_path(fallback_url_path)
        if fallback:
            return fallback
    return cleaned if len(cleaned) > 3 else raw.strip()


def extract_hotel_name(page: str, fallback_url_path: str | None = None) -> str | None:
    title = TITLE_RE.search(page)
    if title:
        name = clean_title(title.group(1), fallback_url_path)
        if name and not looks_like_farvater_boilerplate(name):
            return name
    h1 = H1_TITLE_RE.search(page)
    if h1:
        raw = re.sub(r"<[^>]+>", " ", h1.group(1))
        name = clean_title(raw, fallback_url_path)
        if name and not looks_like_farvater_boilerplate(name):
            return name
    return name_from_url_path(fallback_url_path) if fallback_url_path else None


def make_slug(country_iso2: str, url_path: str) -> str:
    tail = url_path.rstrip("/").rsplit("/", 1)[-1]
    return f"fv-{country_iso2.lower()}-{tail}"[:140]


def extract_gallery(html_text: str) -> list[str]:
    """Pull all unique `img4.farvater.travel/hotelimages/{uuid}` URLs."""
    seen: set[str] = set()
    out: list[str] = []
    for m in GALLERY_RE.finditer(html_text):
        uid = m.group(1).lower()
        if uid in seen:
            continue
        seen.add(uid)
        out.append(f"https://img4.farvater.travel/hotelimages/{uid}?size=original")
    return out


def parse_jsonld(html_text: str) -> dict[str, Any] | None:
    """Best-effort JSON-LD parse."""
    m = JSONLD_RE.search(html_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def review_from_jsonld(data: dict[str, Any] | None) -> tuple[float | None, int]:
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


def extract_stars(html_text: str) -> int | None:
    """Return 1..5 if a star rating is unambiguous in the page, else None."""
    m = STAR_JSONLD_RE.search(html_text)
    if m:
        return int(m.group(1))
    title = TITLE_RE.search(html_text)
    if title:
        t = STAR_TITLE_RE.search(title.group(1))
        if t:
            return int(t.group(1))
    return None


async def list_country_hotels(
    client: Any,
    country_slug: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    url = f"https://farvater.travel/uk/hotelscatalog/strana-{country_slug}/"
    response = await client.get(url, headers={"User-Agent": user_agent}, timeout=30)
    response.raise_for_status()
    seen: set[str] = set()
    out: list[str] = []
    for match in HOTEL_URL_RE.finditer(response.text):
        path = match.group(1)
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


async def list_sitemap_hotels(
    client: Any,
    iso2_filter: set[str] | None = None,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, list[str]]:
    """Return `{iso2: [url_path, ...]}` from farvater's hotelpages sitemap."""
    index_response = await client.get(
        SITEMAP_INDEX_URL,
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    index_response.raise_for_status()
    shards = _SHARD_RE.findall(index_response.text)
    log.info("farvater.sitemap.shards_found", count=len(shards))

    by_iso: dict[str, list[str]] = {}
    seen: set[str] = set()
    for shard_url in shards:
        try:
            response = await client.get(
                shard_url,
                headers={"User-Agent": user_agent},
                timeout=60,
            )
            response.raise_for_status()
        except Exception as exc:
            log.warning("farvater.sitemap.shard_failed", url=shard_url, error=str(exc))
            continue
        added = 0
        for match in _HOTEL_LOC_RE.finditer(response.text):
            path, iso = match.group(1), match.group(2).upper()
            if iso2_filter and iso not in iso2_filter:
                continue
            if path in seen:
                continue
            seen.add(path)
            by_iso.setdefault(iso, []).append(path)
            added += 1
        log.info("farvater.sitemap.shard_done", url=shard_url, kept=added, cumulative=len(seen))
    return by_iso
