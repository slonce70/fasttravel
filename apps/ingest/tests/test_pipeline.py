"""Pipeline DB-write contract tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.clients.farvater_scraper import FarvaterScraper
from src.exceptions import UnsupportedGenericFarvaterIngest
from src.normalizers.base import NormalizedOffer
from src.normalizers.farvater_normalizer import parse_calendar_xhr
from src.pipeline import HotelTarget, SnapshotReport, _bulk_insert, run_snapshot


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
        room_category=None,
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
    assert "meal_plan, room_category, observed_at" in insert_sql
    assert "DO NOTHING" in insert_sql
    assert insert_rows[0]["room_category"] == ""
    assert insert_rows[0]["operator_id"] == 9
    assert db.commits == 0


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


@pytest.mark.asyncio
async def test_run_snapshot_owns_successful_insert_commit(
    redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _FakeDb(operator_rows=[])
    offer = _offer(operator_code="ittour")

    async def _collect_stub(**kwargs: Any) -> list[NormalizedOffer]:
        report: SnapshotReport = kwargs["report"]
        report.hotels_processed = 1
        report.offers_collected = 1
        return [offer]

    async def _not_duplicate(*args: Any, **kwargs: Any) -> bool:
        return False

    async def _insert_stub(*args: Any, **kwargs: Any) -> int:
        return 1

    monkeypatch.setattr("src.pipeline._collect_offers", _collect_stub)
    monkeypatch.setattr("src.pipeline.is_duplicate", _not_duplicate)
    monkeypatch.setattr("src.pipeline._bulk_insert", _insert_stub)

    report = await run_snapshot(
        db=db,
        redis=redis,
        source="ittour",
        hotels=[HotelTarget(canonical_hotel_id=123, external_id="hotel-1")],
        check_in_range=(date(2026, 7, 1), date(2026, 7, 8)),
    )

    assert report.offers_inserted == 1
    assert db.commits == 1


@pytest.mark.asyncio
async def test_run_snapshot_rejects_generic_farvater_before_client_parser_or_db(
    redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb(operator_rows=[{"id": 9, "code": "farvater"}])

    class _ExplodingFarvaterScraper:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pytest.fail("generic Farvater ingest must not instantiate FarvaterScraper")

    async def _fail_async(*args: Any, **kwargs: Any) -> None:
        pytest.fail("generic Farvater ingest must reject before dedup or DB work")

    def _fail_parse(*args: Any, **kwargs: Any) -> None:
        pytest.fail("generic Farvater ingest must not parse calendar XHR")

    monkeypatch.setattr("src.clients.farvater_scraper.FarvaterScraper", _ExplodingFarvaterScraper)
    monkeypatch.setattr("src.normalizers.farvater_normalizer.parse_calendar_xhr", _fail_parse)
    monkeypatch.setattr("src.pipeline.is_duplicate", _fail_async)
    monkeypatch.setattr("src.pipeline._bulk_insert", _fail_async)

    with pytest.raises(UnsupportedGenericFarvaterIngest, match="snapshot_farvater"):
        await run_snapshot(
            db=db,
            redis=redis,
            source="farvater",
            hotels=[HotelTarget(canonical_hotel_id=123, external_id="hotel-1")],
            check_in_range=(date(2026, 7, 1), date(2026, 7, 8)),
        )

    assert db.calls == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_farvater_calendar_client_is_explicitly_scheduler_owned(redis) -> None:
    scraper = FarvaterScraper(redis)

    with pytest.raises(UnsupportedGenericFarvaterIngest, match="scheduler"):
        await scraper.fetch_calendar_xhr("hotel-1")


def test_farvater_calendar_normalizer_is_explicitly_scheduler_owned() -> None:
    with pytest.raises(UnsupportedGenericFarvaterIngest, match="scheduler"):
        parse_calendar_xhr({"hotelId": "hotel-1"})
