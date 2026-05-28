from __future__ import annotations

from datetime import date

from src.services.hotel_upsert import HotelMeta
from src.services.price_insert import PriceRow, dedup_existing, insert_prices


class _FakeResult:
    rowcount = 1


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql, params=None):  # type: ignore[no-untyped-def]
        self.calls.append((str(sql), params))
        if "SELECT check_in" in str(sql):
            return _RowsResult([])
        return _FakeResult()


class _RowsResult:
    def __init__(self, rows: list[tuple[object, int, str, str, int]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, int, str, str, int]]:
        return self._rows


def _hotel() -> HotelMeta:
    return HotelMeta(
        hotel_id=45175,
        url_path="/uk/hotel/eg/albatros/",
        name="Albatros",
        country_iso2="EG",
        photo_url="",
        description="",
        stars=5,
        photos=[],
        review_score=None,
        review_count=0,
    )


def _price(
    room_category: str = "Standard Sea View",
    *,
    price_uah: int = 42500,
    price_usd: int = 1024,
    system_key: str = "2m-full-raw-c42",
) -> PriceRow:
    return PriceRow(
        hotel_id=45175,
        check_in=date(2026, 6, 15),
        nights=7,
        meal_plan="AI",
        room_category=room_category,
        price_uah=price_uah,
        price_usd=price_usd,
        system_key=system_key,
        raw_payload={"systemKey": system_key},
    )


async def test_insert_prices_keeps_room_category_in_conflict_key_and_payload() -> None:
    db = _FakeSession()

    inserted = await insert_prices(
        db,
        hotel_db_id=123,
        operator_id=18,
        hotel=_hotel(),
        rows=[_price()],
        country_iso2="EG",
    )

    assert inserted == 1
    insert_sql, payload = db.calls[-1]
    assert "meal_plan, room_category, observed_at" in insert_sql
    assert isinstance(payload, list)
    assert payload[0]["rm"] == "Standard Sea View"
    assert payload[0]["dl"] == "https://farvater.travel/uk/hotel/eg/albatros/?q=2m-full-raw-c42"


async def test_insert_prices_uses_room_category_when_filtering_recent_duplicates() -> None:
    class _DuplicateSession(_FakeSession):
        async def execute(self, sql, params=None):  # type: ignore[no-untyped-def]
            self.calls.append((str(sql), params))
            if "SELECT check_in" in str(sql):
                return _RowsResult([(date(2026, 6, 15), 7, "AI", "Standard Sea View", 42500)])
            return _FakeResult()

    db = _DuplicateSession()

    inserted = await insert_prices(
        db,
        hotel_db_id=123,
        operator_id=18,
        hotel=_hotel(),
        rows=[_price("Standard Sea View"), _price("Garden View")],
        country_iso2="EG",
    )

    assert inserted == 1
    insert_payload = db.calls[-1][1]
    assert isinstance(insert_payload, list)
    assert insert_payload[0]["rm"] == "Garden View"


async def test_insert_prices_deduplicates_intra_batch_conflict_keys_to_cheapest() -> None:
    db = _FakeSession()

    inserted = await insert_prices(
        db,
        hotel_db_id=123,
        operator_id=18,
        hotel=_hotel(),
        rows=[
            _price(price_uah=46000, price_usd=1100, system_key="expensive"),
            _price(price_uah=42000, price_usd=1000, system_key="cheapest"),
        ],
        country_iso2="EG",
    )

    assert inserted == 1
    insert_payload = db.calls[-1][1]
    assert isinstance(insert_payload, list)
    assert len(insert_payload) == 1
    assert insert_payload[0]["puah"] == 42000
    assert insert_payload[0]["dl"] == "https://farvater.travel/uk/hotel/eg/albatros/?q=cheapest"


async def test_dedup_existing_returns_room_category_keys() -> None:
    class _DedupSession:
        async def execute(self, sql, params):  # type: ignore[no-untyped-def]
            assert "COALESCE(room_category, '')" in str(sql)
            assert params["h"] == 123
            assert params["op"] == 18
            return _RowsResult([(date(2026, 6, 15), 7, "AI", "", 42500)])

    assert await dedup_existing(_DedupSession(), hotel_db_id=123, operator_id=18) == {
        (date(2026, 6, 15), 7, "AI", "", 42500)
    }
