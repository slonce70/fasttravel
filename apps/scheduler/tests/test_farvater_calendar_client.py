from __future__ import annotations

from datetime import date

import pytest

from src.clients.farvater_calendar import NIGHTS, fetch_calendar


async def test_fetch_calendar_preserves_full_farvater_offer_payload() -> None:
    class _FakeClient:
        async def post_json(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "statusCode": 200,
                "data": {
                    "items": [
                        {
                            "item": {
                                "night": 7,
                                "dates": [
                                    {
                                        "date": "15.06.2026",
                                        "meal": "AI",
                                        "room": "Standard Sea View",
                                        "priceUAH": 42500,
                                        "price": 1024,
                                        "systemKey": "2m-full-raw-c42",
                                        "redPriceUAH": 51000,
                                        "isHot": True,
                                    }
                                ],
                            }
                        }
                    ]
                },
            }

    rows = await fetch_calendar(_FakeClient(), 45175, date(2026, 6, 1))

    assert len(rows) == 1
    raw = rows[0].raw_payload
    assert raw["systemKey"] == "2m-full-raw-c42"
    assert raw["source"] == "farvater_scrape"
    assert raw["hotelKey"] == 45175
    assert raw["requestedCheckIn"] == "2026-06-01"
    assert raw["requestedNights"] == NIGHTS
    assert raw["calendarNight"] == 7
    assert raw["offer"]["redPriceUAH"] == 51000
    assert raw["offer"]["isHot"] is True


async def test_fetch_calendar_can_label_live_refresh_payloads() -> None:
    class _FakeClient:
        async def post_json(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "statusCode": 200,
                "data": {
                    "items": [
                        {
                            "item": {
                                "night": 15,
                                "dates": [
                                    {
                                        "date": "20.06.2026",
                                        "meal": "UAI",
                                        "room": "Family Room",
                                        "priceUAH": 88400,
                                        "price": 2120,
                                        "systemKey": "2p-refresh-raw-c42",
                                    }
                                ],
                            }
                        }
                    ]
                },
            }

    rows = await fetch_calendar(
        _FakeClient(),
        45175,
        date(2026, 6, 1),
        nights=[15],
        payload_source="live_refresh",
        payload_hotel_key="45175",
    )

    raw = rows[0].raw_payload
    assert raw["source"] == "live_refresh"
    assert raw["hotelKey"] == "45175"
    assert raw["requestedNights"] == [15]


async def test_fetch_calendar_raises_on_transient_upstream_failure() -> None:
    class _FailingClient:
        async def post_json(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise TimeoutError("calendar timeout")

    with pytest.raises(Exception, match="transient"):
        await fetch_calendar(_FailingClient(), 45175, date(2026, 6, 1))


async def test_fetch_calendar_raises_on_bad_upstream_status() -> None:
    class _BadStatusClient:
        async def post_json(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return {"statusCode": 503}

    with pytest.raises(Exception, match="transient"):
        await fetch_calendar(_BadStatusClient(), 45175, date(2026, 6, 1))
