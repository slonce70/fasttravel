"""ittour `/search/results` offer JSON → NormalizedOffer.

Field-name assumptions live HERE in one place so that, when the real
docs land, a single edit per field is enough. Every assumed key is
flagged with `# DOC` in a comment.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.normalizers.base import NormalizedOffer, normalize_meal_plan

_log = structlog.get_logger("normalizers.ittour")


def _to_int_price(v: Any) -> int | None:
    """Coerce price → int UAH (whole). Accept int, float, str. Return None
    on garbage so the caller can skip + warn."""
    if v is None:
        return None
    if isinstance(v, bool):  # bool is subclass of int, guard explicitly
        return None
    if isinstance(v, int | float):
        return int(round(v))
    if isinstance(v, str):
        try:
            return int(round(float(v.replace(",", "").replace(" ", ""))))
        except ValueError:
            return None
    return None


def _to_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        # Accept both ISO and YYYY-MM-DD (covered by fromisoformat)
        try:
            return datetime.fromisoformat(v).date()
        except ValueError:
            return None
    return None


def normalize_offer(raw: dict[str, Any], *, operator_code: str) -> NormalizedOffer | None:
    """Convert one offer dict to a NormalizedOffer. Returns None on soft skip.

    Soft skip = malformed but non-fatal: missing price, unparseable date.
    Hard skip would raise — we don't, because a single bad row should
    never kill the whole snapshot.
    """
    hotel_external_id = str(raw.get("hotel_id") or raw.get("hotelId") or "").strip()  # DOC
    if not hotel_external_id:
        _log.warn("offer_missing_hotel_id", raw_keys=list(raw.keys()))
        return None

    check_in = _to_date(raw.get("check_in") or raw.get("dateFrom"))  # DOC
    if check_in is None:
        _log.warn("offer_missing_or_bad_check_in", hotel=hotel_external_id)
        return None

    nights = raw.get("nights") or raw.get("duration")  # DOC
    if not isinstance(nights, int) or nights <= 0:
        _log.warn("offer_missing_nights", hotel=hotel_external_id)
        return None

    price_uah = _to_int_price(raw.get("price_uah") or raw.get("priceUAH"))  # DOC
    if price_uah is None or price_uah <= 0:
        _log.warn("offer_missing_price_uah", hotel=hotel_external_id)
        return None

    price_original_raw = raw.get("price_original") or raw.get("priceOriginal")
    price_original = _to_int_price(price_original_raw)
    if price_original is None:
        # Fall back to price_uah — the deal-detection layer doesn't depend
        # on price_original; it's only kept for audit/UX.
        price_original = price_uah

    currency = (raw.get("currency") or "").strip().upper()
    if not currency:
        _log.warn("offer_missing_currency_assume_usd", hotel=hotel_external_id)
        currency = "USD"
    if len(currency) != 3:
        _log.warn("offer_bad_currency_assume_usd", hotel=hotel_external_id, raw=currency)
        currency = "USD"

    fx_rate_raw = raw.get("fx_rate_to_uah") or raw.get("fxRate") or 1
    try:
        fx_rate = Decimal(str(fx_rate_raw))
    except Exception:
        fx_rate = Decimal("1")

    meal_plan = normalize_meal_plan(raw.get("meal_plan") or raw.get("meal"))

    deep_link = str(raw.get("deep_link") or raw.get("link") or "").strip()
    if not deep_link:
        _log.warn("offer_missing_deep_link", hotel=hotel_external_id)
        # We still produce the offer — deep_link is nullable in the schema
        # (`deep_link TEXT, nullable`) but the dedup fingerprint then loses
        # one input; that's OK because (hotel, op, date, nights, meal,
        # price) still uniquely identifies the row.

    return NormalizedOffer(
        hotel_external_id=hotel_external_id,
        operator_code=operator_code,
        check_in=check_in,
        nights=int(nights),
        meal_plan=meal_plan,
        room_category=raw.get("room_category"),
        adults=int(raw.get("adults") or 2),
        departure_city=raw.get("departure_city"),
        price_uah=price_uah,
        price_original=price_original,
        currency=currency,
        fx_rate_to_uah=fx_rate,
        deep_link=deep_link,
        raw_payload=raw,
    )


def parse_search_response(
    raw_offers: list[dict[str, Any]],
    fallback_hotel_external_id: str,
) -> list[NormalizedOffer]:
    offers: list[NormalizedOffer] = []
    for raw in raw_offers:
        normalized_raw = dict(raw)
        normalized_raw.setdefault("hotel_id", fallback_hotel_external_id)
        offer = normalize_offer(normalized_raw, operator_code="ittour")
        if offer is not None:
            offers.append(offer)
    return offers
