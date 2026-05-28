from __future__ import annotations

import json
from datetime import date
from typing import Any, ClassVar
from unittest.mock import AsyncMock

import pytest

from src.clients.farvater_calendar import NIGHTS
from src.jobs import refresh_worker
from src.services.hotel_upsert import HotelMeta
from src.services.price_insert import PriceRow


class _FakeResponse:
    status_code = 200

    def json(self) -> dict[str, Any]:
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
    requests: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, *_args: object, **_kwargs: Any) -> _FakeResponse:
        self.__class__.requests.append(_kwargs)
        return _FakeResponse()


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None = None, scalar: Any = None) -> None:
        self._row = row
        self._scalar = scalar

    def first(self) -> tuple[Any, ...] | None:
        return self._row

    def scalar(self) -> Any:
        return self._scalar


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.commits = 0

    async def execute(self, sql: Any, _params: dict[str, Any] | None = None) -> _FakeResult:
        statement = str(sql)
        self.calls.append(statement)
        if "SELECT id FROM operators" in statement:
            return _FakeResult(row=(18,))
        if "FROM hotels h" in statement:
            return _FakeResult(scalar="https://farvater.travel/uk/hotel/es/demo-hotel/")
        return _FakeResult()

    async def commit(self) -> None:
        self.commits += 1


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeEngineConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __aenter__(self) -> _FakeEngineConnection:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execution_options(self, **_kwargs: Any) -> _FakeEngineConnection:
        return self

    async def execute(self, sql: Any) -> None:
        self.calls.append(str(sql))


class _FakeEngine:
    def __init__(self, connection: _FakeEngineConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeEngineConnection:
        return self.connection


@pytest.mark.asyncio
async def test_refresh_worker_preserves_full_farvater_offer_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.requests = []
    monkeypatch.setattr("src.jobs.refresh_worker.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(refresh_worker, "CHECK_IN_OFFSETS_DAYS", [3])

    rows = await refresh_worker._fetch_hotel_prices(42, "45175")

    assert len(rows) == 1
    assert rows[0].room_category == "Family Room"
    assert rows[0].price_uah == 88400
    raw = rows[0].raw_payload
    assert raw["systemKey"] == "2p-refresh-raw-c42"
    assert raw["source"] == "live_refresh"
    assert raw["hotelKey"] == "45175"
    assert raw["requestedNights"] == NIGHTS
    assert raw["calendarNight"] == 14
    assert raw["offer"]["redPriceUAH"] == 110000
    assert raw["offer"]["isPromo"] is True


@pytest.mark.asyncio
async def test_refresh_worker_fetches_requested_custom_nights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.requests = []
    monkeypatch.setattr("src.jobs.refresh_worker.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(refresh_worker, "CHECK_IN_OFFSETS_DAYS", [3])

    rows = await refresh_worker._fetch_hotel_prices(42, "45175", requested_nights=[15])

    assert _FakeAsyncClient.requests[0]["json"]["nights"] == [15]
    assert rows[0].raw_payload["requestedNights"] == [15]


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_nights", [[True], [False], [7, True]])
async def test_refresh_worker_rejects_boolean_requested_nights(
    monkeypatch: pytest.MonkeyPatch,
    requested_nights: list[object],
) -> None:
    fetch_prices = AsyncMock(return_value=[])
    persist_prices = AsyncMock(return_value=0)
    monkeypatch.setattr(refresh_worker, "_fetch_hotel_prices", fetch_prices)
    monkeypatch.setattr(refresh_worker, "_persist_prices", persist_prices)

    await refresh_worker._process_job(
        json.dumps(
            {
                "hotel_id": 42,
                "farvater_key": "45175",
                "requested_nights": requested_nights,
            }
        )
    )

    fetch_prices.assert_not_awaited()
    persist_prices.assert_not_awaited()


def test_refresh_worker_deep_link_sql_allows_region_destinations() -> None:
    sql = str(refresh_worker._DEEP_LINK_BASE_SQL)

    assert "LEFT JOIN destinations parent" in sql
    assert "d.parent_id IS NULL" not in sql
    assert "COALESCE(parent.country_iso2, d.country_iso2)" in sql


@pytest.mark.asyncio
async def test_persist_prices_delegates_insert_to_shared_price_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    engine_connection = _FakeEngineConnection()
    inserted: list[tuple[int, int, str, list[PriceRow], str | None]] = []

    async def _insert_prices(
        db: _FakeSession,
        hotel_db_id: int,
        operator_id: int,
        hotel: HotelMeta,
        rows: list[PriceRow],
        country_iso2: str | None = None,
    ) -> int:
        inserted.append((hotel_db_id, operator_id, hotel.url_path, rows, country_iso2))
        return len(rows)

    monkeypatch.setattr(
        refresh_worker,
        "async_session_factory",
        lambda: _FakeSessionFactory(session),
    )
    monkeypatch.setattr(
        "src.services.materialized_views.async_engine", _FakeEngine(engine_connection)
    )
    monkeypatch.setattr(refresh_worker, "insert_prices", _insert_prices, raising=False)

    row = PriceRow(
        hotel_id=45175,
        check_in=date(2026, 6, 20),
        nights=14,
        meal_plan="AI",
        room_category="Family Room",
        price_uah=88400,
        price_usd=2120,
        system_key="2p-refresh-raw-c42",
        raw_payload={"systemKey": "2p-refresh-raw-c42"},
    )

    count = await refresh_worker._persist_prices(42, [row])

    assert count == 1
    assert inserted == [(42, 18, "/uk/hotel/es/demo-hotel/", [row], "ES")]
    assert session.commits == 1
    assert any("UPDATE hotels" in call for call in session.calls)
    assert not any("INSERT INTO price_observations" in call for call in session.calls)
    assert engine_connection.calls == [
        "REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY hotel_calendar_prices",
    ]
