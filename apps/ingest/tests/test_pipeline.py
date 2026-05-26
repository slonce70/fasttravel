"""Pipeline DB-write contract tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.normalizers.base import NormalizedOffer
from src.pipeline import HotelTarget, _bulk_insert


class _MappingsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingsResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _InsertResult:
    rowcount = 1


class _FakeDb:
    def __init__(self, operator_rows: list[dict[str, Any]]) -> None:
        self.operator_rows = operator_rows
        self.calls: list[tuple[Any, Any]] = []
        self.commits = 0

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.calls.append((stmt, params))
        if len(self.calls) == 1:
            return _MappingsResult(self.operator_rows)
        return _InsertResult()

    async def commit(self) -> None:
        self.commits += 1


def _offer(operator_code: str = "farvater") -> NormalizedOffer:
    return NormalizedOffer(
        hotel_external_id="hotel-1",
        operator_code=operator_code,
        check_in=date(2026, 7, 1),
        nights=7,
        meal_plan="AI",
        price_uah=42000,
        price_original=1000,
        currency="USD",
        fx_rate_to_uah=Decimal("42.0"),
        deep_link="https://example.test/tour",
    )


@pytest.mark.asyncio
async def test_bulk_insert_resolves_operator_id_and_uses_conflict_guard() -> None:
    db = _FakeDb(operator_rows=[{"id": 9, "code": "farvater"}])

    inserted = await _bulk_insert(
        db,
        [_offer()],
        [HotelTarget(canonical_hotel_id=123, external_id="hotel-1")],
    )

    assert inserted == 1
    assert len(db.calls) == 2
    insert_sql = str(db.calls[1][0])
    insert_rows = db.calls[1][1]
    assert "ON CONFLICT" in insert_sql
    assert "DO NOTHING" in insert_sql
    assert insert_rows[0]["operator_id"] == 9
    assert db.commits == 1


@pytest.mark.asyncio
async def test_bulk_insert_skips_offers_with_unknown_operator() -> None:
    db = _FakeDb(operator_rows=[])

    inserted = await _bulk_insert(
        db,
        [_offer(operator_code="missing")],
        [HotelTarget(canonical_hotel_id=123, external_id="hotel-1")],
    )

    assert inserted == 0
    assert len(db.calls) == 1
    assert db.commits == 0
