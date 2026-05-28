"""farvater `/uk/catalog/static-tours` client + parser.

This is the endpoint the 2026-05-25 HAR investigation identified as the
canonical carrier of operator-flagged promotion signals. It is NOT the
same as the calendar endpoint that `snapshot_farvater` already calls —
the calendar carries pricing only, no flags.

Schema (per HAR snapshot 2026-05-25):

Request — `POST https://farvater.travel/uk/catalog/static-tours`
JSON body fields used:
  - slugTypes:    list[str]   — promo bucket(s), e.g. ["gorjashhie-tury"]
  - countryId:    int         — -1 = all, or specific countryID
  - pageSize:     int         — observed up to 50
  - pageIndex:    int         — 1-based
  - adults:       int         — usually 2
  - checkinList:  list[{From, To}]  — ISO datetime strings
  - (many other fields — see HAR; we only send the ones farvater honours)

Response — `data.tourPackage.tours[]` where each row carries:
  - hotelKey: str            — joins to hotels via hotel_operator_mapping
  - SystemKey: str           — joins to price_observations.deep_link `?q=`
  - isHot, isPromo, isEarly, isBestDeal, isVip, isRecommended,
    IsChoiceFarvater, isOtp, isLastSeats, IsBlackFriday: bool
  - HotType, EarlyType, RecommendedType: int    — type modifiers
  - priceUAH: int, redPriceUAH: int             — pricing
  - operatorName: str, operatorIdInt: int
  - LoadedDate: ISO datetime
  - promotionEndDate: ISO datetime | null
  - checkIn.value: ISO datetime, nights: int, meal.value: localised str
  - countryName, region.RegionName, region.ResortName, hotel.value

The parser canonicalises to a `PromoTourRow` dataclass which mirrors
the `promo_offers` table (migration 012). Validation reuses
`validate_price_row` from Sprint 0.4 so bucket-fetched rows get the
same 0-price / empty-systemKey guard as calendar rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from src.infra.farvater_http import FarvaterProdClient
from src.infra.logging import get_logger

# Reject reasons — same vocabulary as src.jobs._price_validation. Inlined
# here to break the circular import that arises when src.clients is
# pulled in by src.jobs.static_tours_sweep at module load.
REJECT_NON_POSITIVE_PRICE = "non_positive_price"
REJECT_EMPTY_SYSTEM_KEY = "empty_system_key"

log = get_logger(__name__)


STATIC_TOURS_URL = "https://farvater.travel/uk/catalog/static-tours"

# Buckets the May 2026 audit confirmed exist on farvater. New buckets
# can be added without code changes — they are passed as `slugTypes`.
SUPPORTED_BUCKETS = (
    "gorjashhie-tury",  # hot tours — `isHot` always True
    "rannee-bronirovanie",  # early-booking — `isEarly` always True
    "akcionnye-tury",  # generic action / promo
)

# Country IDs farvater uses internally. -1 = all countries (returns a
# mixed-bag response, useful for first-pass discovery).
COUNTRY_ID_ALL = -1
COUNTRY_ID_TURKEY = 83
COUNTRY_ID_EGYPT = 31
COUNTRY_ID_GREECE = 25


# Map farvater's localised meal strings to our 8-char canonical codes.
# Matches the meal_plan column width in promo_offers/price_observations
# and the values snapshot_farvater already writes.
_MEAL_CANON: dict[str, str] = {
    "сніданок (bb)": "BB",
    "bed and breakfast": "BB",
    "сніданок": "BB",
    "напівпансіон (hb)": "HB",
    "half board": "HB",
    "повний пансіон (fb)": "FB",
    "full board": "FB",
    "все включено (ai)": "AI",
    "all inclusive": "AI",
    "ультра все включено (uai)": "UAI",
    "ultra all inclusive": "UAI",
    "без харчування (ro)": "RO",
    "room only": "RO",
    "без харчування": "RO",
}


def _canonical_meal(raw: str | None) -> str:
    if not raw:
        return "OTHER"
    key = raw.strip().lower()
    exact = _MEAL_CANON.get(key)
    if exact:
        return exact[:16]
    match = re.search(r"\b(UAI|AI|HB|BB|FB|RO)\b", key.upper())
    return match.group(1) if match else "OTHER"


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_iso_date(raw: str | None) -> date | None:
    dt = _parse_iso(raw)
    return dt.date() if dt else None


@dataclass
class PromoTourRow:
    """One row of `data.tourPackage.tours[]` normalised for `promo_offers`.

    `raw` is the unmodified upstream dict — kept so the `static_tours_sweep`
    job can persist it into `promo_offers.raw_payload` for forensics.
    """

    bucket_slug: str
    hotel_key: int
    system_key: str
    check_in: date
    nights: int
    meal_plan: str
    price_uah: int
    red_price_uah: int | None
    is_hot: bool
    is_early: bool
    is_best_deal: bool
    is_recommended: bool
    is_choice_farvater: bool
    is_otp: bool
    is_last_seats: bool
    is_black_friday: bool
    is_vip: bool
    hot_type: str | None
    early_type: str | None
    operator_name: str | None
    operator_id_int: int | None
    promotion_end_date: date | None
    loaded_date: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StaticToursPage:
    """Parsed page from the static-tours response.

    `total_items` lets the caller decide whether to paginate further.
    `tours` is already validated and ready to upsert into `promo_offers`.
    """

    bucket_slug: str
    page_index: int
    total_items: int
    tours: list[PromoTourRow]


def _validate(d: dict[str, Any]) -> tuple[bool, str | None]:
    """Local validator — same rules as `validate_price_row` but adapted
    to the static-tours field names (priceUAH same; SystemKey vs systemKey)."""
    try:
        price = int(d.get("priceUAH") or 0)
    except (TypeError, ValueError):
        return False, REJECT_NON_POSITIVE_PRICE
    if price <= 0:
        return False, REJECT_NON_POSITIVE_PRICE
    sk = str(d.get("SystemKey") or "").strip()
    if not sk:
        return False, REJECT_EMPTY_SYSTEM_KEY
    return True, None


def parse_response(
    payload: dict[str, Any],
    *,
    bucket_slug: str,
    page_index: int = 1,
) -> StaticToursPage:
    """Parse a `/uk/catalog/static-tours` JSON body into a `StaticToursPage`.

    Drops rows that fail validation (logs each rejection so a regression
    in upstream's schema is visible in operator logs).
    """
    if payload.get("statusCode") != 200:
        log.warning(
            "static_tours.bad_status",
            bucket=bucket_slug,
            status_code=payload.get("statusCode"),
        )
        return StaticToursPage(bucket_slug, page_index, total_items=0, tours=[])

    package = payload.get("data", {}).get("tourPackage", {}) or {}
    raw_tours: list[dict[str, Any]] = package.get("tours", []) or []
    total_items = int(package.get("totalItems") or 0)

    out: list[PromoTourRow] = []
    for raw in raw_tours:
        ok, reason = _validate(raw)
        if not ok:
            log.warning(
                "static_tours.row_rejected",
                bucket=bucket_slug,
                reason=reason,
                hotel_key=raw.get("hotelKey"),
            )
            continue

        check_in_dt = _parse_iso((raw.get("checkIn") or {}).get("value"))
        if check_in_dt is None:
            log.warning(
                "static_tours.row_rejected",
                bucket=bucket_slug,
                reason="bad_check_in",
                hotel_key=raw.get("hotelKey"),
            )
            continue

        try:
            hotel_key = int(raw.get("hotelKey") or raw.get("hotelId") or 0)
        except (TypeError, ValueError):
            log.warning(
                "static_tours.row_rejected",
                bucket=bucket_slug,
                reason="bad_hotel_key",
            )
            continue
        if hotel_key <= 0:
            continue

        out.append(
            PromoTourRow(
                bucket_slug=bucket_slug,
                hotel_key=hotel_key,
                system_key=str(raw["SystemKey"]).strip(),
                check_in=check_in_dt.date(),
                nights=int(raw.get("nights") or 0),
                meal_plan=_canonical_meal((raw.get("meal") or {}).get("value")),
                price_uah=int(raw["priceUAH"]),
                red_price_uah=int(raw["redPriceUAH"]) if raw.get("redPriceUAH") else None,
                is_hot=bool(raw.get("isHot")),
                is_early=bool(raw.get("isEarly")),
                is_best_deal=bool(raw.get("isBestDeal")),
                is_recommended=bool(raw.get("isRecommended")),
                is_choice_farvater=bool(raw.get("IsChoiceFarvater")),
                is_otp=bool(raw.get("isOtp")),
                is_last_seats=bool(raw.get("isLastSeats")),
                is_black_friday=bool(raw.get("IsBlackFriday")),
                is_vip=bool(raw.get("isVip")),
                hot_type=str(raw["HotType"]) if raw.get("HotType") else None,
                early_type=str(raw["EarlyType"]) if raw.get("EarlyType") else None,
                operator_name=raw.get("operatorName"),
                operator_id_int=raw.get("operatorIdInt"),
                promotion_end_date=_parse_iso_date(raw.get("promotionEndDate")),
                loaded_date=_parse_iso(raw.get("LoadedDate")),
                raw=raw,
            )
        )

    return StaticToursPage(
        bucket_slug=bucket_slug,
        page_index=page_index,
        total_items=total_items,
        tours=out,
    )


def build_request_body(
    *,
    bucket_slug: str,
    country_id: int = COUNTRY_ID_ALL,
    page_index: int = 1,
    page_size: int = 50,
    adults: int = 2,
    check_in_from: date | None = None,
    check_in_to: date | None = None,
) -> dict[str, Any]:
    """Construct the request body verbatim per the HAR snapshot.

    `check_in_from` / `check_in_to` default to today → today+30d, which
    matches what `V4SEOcatalog.js` sends on a cold page load. Callers
    can widen the window for backfill runs.
    """
    today = datetime.now(UTC).date()
    cif = check_in_from or today
    cit = check_in_to or today.replace(day=1).replace(month=today.month)
    # Default the upper bound to +30 days from today.
    if check_in_to is None:
        from datetime import timedelta

        cit = today + timedelta(days=30)

    return {
        "nightFrom": 0,
        "nightTo": 0,
        "slugTypes": [bucket_slug],
        "countryId": country_id,
        "starIDs": [],
        "meals": [],
        "adults": adults,
        "kids": 0,
        "ages": [],
        "hotels": [],
        "resorts": [],
        "airportList": [],
        "operatorIdList": [],
        "checkinList": [
            {
                "From": f"{cif.isoformat()}T00:00:00+03:00",
                "To": f"{cit.isoformat()}T00:00:00+03:00",
            }
        ],
        "pageSize": page_size,
        "pageIndex": page_index,
        "descByPrice": False,
    }


async def fetch_bucket_page(
    client: FarvaterProdClient,
    *,
    bucket_slug: str,
    country_id: int = COUNTRY_ID_ALL,
    page_index: int = 1,
    page_size: int = 50,
    check_in_from: date | None = None,
    check_in_to: date | None = None,
) -> StaticToursPage:
    """Fetch a single page of `static-tours` for `(bucket_slug, country_id)`.

    Raises whatever `FarvaterProdClient.post_json` raises (BreakerOpen /
    DailyCapHit / UpstreamRateLimited / httpx.HTTPStatusError) — callers
    decide whether to swallow or escalate.
    """
    if bucket_slug not in SUPPORTED_BUCKETS:
        log.warning("static_tours.unknown_bucket", bucket=bucket_slug)

    body = build_request_body(
        bucket_slug=bucket_slug,
        country_id=country_id,
        page_index=page_index,
        page_size=page_size,
        check_in_from=check_in_from,
        check_in_to=check_in_to,
    )
    payload = await client.post_json(
        STATIC_TOURS_URL,
        json=body,
        extra_headers={
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://farvater.travel/uk/",
            "Origin": "https://farvater.travel",
        },
    )
    return parse_response(payload, bucket_slug=bucket_slug, page_index=page_index)


async def fetch_bucket_all_pages(
    client: FarvaterProdClient,
    *,
    bucket_slug: str,
    country_id: int = COUNTRY_ID_ALL,
    page_size: int = 50,
    max_pages: int = 20,
    check_in_from: date | None = None,
    check_in_to: date | None = None,
) -> list[PromoTourRow]:
    """Walk all pages for `(bucket_slug, country_id)` up to `max_pages`.

    Uses `total_items` from the first page to stop early once we've
    seen everything. `max_pages` is a hard cap so a misreporting upstream
    can't pull us into an infinite loop.
    """
    first = await fetch_bucket_page(
        client,
        bucket_slug=bucket_slug,
        country_id=country_id,
        page_index=1,
        page_size=page_size,
        check_in_from=check_in_from,
        check_in_to=check_in_to,
    )
    collected = list(first.tours)
    if first.total_items <= page_size or not first.tours:
        return collected

    total_pages = min(max_pages, -(-first.total_items // page_size))
    for page_index in range(2, total_pages + 1):
        page = await fetch_bucket_page(
            client,
            bucket_slug=bucket_slug,
            country_id=country_id,
            page_index=page_index,
            page_size=page_size,
            check_in_from=check_in_from,
            check_in_to=check_in_to,
        )
        if not page.tours:
            break
        collected.extend(page.tours)
    return collected
