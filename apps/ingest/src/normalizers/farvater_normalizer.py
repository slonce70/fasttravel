"""Normalizer for farvater HTML pages and (eventually) XHR responses.

Farvater is the bootstrap source — its data shape is intentionally
not stable, because we'll replace it with ittour direct as soon as
the partner token arrives.

What this module currently does:
  * `parse_hotel_card_html(html)` → NormalizedHotelContent (best-effort
    metadata extraction from a public hotel landing page)
  * `parse_calendar_xhr(payload)` — STUB; raises NotImplementedError
    until we capture the real XHR shape via DevTools HAR

What this module deliberately does NOT do:
  * Render JavaScript. If the data isn't in the static HTML, the
    bootstrap source can't help us — we need ittour direct.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from selectolax.parser import HTMLParser

from src.normalizers.base import NormalizedHotelContent, NormalizedOffer


def parse_hotel_card_html(html: str) -> NormalizedHotelContent | None:
    """Best-effort scrape of basic hotel metadata from a farvater landing.

    Returns None if the page doesn't look like a hotel page (404, captcha,
    redirect to search). Caller logs the miss.

    NB: selectors below are hypothetical until HAR analysis is done.
    The structure of the function is correct; the CSS paths will need
    tweaking on first real run.
    """
    tree = HTMLParser(html)
    name_node = tree.css_first("h1.hotel__title, h1[itemprop='name']")
    if name_node is None:
        return None

    name = name_node.text(strip=True)
    if not name:
        return None

    stars = _extract_stars(tree)
    photos = _extract_photo_urls(tree)
    description = _extract_description(tree)
    review_score, review_count = _extract_review_stats(tree)

    return NormalizedHotelContent(
        external_id="",  # caller fills in from the URL slug → mapping table
        name=name,
        stars=stars,
        coords=None,  # not currently extracted; ittour has it natively
        photos=photos,
        description=description,
        amenities=[],
        review_score=review_score,
        review_count=review_count,
    )


def parse_calendar_xhr(payload: dict[str, Any]) -> list[NormalizedOffer]:
    """Return list[NormalizedOffer] from Farvater's private calendar payload.

    The generic ingest package does not yet know Farvater's private XHR
    shape; production prices currently come from scheduler snapshot jobs.
    Once a HAR capture pins this endpoint, the function should look roughly
    like:

        offers = []
        for entry in payload["data"]["calendar"]:
            for op in entry["operators"]:
                offers.append(NormalizedOffer(
                    hotel_external_id=str(payload["hotelId"]),
                    operator_code=_OPERATOR_ID_TO_CODE[op["operatorId"]],
                    check_in=date.fromisoformat(entry["date"]),
                    nights=op["nights"],
                    meal_plan=normalize_meal_plan(op["meal"]),
                    price_uah=int(op["priceUah"]),
                    ...
                ))
        return offers
    """
    raise NotImplementedError(
        "farvater calendar XHR shape unknown for generic ingest — "
        "production Farvater prices are handled by scheduler snapshots"
    )


# ---------------------------------------------------------------------------
# Internal helpers — selectolax CSS queries, all defensive.
# ---------------------------------------------------------------------------


def _extract_stars(tree: HTMLParser) -> int | None:
    # Two common patterns: explicit data attribute, or N-star icons.
    node = tree.css_first("[data-hotel-stars]")
    if node is not None:
        raw = node.attributes.get("data-hotel-stars")
        if raw and raw.isdigit():
            return int(raw)
    icons = tree.css(".hotel__stars i, .hotel-stars__icon")
    if icons:
        return len(icons)
    return None


def _extract_photo_urls(tree: HTMLParser) -> list[str]:
    urls: list[str] = []
    for node in tree.css(".hotel__gallery img, [itemprop='photo']"):
        src = node.attributes.get("src") or node.attributes.get("data-src")
        if src and src.startswith(("http", "//")):
            urls.append(src if src.startswith("http") else f"https:{src}")
    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique[:10]


def _extract_description(tree: HTMLParser) -> str | None:
    node = tree.css_first(".hotel__description, [itemprop='description']")
    return node.text(strip=True)[:2000] if node else None


def _extract_review_stats(tree: HTMLParser) -> tuple[float | None, int | None]:
    score_node = tree.css_first("[itemprop='ratingValue']")
    count_node = tree.css_first("[itemprop='reviewCount']")
    score = None
    count = None
    if score_node is not None:
        with suppress(ValueError):
            score = float(score_node.text(strip=True).replace(",", "."))
    if count_node is not None:
        with suppress(ValueError):
            count = int("".join(c for c in count_node.text() if c.isdigit()))
    return score, count
