"""Helpers for public FastTravel web URLs used outside the web app."""

from __future__ import annotations

from urllib.parse import quote, urlencode


def _base_url(public_site_url: str | None) -> str | None:
    if not public_site_url:
        return None
    return public_site_url.strip().rstrip("/")


def public_hotel_url(
    public_site_url: str | None,
    slug: str | None,
    *,
    source: str = "tg_bot",
    medium: str | None = None,
) -> str | None:
    base = _base_url(public_site_url)
    slug_segment = (slug or "").strip()
    if not base or not slug_segment:
        return None

    url = f"{base}/hotels/{quote(slug_segment, safe='')}"
    query: dict[str, str] = {}
    if source:
        query["utm_source"] = source
    if medium:
        query["utm_medium"] = medium
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def public_destination_url(
    public_site_url: str | None,
    country_iso2: str | None,
    *,
    source: str = "tg_bot",
) -> str | None:
    base = _base_url(public_site_url)
    country = (country_iso2 or "").strip().lower()
    if not base or not country:
        return None

    url = f"{base}/destinations/{quote(country, safe='')}"
    if source:
        url = f"{url}?{urlencode({'utm_source': source})}"
    return url
