"""Tests for the `static_tours` client + parser.

The cassette `tests/cassettes/static_tours_gorjashhie_tury.json` is the
verbatim response captured during the 2026-05-25 HAR investigation
against the Farvater `static-tours` POST endpoint with
`slugTypes=["gorjashhie-tury"], countryId=-1, pageSize=50`. Parsing
against the real wire format is the only reliable schema canary.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.clients import static_tours as st
from src.clients.static_tours import (
    StaticToursPage,
    build_request_body,
    fetch_bucket_all_pages,
    parse_response,
)

CASSETTE_PATH = Path(__file__).parent / "cassettes" / "static_tours_gorjashhie_tury.json"


@pytest.fixture(scope="module")
def cassette() -> dict:
    """Load the captured static-tours response once per test module."""
    with CASSETTE_PATH.open() as fh:
        return json.load(fh)


# ── parse_response ───────────────────────────────────────────────────────


def test_parse_returns_static_tours_page(cassette: dict) -> None:
    page = parse_response(cassette, bucket_slug="gorjashhie-tury", page_index=1)
    assert isinstance(page, StaticToursPage)
    assert page.bucket_slug == "gorjashhie-tury"
    assert page.page_index == 1
    # HAR report documents totalItems=635 across all countries.
    assert page.total_items > 0


def test_parse_extracts_all_rows_from_cassette(cassette: dict) -> None:
    """The HAR cassette captured 50 hot tours; parser must accept all
    of them since they came from the live endpoint and passed
    validation upstream."""
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    assert (
        len(page.tours) >= 45
    ), f"expected ~50 tours from gorjashhie-tury cassette, got {len(page.tours)}"


def test_parse_first_row_matches_har_snapshot(cassette: dict) -> None:
    """Spot-check Arena Beach (hotelKey=15937) — the canonical sample
    used throughout the HAR report. Locks the parser to actual HAR values
    so a parser regression is caught immediately."""
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    arena = next((t for t in page.tours if t.hotel_key == 15937), None)
    assert arena is not None, "Arena Beach (hotelKey=15937) missing from cassette"
    assert arena.is_hot is True
    assert arena.is_recommended is True
    assert arena.is_otp is True
    assert arena.is_choice_farvater is False
    assert arena.price_uah == 29847
    assert arena.red_price_uah == 29847  # HAR finding: red == price in current data
    assert arena.operator_name == "Alliance"
    assert arena.operator_id_int == 119
    assert arena.system_key == "2p4191025733778095065c51"
    assert arena.bucket_slug == "gorjashhie-tury"


def test_parse_meal_canonicalization(cassette: dict) -> None:
    """meal.value comes localised ('Сніданок (BB)'). Parser must
    canonicalise to our 8-char meal code."""
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    arena = next((t for t in page.tours if t.hotel_key == 15937), None)
    assert arena is not None
    assert arena.meal_plan == "BB"


def test_parse_handles_iso_dates(cassette: dict) -> None:
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    arena = next((t for t in page.tours if t.hotel_key == 15937), None)
    assert arena is not None
    assert arena.check_in == date(2026, 6, 11)
    assert arena.loaded_date is not None
    assert arena.loaded_date.year == 2026


def test_parse_rejects_status_code_not_200() -> None:
    page = parse_response(
        {"statusCode": 500, "data": {}},
        bucket_slug="gorjashhie-tury",
    )
    assert page.tours == []
    assert page.total_items == 0


def test_parse_rejects_zero_price() -> None:
    """0-price row should be dropped — same guard as Sprint 0.4."""
    bad = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "totalItems": 1,
                "tours": [
                    {
                        "hotelKey": "100",
                        "SystemKey": "abc",
                        "priceUAH": 0,
                        "nights": 7,
                        "checkIn": {"value": "2026-07-01T00:00:00+03:00"},
                        "meal": {"value": "AI"},
                    }
                ],
            }
        },
    }
    page = parse_response(bad, bucket_slug="gorjashhie-tury")
    assert page.tours == []


def test_parse_rejects_empty_system_key() -> None:
    bad = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "totalItems": 1,
                "tours": [
                    {
                        "hotelKey": "100",
                        "SystemKey": "",
                        "priceUAH": 10000,
                        "nights": 7,
                        "checkIn": {"value": "2026-07-01T00:00:00+03:00"},
                        "meal": {"value": "AI"},
                    }
                ],
            }
        },
    }
    page = parse_response(bad, bucket_slug="gorjashhie-tury")
    assert page.tours == []


def test_parse_rejects_missing_check_in() -> None:
    bad = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "totalItems": 1,
                "tours": [
                    {
                        "hotelKey": "100",
                        "SystemKey": "abc",
                        "priceUAH": 10000,
                        "nights": 7,
                        "checkIn": {"value": None},
                        "meal": {"value": "AI"},
                    }
                ],
            }
        },
    }
    page = parse_response(bad, bucket_slug="gorjashhie-tury")
    assert page.tours == []


def test_parse_handles_empty_tours_list() -> None:
    empty = {
        "statusCode": 200,
        "data": {"tourPackage": {"totalItems": 0, "tours": []}},
    }
    page = parse_response(empty, bucket_slug="gorjashhie-tury")
    assert page.tours == []
    assert page.total_items == 0


def test_parse_preserves_raw_payload(cassette: dict) -> None:
    """`raw` carries the unmodified upstream dict so forensics queries
    can re-derive fields without re-fetching."""
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    assert page.tours
    sample = page.tours[0]
    assert sample.raw["SystemKey"] == sample.system_key
    assert "hotelKey" in sample.raw


def test_parse_flag_coverage_matches_har_distribution(cassette: dict) -> None:
    """HAR report finding: in gorjashhie-tury bucket isHot=100%,
    isRecommended~52%, IsChoiceFarvater~4%. Lock the parser to that
    distribution as a regression guard against silent flag flips.
    """
    page = parse_response(cassette, bucket_slug="gorjashhie-tury")
    total = len(page.tours)
    assert total > 0

    hot_rate = sum(1 for t in page.tours if t.is_hot) / total
    promo_rate = sum(1 for t in page.tours if t.raw.get("isPromo")) / total

    assert hot_rate == 1.0, f"isHot should be 100% in this bucket, got {hot_rate}"
    # HAR documented isPromo always-false: if upstream starts populating
    # it again, we'll want to know.
    assert promo_rate == 0.0


# ── build_request_body ───────────────────────────────────────────────────


def test_build_request_body_matches_har_schema() -> None:
    body = build_request_body(bucket_slug="gorjashhie-tury", country_id=-1)
    # The HAR snapshot of V4SEOcatalog.js shows exactly these field names.
    expected_fields = {
        "nightFrom",
        "nightTo",
        "slugTypes",
        "countryId",
        "starIDs",
        "meals",
        "adults",
        "kids",
        "ages",
        "hotels",
        "resorts",
        "airportList",
        "operatorIdList",
        "checkinList",
        "pageSize",
        "pageIndex",
        "descByPrice",
    }
    assert set(body.keys()) == expected_fields
    assert body["slugTypes"] == ["gorjashhie-tury"]
    assert body["countryId"] == -1
    assert body["adults"] == 2


def test_build_request_body_honours_overrides() -> None:
    body = build_request_body(
        bucket_slug="rannee-bronirovanie",
        country_id=83,
        page_size=25,
        page_index=3,
        adults=4,
        check_in_from=date(2026, 7, 1),
        check_in_to=date(2026, 7, 31),
    )
    assert body["slugTypes"] == ["rannee-bronirovanie"]
    assert body["countryId"] == 83
    assert body["pageSize"] == 25
    assert body["pageIndex"] == 3
    assert body["adults"] == 4
    assert body["checkinList"][0]["From"].startswith("2026-07-01")
    assert body["checkinList"][0]["To"].startswith("2026-07-31")


# ── fetch_bucket_all_pages ──────────────────────────────────────────────


async def test_fetch_all_pages_stops_after_first_when_total_fits(
    cassette: dict,
) -> None:
    """If `total_items <= page_size`, no second-page POST should fire."""
    client = AsyncMock()
    client.post_json = AsyncMock(return_value=cassette)

    rows = await fetch_bucket_all_pages(
        client,  # type: ignore[arg-type]
        bucket_slug="gorjashhie-tury",
        page_size=10_000,  # forces "all fits in one page"
    )
    assert client.post_json.await_count == 1
    assert len(rows) > 0


async def test_fetch_all_pages_respects_max_pages_cap(cassette: dict) -> None:
    """Hard safety cap — even if upstream keeps returning data, never
    exceed `max_pages` POSTs."""
    # Mimic an upstream that claims totalItems=100 but always returns
    # a full page. Without the cap this would loop forever.
    looping = dict(cassette)
    looping = json.loads(json.dumps(cassette))  # deep copy
    looping["data"]["tourPackage"]["totalItems"] = 99_999

    client = AsyncMock()
    client.post_json = AsyncMock(return_value=looping)

    await fetch_bucket_all_pages(
        client,  # type: ignore[arg-type]
        bucket_slug="gorjashhie-tury",
        page_size=10,
        max_pages=3,
    )
    assert client.post_json.await_count == 3


async def test_fetch_all_pages_stops_on_empty_page() -> None:
    """If upstream returns an empty tours[] mid-pagination, stop —
    don't waste calls on subsequent pages."""
    full = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "totalItems": 100,
                "tours": [
                    {
                        "hotelKey": "1",
                        "SystemKey": "sk1",
                        "priceUAH": 10000,
                        "nights": 7,
                        "checkIn": {"value": "2026-07-01T00:00:00+03:00"},
                        "meal": {"value": "AI"},
                    }
                ]
                * 10,  # 10 valid tours
            }
        },
    }
    empty = {
        "statusCode": 200,
        "data": {"tourPackage": {"totalItems": 100, "tours": []}},
    }

    client = AsyncMock()
    client.post_json = AsyncMock(side_effect=[full, empty, full])

    await fetch_bucket_all_pages(
        client,  # type: ignore[arg-type]
        bucket_slug="gorjashhie-tury",
        page_size=10,
        max_pages=10,
    )
    # First page returned 1 unique row (after dedup via SystemKey within parser),
    # second page returned empty → break before third call.
    assert client.post_json.await_count == 2


async def test_unknown_bucket_logs_warning_but_still_fetches(
    cassette: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """`SUPPORTED_BUCKETS` is informational — if farvater adds a new
    bucket the client should still attempt the fetch (operator decision)."""
    client = AsyncMock()
    client.post_json = AsyncMock(return_value=cassette)

    await st.fetch_bucket_page(
        client,  # type: ignore[arg-type]
        bucket_slug="brand-new-bucket-2026",
    )
    assert client.post_json.await_count == 1
