"""Farvater hotel-page metadata client."""

from __future__ import annotations

import re
from typing import Any, Protocol

import httpx

from src.clients import farvater_catalog
from src.clients.farvater_calendar import DEFAULT_USER_AGENT
from src.infra.logging import get_logger
from src.services.hotel_upsert import HotelMeta

log = get_logger(__name__)

HOTEL_ID_RE = re.compile(r"hotelId:(\d+)")
DESC_RE = re.compile(r'<meta name="description" content="([^"]+)"', re.IGNORECASE)
OG_IMG_RE = re.compile(r'<meta property="og:image" content="([^"]+)"', re.IGNORECASE)


class FarvaterHotelPageTransientError(RuntimeError):
    """Raised when a hotel page could not be fetched for a retryable reason."""


class FarvaterHotelPageClient(Protocol):
    async def get_text(
        self,
        url: str,
        *,
        extra_headers: dict[str, str],
    ) -> str: ...


async def fetch_hotel_meta(
    client: FarvaterHotelPageClient,
    url_path: str,
    iso2: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> HotelMeta | None:
    url = f"https://farvater.travel{url_path}"
    try:
        page = await client.get_text(url, extra_headers={"User-Agent": user_agent})
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 404:
            log.info("farvater.hotel_not_found", url=url, status_code=status_code)
        else:
            log.warning(
                "farvater.hotel_fetch_failed",
                url=url,
                status_code=status_code,
                error=str(exc),
            )
            raise FarvaterHotelPageTransientError(
                f"transient Farvater hotel-page fetch failed for {url}"
            ) from exc
        return None
    except Exception as exc:
        log.warning("farvater.hotel_fetch_failed", url=url, error=str(exc))
        raise FarvaterHotelPageTransientError(
            f"transient Farvater hotel-page fetch failed for {url}"
        ) from exc
    hotel_id_match = HOTEL_ID_RE.search(page)
    if not hotel_id_match:
        log.warning("farvater.no_hotel_id_in_html", url=url)
        return None
    desc_match = DESC_RE.search(page)
    image_match = OG_IMG_RE.search(page)
    jsonld = farvater_catalog.parse_jsonld(page)
    jsonld_desc = (jsonld or {}).get("description") if jsonld else None
    description = (
        farvater_catalog.clean_description(cast_str(jsonld_desc))
        or farvater_catalog.clean_description(desc_match.group(1) if desc_match else None)
        or ""
    )
    gallery = farvater_catalog.extract_gallery(page)
    og_url = (image_match.group(1) if image_match else "")[:512]
    if og_url and og_url not in gallery:
        gallery = [og_url, *gallery]
    review_score, review_count = farvater_catalog.review_from_jsonld(jsonld)
    return HotelMeta(
        hotel_id=int(hotel_id_match.group(1)),
        url_path=url_path.rstrip("/"),
        name=farvater_catalog.extract_hotel_name(page, url_path)
        or farvater_catalog.name_from_url_path(url_path),
        country_iso2=iso2,
        photo_url=og_url,
        description=description,
        stars=farvater_catalog.extract_stars(page),
        photos=gallery[:30],
        review_score=review_score,
        review_count=review_count,
    )


def cast_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
