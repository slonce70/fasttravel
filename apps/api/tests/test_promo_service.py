from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from src.services.promo_service import list_promotions


class _FakeResult:
    def all(self) -> list[Any]:
        return []


class _CapturingSession:
    async def scalar(self, statement) -> int:  # type: ignore[no-untyped-def]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "promo_offers.price_uah > 0" in sql
        return 0

    async def execute(self, statement) -> _FakeResult:  # type: ignore[no-untyped-def]
        return _FakeResult()


@pytest.mark.asyncio
async def test_min_discount_filter_requires_positive_price() -> None:
    await list_promotions(_CapturingSession(), min_discount_pct=20)  # type: ignore[arg-type]
