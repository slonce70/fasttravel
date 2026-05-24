from __future__ import annotations

import pytest

from src.services.search_service import search_hotels


class _FakeResult:
    def mappings(self):  # type: ignore[no-untyped-def]
        return self

    def all(self) -> list[dict]:
        return []


class _FakeSession:
    def __init__(self) -> None:
        self.scalar_sql = ""
        self.execute_sql = ""

    async def scalar(self, sql, params):  # type: ignore[no-untyped-def]
        self.scalar_sql = str(sql)
        return 0

    async def execute(self, sql, params):  # type: ignore[no-untyped-def]
        self.execute_sql = str(sql)
        return _FakeResult()


@pytest.mark.asyncio
async def test_no_date_meal_search_requires_matching_price_rows() -> None:
    session = _FakeSession()

    await search_hotels(session, country="TR", meal_plan="AI", nights=7)

    assert "JOIN prices px ON px.hotel_id = h.id" in session.scalar_sql
    assert "LEFT JOIN prices px ON px.hotel_id = h.id" not in session.scalar_sql
    assert "meal_plan IN" in session.scalar_sql


@pytest.mark.asyncio
async def test_pax_metadata_is_honest_when_requested_pax_is_not_supported() -> None:
    session = _FakeSession()

    result = await search_hotels(session, adults=3, kids=[7])

    assert result.price_basis_adults == 2
    assert result.price_basis_kids == []
    assert result.pax_supported is False
    assert result.pax_note is not None
