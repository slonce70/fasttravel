from __future__ import annotations

from typing import ClassVar

import pytest

from src.jobs import refresh_worker


class _FakeResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "statusCode": 200,
            "data": {
                "items": [
                    {
                        "item": {
                            "night": 14,
                            "dates": [
                                {
                                    "date": "20.06.2026",
                                    "meal": "UAI",
                                    "room": "Family Room",
                                    "priceUAH": 88400,
                                    "price": 2120,
                                    "systemKey": "2p-refresh-raw-c42",
                                    "redPriceUAH": 110000,
                                    "isPromo": True,
                                }
                            ],
                        }
                    }
                ]
            },
        }


class _FakeAsyncClient:
    requests: ClassVar[list[dict]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, *_args, **_kwargs):
        self.__class__.requests.append(_kwargs)
        return _FakeResponse()


@pytest.mark.asyncio
async def test_refresh_worker_preserves_full_farvater_offer_payload(monkeypatch) -> None:
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(refresh_worker.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(refresh_worker, "CHECK_IN_OFFSETS_DAYS", [3])

    rows = await refresh_worker._fetch_hotel_prices(42, "45175")

    assert len(rows) == 1
    raw = rows[0]["raw"]
    assert raw["systemKey"] == "2p-refresh-raw-c42"
    assert raw["source"] == "live_refresh"
    assert raw["hotelKey"] == "45175"
    assert raw["requestedNights"] == refresh_worker.NIGHTS
    assert raw["calendarNight"] == 14
    assert raw["offer"]["redPriceUAH"] == 110000
    assert raw["offer"]["isPromo"] is True


@pytest.mark.asyncio
async def test_refresh_worker_fetches_requested_custom_nights(monkeypatch) -> None:
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(refresh_worker.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(refresh_worker, "CHECK_IN_OFFSETS_DAYS", [3])

    rows = await refresh_worker._fetch_hotel_prices(42, "45175", requested_nights=[15])

    assert _FakeAsyncClient.requests[0]["json"]["nights"] == [15]
    assert rows[0]["raw"]["requestedNights"] == [15]


def test_refresh_worker_deep_link_sql_allows_region_destinations() -> None:
    sql = str(refresh_worker._DEEP_LINK_BASE_SQL)

    assert "LEFT JOIN destinations parent" in sql
    assert "d.parent_id IS NULL" not in sql
    assert "COALESCE(parent.country_iso2, d.country_iso2)" in sql
