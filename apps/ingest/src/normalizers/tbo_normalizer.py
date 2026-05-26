"""TBO HotelDetails JSON → NormalizedHotelContent.

TBO only ships content (not pricing for UA). The pipeline calls this
once per hotel as a hotel-content refresh — NOT every snapshot.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.normalizers.base import NormalizedHotelContent

_log = structlog.get_logger("normalizers.tbo")


def _parse_coords(payload: dict[str, Any]) -> tuple[float, float] | None:
    """TBO uses 'Latitude'/'Longitude' as strings in some responses, floats
    in others. Defend both shapes; missing → None."""
    lat = payload.get("Latitude")
    lon = payload.get("Longitude")
    if lat is None or lon is None:
        return None
    try:
        return (float(lat), float(lon))
    except (TypeError, ValueError):
        return None


def _parse_photos(payload: dict[str, Any]) -> list[str]:
    """`Images` is documented as list[str] but some payloads return
    list[dict] with {'Url': ...}. Handle both."""
    images = payload.get("Images") or []
    out: list[str] = []
    for img in images:
        if isinstance(img, str):
            out.append(img)
        elif isinstance(img, dict) and "Url" in img:
            out.append(str(img["Url"]))
    return out


def normalize_hotel_details(raw: dict[str, Any]) -> NormalizedHotelContent | None:
    """Extract a single hotel's content. Returns None if the upstream
    Status.Code != 200 or HotelDetails is missing/empty."""
    status = (raw.get("Status") or {}).get("Code")
    if status != 200:
        _log.warn("tbo_non_200_status", status=status)
        return None

    details_list = raw.get("HotelDetails") or []
    if not details_list:
        _log.warn("tbo_empty_hotel_details")
        return None

    h = details_list[0]
    code = h.get("HotelCode") or h.get("Hotelcodes") or h.get("HotelID")
    if not code:
        _log.warn("tbo_missing_hotel_code")
        return None

    return NormalizedHotelContent(
        external_id=str(code),
        name=str(h.get("HotelName") or "").strip() or f"TBO-{code}",
        stars=_parse_stars(h),
        coords=_parse_coords(h),
        photos=_parse_photos(h),
        description=h.get("Description"),
        amenities=list(h.get("HotelFacilities") or []),
        review_score=None,  # TBO doesn't ship review scores in HotelDetails
        review_count=None,
    )


def _parse_stars(payload: dict[str, Any]) -> int | None:
    """TBO sometimes returns 'HotelRating' as int, sometimes as 'FourStar'
    style string. Coerce both, return None on failure."""
    raw = payload.get("HotelRating")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 5 else None
    str_map = {
        "OneStar": 1,
        "TwoStar": 2,
        "ThreeStar": 3,
        "FourStar": 4,
        "FiveStar": 5,
    }
    if isinstance(raw, str) and raw in str_map:
        return str_map[raw]
    try:
        v = int(raw)
        return v if 1 <= v <= 5 else None
    except (TypeError, ValueError):
        return None
