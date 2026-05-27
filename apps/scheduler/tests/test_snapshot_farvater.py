import importlib
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from src.jobs.snapshot_farvater import (
    DEFAULT_MAX_HOTELS_PER_COUNTRY,
    NIGHTS,
    HotelMeta,
    _clean_title,
    _extract_hotel_name,
    _fetch_calendar,
    _fetch_hotel_meta,
    _mark_unpriced,
    _refresh_targets,
    _http_client,
    _upsert_hotel,
    _upsert_mapping,
    snapshot_farvater,
)


def test_clean_title_uses_slug_fallback_for_farvater_boilerplate() -> None:
    assert (
        _clean_title("ᐉ - Farvater Travel", "/uk/hotel/eg/golf-villas-by-rixos/")
        == "Golf Villas By Rixos"
    )


def test_snapshot_collects_expanded_scheduled_nights() -> None:
    assert NIGHTS == [7, 8, 9, 10, 11, 12, 13, 14]


@pytest.mark.asyncio
async def test_fetch_calendar_preserves_full_farvater_offer_payload() -> None:
    class _FakeClient:
        async def post_json(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "statusCode": 200,
                "data": {
                    "items": [
                        {
                            "item": {
                                "night": 7,
                                "dates": [
                                    {
                                        "date": "15.06.2026",
                                        "meal": "AI",
                                        "room": "Standard Sea View",
                                        "priceUAH": 42500,
                                        "price": 1024,
                                        "systemKey": "2m-full-raw-c42",
                                        "redPriceUAH": 51000,
                                        "isHot": True,
                                    }
                                ],
                            }
                        }
                    ]
                },
            }

    rows = await _fetch_calendar(_FakeClient(), 45175, date(2026, 6, 1))

    assert len(rows) == 1
    raw = rows[0].raw_payload
    assert raw["systemKey"] == "2m-full-raw-c42"
    assert raw["source"] == "farvater_scrape"
    assert raw["hotelKey"] == 45175
    assert raw["requestedCheckIn"] == "2026-06-01"
    assert raw["requestedNights"] == NIGHTS
    assert raw["calendarNight"] == 7
    assert raw["offer"]["redPriceUAH"] == 51000
    assert raw["offer"]["isHot"] is True


def test_clean_title_extracts_hotel_name_from_tours_title() -> None:
    assert (
        _clean_title(
            "4* - тури в готель Дефне Стар Сіде - Farvater Travel",
            "/uk/hotel/tr/defne-star-hotel/",
        )
        == "Дефне Стар Сіде"
    )


def test_clean_title_unescapes_entities_and_drops_example_tail() -> None:
    assert (
        _clean_title(
            "Bellagio Beach Resort &amp; Spa (наприклад ціни) - Farvater Travel",
            "/uk/hotel/eg/panorama-bungalows-resort-hurghada/",
        )
        == "Bellagio Beach Resort & Spa"
    )


def test_clean_title_keeps_hotel_word_inside_previous_name() -> None:
    assert (
        _clean_title(
            "ᐉ Antik Butik (ex. Antik Hotel &amp; Garden) ✈ Ціни на відпочинок",
            "/uk/hotel/tr/antik-butik/",
        )
        == "Antik Butik (ex. Antik Hotel & Garden)"
    )


def test_clean_title_keeps_hotel_word_when_name_starts_with_hotel() -> None:
    assert (
        _clean_title(
            "Hotel &amp; Resort Gacka 4* - Montenegro - Farvater Travel",
            "/uk/hotel/me/hotel-resort-gacka/",
        )
        == "Hotel & Resort Gacka"
    )


def test_extract_hotel_name_prefers_title_over_boilerplate_h1() -> None:
    page = """
    <title>Antik Butik (ex. Antik Hotel &amp; Garden) 4* - Туреччина, Аланія - Farvater Travel</title>
    <h1 id="TP__Blocks__TourTitle">
      Тури і ціни на відпочинок в готелі Antik Butik (ex. Antik Hotel & Garden) 4* 2026-2027 Туреччина, Аланія
    </h1>
    """

    assert (
        _extract_hotel_name(page, "/uk/hotel/tr/antik-butik/")
        == "Antik Butik (ex. Antik Hotel & Garden)"
    )


def test_clean_title_uses_slug_fallback_for_ex_only_title() -> None:
    assert (
        _clean_title(
            "ᐉ (ex. Belport Beach Hotel) 4* - Farvater Travel",
            "/uk/hotel/tr/belport-beach-hotel/",
        )
        == "Belport Beach Hotel"
    )


@pytest.mark.asyncio
async def test_http_client_follows_farvater_redirects() -> None:
    async with _http_client() as client:
        assert client._client is not None  # noqa: SLF001
        assert client._client.follow_redirects is True  # noqa: SLF001


@pytest.mark.asyncio
async def test_fetch_hotel_meta_treats_404_as_expected_stale_url(monkeypatch) -> None:
    class _NotFoundClient:
        async def get_text(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            request = httpx.Request("GET", "https://farvater.travel/uk/hotel/tr/stale/")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    events: list[tuple[str, dict]] = []

    class _FakeLog:
        def info(self, event: str, **kwargs):  # type: ignore[no-untyped-def]
            events.append((event, kwargs))

        def warning(self, event: str, **kwargs):  # type: ignore[no-untyped-def]
            events.append((event, kwargs))

    module = importlib.import_module("src.jobs.snapshot_farvater")
    monkeypatch.setattr(module, "log", _FakeLog())

    result = await _fetch_hotel_meta(_NotFoundClient(), "/uk/hotel/tr/stale/", "TR")

    assert result is None
    assert (
        "farvater.hotel_not_found",
        {"url": "https://farvater.travel/uk/hotel/tr/stale/", "status_code": 404},
    ) in events
    assert all(event != "farvater.hotel_fetch_failed" for event, _kwargs in events)


@pytest.mark.asyncio
async def test_snapshot_uses_default_country_cap_when_env_missing(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def fake_ensure_operator(db):  # type: ignore[no-untyped-def]
        return 18

    async def fake_refresh_targets(db, iso_filter, max_per_country):  # type: ignore[no-untyped-def]
        captured["max_per_country"] = max_per_country
        return []

    async def fake_record_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def execution_options(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self

        async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return None

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

    module = importlib.import_module("src.jobs.snapshot_farvater")
    monkeypatch.delenv("FT_SNAPSHOT_MAX_HOTELS_PER_COUNTRY", raising=False)
    monkeypatch.setattr(module, "async_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(module, "_ensure_operator", fake_ensure_operator)
    monkeypatch.setattr(module, "_refresh_targets", fake_refresh_targets)
    monkeypatch.setattr(module, "_http_client", lambda: _FakeClient())
    monkeypatch.setattr(module, "_record_run", fake_record_run)
    monkeypatch.setattr("src.infra.db.async_engine", _FakeEngine())

    await snapshot_farvater(max_runtime_minutes=1)

    assert captured["max_per_country"] == DEFAULT_MAX_HOTELS_PER_COUNTRY


def test_snapshot_has_no_extra_request_sleep_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FT_FARVATER_REQUEST_DELAY_S", raising=False)

    module = importlib.reload(importlib.import_module("src.jobs.snapshot_farvater"))

    assert module.PER_REQUEST_DELAY_S == 0.0


@pytest.mark.asyncio
async def test_refresh_targets_excludes_inactive_long_tail_hotels() -> None:
    class _Rows:
        def all(self):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=1,
                    canonical_slug="fv-tr-active-hotel",
                    country_iso2="TR",
                    external_id="101",
                    has_active_prices=True,
                    last_priced_at=date(2026, 5, 1),
                ),
                SimpleNamespace(
                    id=2,
                    canonical_slug="fv-tr-no-inventory",
                    country_iso2="TR",
                    external_id="102",
                    has_active_prices=False,
                    last_priced_at=date(2026, 5, 1),
                ),
                SimpleNamespace(
                    id=3,
                    canonical_slug="fv-eg-never-priced",
                    country_iso2="EG",
                    external_id="103",
                    has_active_prices=False,
                    last_priced_at=None,
                ),
            ]

    class _FakeSession:
        async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return _Rows()

    targets = await _refresh_targets(_FakeSession(), ["TR", "EG"], None)

    assert targets == [
        ("/uk/hotel/tr/active-hotel/", "TR", 1, "101"),
        ("/uk/hotel/eg/never-priced/", "EG", 3, "103"),
    ]


@pytest.mark.asyncio
async def test_mark_unpriced_removes_stale_active_hotel_from_refresh_cohort() -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, sql, params):  # type: ignore[no-untyped-def]
            self.calls.append((str(sql), params))

    db = _FakeSession()

    await _mark_unpriced(db, 123)

    statement, params = db.calls[0]
    assert "has_active_prices = FALSE" in statement
    assert "last_priced_at = NOW()" in statement
    assert params == {"id": 123}


class _FakeResult:
    def __init__(self, row=None) -> None:  # type: ignore[no-untyped-def]
        self._row = row

    def first(self):  # type: ignore[no-untyped-def]
        return self._row


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, sql, params):  # type: ignore[no-untyped-def]
        statement = str(sql)
        self.calls.append((statement, params))
        if "hotel_operator_mapping" in statement and "external_id" in statement:
            return _FakeResult((28644,))
        if "SELECT id FROM hotels WHERE canonical_slug" in statement:
            return _FakeResult(None)
        return _FakeResult((99999,))


@pytest.mark.asyncio
async def test_upsert_hotel_reuses_existing_farvater_mapping_when_slug_changes() -> None:
    db = _FakeSession()
    meta = HotelMeta(
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

    hotel_id = await _upsert_hotel(db, meta, dest_id=37, operator_id=18)

    assert hotel_id == 28644
    update_calls = [params for sql, params in db.calls if "UPDATE hotels" in sql]
    assert update_calls
    assert update_calls[0]["id"] == 28644


@pytest.mark.asyncio
async def test_upsert_mapping_refreshes_external_name_on_conflict() -> None:
    db = _FakeSession()
    meta = HotelMeta(
        hotel_id=291623,
        url_path="/uk/hotel/tr/antik-butik/",
        name="Antik Butik (ex. Antik Hotel & Garden)",
        country_iso2="TR",
        photo_url="",
        description="",
        stars=4,
        photos=[],
        review_score=None,
        review_count=0,
    )

    await _upsert_mapping(db, hotel_db_id=54034, operator_id=18, hotel=meta)

    mapping_sql = db.calls[-1][0]
    assert "ON CONFLICT (operator_id, external_id) DO UPDATE" in mapping_sql
    assert db.calls[-1][1]["n"] == "Antik Butik (ex. Antik Hotel & Garden)"
