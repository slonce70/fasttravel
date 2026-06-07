from typing import Any

from src.services.hotel_upsert import (
    OPERATOR_CODE,
    HotelMeta,
    country_dest_id,
    ensure_operator,
    upsert_hotel,
    upsert_mapping,
)


class _FakeResult:
    def __init__(self, row=None) -> None:  # type: ignore[no-untyped-def]
        self._row = row

    def first(self):  # type: ignore[no-untyped-def]
        return self._row


class _FakeSession:
    def __init__(
        self,
        *,
        operator_row: tuple[int, ...] | None = (18,),
        destination_row: tuple[int, ...] | None = (37,),
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self.operator_row = operator_row
        self.destination_row = destination_row

    async def execute(self, sql: Any, params: dict[str, Any]) -> _FakeResult:
        statement = str(sql)
        self.calls.append((statement, params))
        if "SELECT id FROM operators" in statement:
            return _FakeResult(self.operator_row)
        if "INSERT INTO operators" in statement:
            return _FakeResult((19,))
        if "SELECT id FROM destinations" in statement:
            return _FakeResult(self.destination_row)
        if "INSERT INTO destinations" in statement:
            return _FakeResult((38,))
        if "hotel_operator_mapping" in statement and "external_id" in statement:
            return _FakeResult((28644,))
        if "SELECT id FROM hotels WHERE canonical_slug" in statement:
            return _FakeResult(None)
        return _FakeResult((99999,))

    async def commit(self) -> None:
        self.commits += 1


def _db(session: _FakeSession) -> Any:
    return session


def _meta() -> HotelMeta:
    return HotelMeta(
        hotel_id=39005,
        url_path="/uk/hotel/es/apart-hotel-ght-tossa-park/",
        name="Apart Hotel Ght Tossa Park",
        country_iso2="ES",
        photo_url="",
        description="",
        stars=2,
        photos=[],
        review_score=7.6,
        review_count=46,
    )


async def test_ensure_operator_reuses_existing_farvater_operator() -> None:
    db = _FakeSession()

    operator_id = await ensure_operator(_db(db))

    assert OPERATOR_CODE == "farvater"
    assert operator_id == 18
    assert db.calls[0][1] == {"c": "farvater"}
    assert db.commits == 0


async def test_ensure_operator_insert_leaves_commit_to_caller() -> None:
    db = _FakeSession(operator_row=None)

    operator_id = await ensure_operator(_db(db))

    assert operator_id == 19
    assert db.commits == 0
    insert_sql = db.calls[1][0]
    assert "INSERT INTO operators" in insert_sql
    assert "ON CONFLICT (code)" in insert_sql


async def test_country_dest_id_finds_top_level_country_destination() -> None:
    db = _FakeSession()

    assert await country_dest_id(_db(db), "ES") == 37
    assert "parent_id IS NULL" in db.calls[0][0]
    assert db.calls[0][1] == {"iso": "ES"}


async def test_country_dest_id_creates_missing_top_level_country_destination() -> None:
    db = _FakeSession(destination_row=None)

    assert await country_dest_id(_db(db), "TR") == 38

    insert_sql = db.calls[1][0]
    assert "INSERT INTO destinations" in insert_sql
    assert "ON CONFLICT (country_iso2, region_slug)" in insert_sql
    assert db.calls[1][1] == {
        "iso": "TR",
        "slug": "turkey",
        "name_uk": "Туреччина",
        "name_en": "Turkey",
    }


async def test_upsert_hotel_reuses_existing_farvater_mapping_when_slug_changes() -> None:
    db = _FakeSession()

    hotel_id = await upsert_hotel(_db(db), _meta(), dest_id=37, operator_id=18)

    assert hotel_id == 28644
    update_calls = [params for sql, params in db.calls if "UPDATE hotels" in sql]
    assert update_calls
    assert update_calls[0]["id"] == 28644
    assert update_calls[0]["dest"] == 37


async def test_upsert_mapping_refreshes_external_name_on_conflict() -> None:
    db = _FakeSession()
    meta = _meta()

    await upsert_mapping(_db(db), hotel_db_id=54034, operator_id=18, hotel=meta)

    mapping_sql = db.calls[-1][0]
    assert "ON CONFLICT (operator_id, external_id) DO UPDATE" in mapping_sql
    assert db.calls[-1][1]["n"] == "Apart Hotel Ght Tossa Park"
