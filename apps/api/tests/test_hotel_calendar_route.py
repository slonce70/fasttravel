from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.routers import hotels as hotels_router


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
    ) -> list[object]:
        captured.update(
            {
                "session": session,
                "hotel_id": hotel_id,
                "from_date": from_date,
                "to_date": to_date,
                "meal_plan": meal_plan,
            }
        )
        return []

    monkeypatch.setattr(hotels_router, "get_calendar", fake_get_calendar)

    response = await client.get(
        "/api/hotels/42/calendar?from=2026-05-25&to=2026-06-05&meal_plan=AI"
    )

    assert response.status_code == 200
    assert captured["session"] is db_session
    assert captured["hotel_id"] == 42
    assert captured["from_date"] == date(2026, 5, 25)
    assert captured["to_date"] == date(2026, 6, 5)
    assert captured["meal_plan"] == "AI"
