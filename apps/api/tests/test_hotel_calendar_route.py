from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.routers import hotels as hotels_router
from src.services.calendar_service import get_calendar


@pytest.mark.asyncio
async def test_calendar_route_passes_meal_plan_filter(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_get_calendar(
        session: AsyncSession,
        hotel_id: int,
        from_date: date,
        to_date: date,
        meal_plan: str | None = None,
        nights: int | None = None,
    ) -> list[object]:
        captured.update(
            {
                "session": session,
                "hotel_id": hotel_id,
                "from_date": from_date,
                "to_date": to_date,
                "meal_plan": meal_plan,
                "nights": nights,
            }
        )
        return []

    monkeypatch.setattr(hotels_router, "get_calendar", fake_get_calendar)

    response = await client.get(
        "/api/hotels/42/calendar?from=2026-05-25&to=2026-06-05&meal_plan=AI&nights=5"
    )

    assert response.status_code == 200
    assert captured["session"] is db_session
    assert captured["hotel_id"] == 42
    assert captured["from_date"] == date(2026, 5, 25)
    assert captured["to_date"] == date(2026, 6, 5)
    assert captured["meal_plan"] == "AI"
    assert captured["nights"] == 5


class _FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeCalendarSession:
    """Mock session that records the SQL it sees and returns a single
    fixed CalendarDay-shaped row so we can assert the service layer's
    query construction and decoding."""

    def __init__(self, prices_by_night: dict[str, int] | None = None) -> None:
        self.statement = ""
        self.params: dict[str, object] = {}
        self._prices = prices_by_night or {"5": 55555}

    async def execute(self, statement, params):  # type: ignore[no-untyped-def]
        self.statement = str(statement)
        self.params = dict(params)
        return _FakeResult(
            [
                {
                    "check_in": date(2026, 5, 27),
                    "meal_plan": self.params.get("requested_meal_plan"),
                    "min_price_uah": min(self._prices.values()),
                    "prices_by_night": dict(self._prices),
                    "observed_at": None,
                }
            ]
        )


@pytest.mark.asyncio
async def test_calendar_service_filters_exact_nights_from_current_prices() -> None:
    session = _FakeCalendarSession({"5": 55555})

    rows = await get_calendar(
        session, 54034, date(2026, 5, 24), date(2026, 6, 1), meal_plan="AI", nights=5
    )

    assert "FROM current_prices cp" in session.statement
    assert "cp.nights = :nights" in session.statement
    # Exact-nights branch builds prices_by_night via jsonb_build_object so
    # the response shape is identical with or without ?nights.
    assert "jsonb_build_object" in session.statement
    assert session.params["nights"] == 5
    assert session.params["nights_key"] == "5"
    assert session.params["meal_codes"] == ["AI"]
    assert rows[0].min_price_uah == 55555
    assert rows[0].prices_by_night == {"5": 55555}
    assert rows[0].meal_plan == "AI"


@pytest.mark.asyncio
async def test_calendar_service_echoes_meal_filter_without_exact_nights() -> None:
    session = _FakeCalendarSession({"7": 44444, "8": 45555})

    rows = await get_calendar(session, 54034, date(2026, 5, 24), date(2026, 6, 1), meal_plan="AI")

    assert "FROM hotel_calendar_prices" in session.statement
    assert session.params["meal_codes"] == ["AI"]
    assert session.params["requested_meal_plan"] == "AI"
    assert rows[0].meal_plan == "AI"


@pytest.mark.asyncio
async def test_calendar_service_returns_prices_by_night_for_non_legacy_nights() -> None:
    """Regression for Stage 2 audit fix: ?nights=9 used to fall back to
    min_price_uah because the MV only exposed 7/10/14. After migration 016
    we return the per-nights map for any value scrape supplies (7..14)."""
    session = _FakeCalendarSession({"9": 49000})

    rows = await get_calendar(session, 42, date(2026, 5, 24), date(2026, 6, 1), nights=9)

    assert session.params["nights"] == 9
    assert session.params["nights_key"] == "9"
    assert rows[0].prices_by_night == {"9": 49000}
    assert rows[0].min_price_uah == 49000


@pytest.mark.asyncio
async def test_calendar_service_reads_mv_when_no_nights() -> None:
    """Without ?nights= the service must read hotel_calendar_prices
    (the MV that already stores the full prices_by_night map)."""
    session = _FakeCalendarSession({"7": 50000, "8": 51000, "14": 47000})

    rows = await get_calendar(session, 42, date(2026, 5, 24), date(2026, 6, 1))

    assert "FROM hotel_calendar_prices" in session.statement
    assert "jsonb_each_text" in session.statement
    assert rows[0].prices_by_night == {"7": 50000, "8": 51000, "14": 47000}


@pytest.mark.asyncio
async def test_hotel_route_resolves_slug_alias_to_canonical_hotel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO hotels (id, canonical_slug, name_uk, is_active)
            VALUES (990001, 'test-canonical-alias-hotel', 'Alias Test Hotel', TRUE)
            """
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
            VALUES ('test-old-alias-hotel', 990001, 'test duplicate')
            """
        )
    )

    response = await client.get("/api/hotels/test-old-alias-hotel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 990001
    assert payload["canonical_slug"] == "test-canonical-alias-hotel"


@pytest.mark.asyncio
async def test_hotel_route_returns_404_for_unknown_slug(client: AsyncClient) -> None:
    response = await client.get("/api/hotels/not-a-real-hotel-slug")

    assert response.status_code == 404
