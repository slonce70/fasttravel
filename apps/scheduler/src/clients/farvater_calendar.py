"""Farvater low-price calendar client."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from src.infra.logging import get_logger
from src.services.price_insert import PriceRow
from src.services.price_validation import parse_check_in, validate_price_row

log = get_logger(__name__)

DEFAULT_USER_AGENT = (
    "FastTravel-Bot/1.0 (+https://fasttravel.com.ua/about; snapshot 2x/day; respects robots.txt)"
)
CALENDAR_DATE_SHIFT_DAYS = 60
NIGHTS = [7, 8, 9, 10, 11, 12, 13, 14]


class FarvaterCalendarTransientError(RuntimeError):
    """Raised when the calendar endpoint failed before returning usable inventory data."""


class FarvaterCalendarClient(Protocol):
    async def post_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        json: dict[str, Any],
        extra_headers: dict[str, str],
    ) -> dict[str, Any]: ...


async def fetch_calendar(
    client: FarvaterCalendarClient,
    hotel_id: int,
    check_in: date,
    *,
    date_shift_days: int = CALENDAR_DATE_SHIFT_DAYS,
    nights: Sequence[int] = NIGHTS,
    user_agent: str = DEFAULT_USER_AGENT,
    payload_source: str = "farvater_scrape",
    payload_hotel_key: int | str | None = None,
) -> list[PriceRow]:
    url = "https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
    requested_nights = list(nights)
    params = {
        "hotelKey": hotel_id,
        "adults": 2,
        "ages": 0,
        "meals": "all",
        "checkIn": check_in.strftime("%d.%m.%Y"),
    }
    body = {"dateShift": date_shift_days, "nights": requested_nights, "townFroms": "all"}
    try:
        payload = await client.post_json(
            url,
            params=params,
            json=body,
            extra_headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    except Exception as exc:
        log.warning("farvater.calendar_fetch_failed", hotel_id=hotel_id, error=str(exc))
        raise FarvaterCalendarTransientError(
            f"transient Farvater calendar fetch failed for hotel {hotel_id}"
        ) from exc
    if payload.get("statusCode") != 200:
        log.warning(
            "farvater.calendar_bad_status",
            hotel_id=hotel_id,
            status_code=payload.get("statusCode"),
        )
        raise FarvaterCalendarTransientError(
            f"transient Farvater calendar status {payload.get('statusCode')} for hotel {hotel_id}"
        )
    out: list[PriceRow] = []
    for wrapper in payload["data"]["items"]:
        item = wrapper["item"]
        calendar_nights = int(item["night"])
        for offer in item["dates"]:
            ok, reason = validate_price_row(offer)
            if not ok:
                log.warning(
                    "farvater.calendar_row_rejected",
                    hotel_id=hotel_id,
                    reason=reason,
                    nights=calendar_nights,
                    raw_date=offer.get("date"),
                )
                try:
                    from src.infra.metrics import SCRAPE_HOTEL_FAILURES

                    SCRAPE_HOTEL_FAILURES.labels(
                        source="farvater_scrape",
                        country="unknown",
                        reason=reason or "unknown",
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass
                continue
            check_date = parse_check_in(offer["date"])
            if check_date is None:
                log.warning(
                    "farvater.calendar_row_bad_date",
                    hotel_id=hotel_id,
                    nights=calendar_nights,
                    raw_date=offer.get("date"),
                )
                continue
            out.append(
                PriceRow(
                    hotel_id=hotel_id,
                    check_in=check_date,
                    nights=calendar_nights,
                    meal_plan=(offer.get("meal") or "OTHER")[:8],
                    room_category=(offer.get("room") or "")[:64],
                    price_uah=int(offer.get("priceUAH") or 0),
                    price_usd=int(offer.get("price") or 0),
                    system_key=str(offer.get("systemKey") or ""),
                    raw_payload={
                        "systemKey": str(offer.get("systemKey") or ""),
                        "source": payload_source,
                        "hotelKey": payload_hotel_key
                        if payload_hotel_key is not None
                        else hotel_id,
                        "requestedCheckIn": check_in.isoformat(),
                        "requestedDateShift": date_shift_days,
                        "requestedNights": requested_nights,
                        "calendarNight": calendar_nights,
                        "offer": offer,
                    },
                )
            )
    return out
