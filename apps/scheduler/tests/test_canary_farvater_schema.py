"""Tests for the daily farvater schema canary (Sprint 3.7).

The canary's value is in the path-presence assertion logic; the actual
HTTP and DB sides are stubbed out so this runs without docker.
"""

from __future__ import annotations

import importlib

# Same trick as test_static_tours_sweep — `from src.jobs import
# canary_farvater_schema` resolves to the FUNCTION, not the module.
canary = importlib.import_module("src.jobs.canary_farvater_schema")


def test_missing_paths_returns_empty_when_all_present() -> None:
    obj = {"a": {"b": [{"c": 1}]}}
    missing = canary._missing_paths(obj, ["a", "a.b", "a.b[0]", "a.b[0].c"])
    assert missing == []


def test_missing_paths_flags_absent_keys() -> None:
    obj = {"a": {"b": [{"c": 1}]}}
    missing = canary._missing_paths(obj, ["a.b[0].d", "a.x"])
    assert set(missing) == {"a.b[0].d", "a.x"}


def test_missing_paths_flags_out_of_bounds_index() -> None:
    obj = {"a": [{"x": 1}]}
    missing = canary._missing_paths(obj, ["a[5].x"])
    assert missing == ["a[5].x"]


def test_missing_paths_flags_wrong_type() -> None:
    """Index into a non-list should be reported as missing."""
    obj = {"a": "string"}
    missing = canary._missing_paths(obj, ["a[0]"])
    assert missing == ["a[0]"]


def test_har_calendar_response_satisfies_required_paths() -> None:
    """The required-paths list must validate against the HAR snapshot
    or the canary will false-positive on a perfectly valid response.
    Mirrors the calendar response shape captured during the original HAR
    investigation against the Farvater production endpoint
    (`/uk/tour/stat/low-price-calendar/auto`).
    """
    har_snapshot = {
        "statusCode": 200,
        "data": {
            "items": [
                {
                    "item": {
                        "night": 7,
                        "dates": [
                            {
                                "date": "01.07.2026",
                                "priceUAH": 29847,
                                "systemKey": "abc",
                                "meal": "AI",
                                "room": "Standard",
                            }
                        ],
                    }
                }
            ]
        },
    }
    missing = canary._missing_paths(har_snapshot, canary._CALENDAR_REQUIRED_PATHS)
    assert missing == []


def test_har_static_tours_response_satisfies_required_paths() -> None:
    har_snapshot = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "tours": [
                    {
                        "hotelKey": "15937",
                        "SystemKey": "abc",
                        "priceUAH": 29847,
                        "isHot": True,
                        "isEarly": False,
                        "IsChoiceFarvater": False,
                        "checkIn": {"value": "2026-07-01T00:00:00+03:00"},
                        "nights": 7,
                    }
                ]
            }
        },
    }
    missing = canary._missing_paths(har_snapshot, canary._STATIC_TOURS_REQUIRED_PATHS)
    assert missing == []


def test_calendar_paths_catch_dropped_systemkey() -> None:
    """The canary must fire if farvater removes the SystemKey field —
    this is exactly the regression the canary exists to catch."""
    broken = {
        "statusCode": 200,
        "data": {
            "items": [
                {
                    "item": {
                        "night": 7,
                        "dates": [
                            {
                                "date": "01.07.2026",
                                "priceUAH": 29847,
                                # systemKey intentionally absent
                                "meal": "AI",
                            }
                        ],
                    }
                }
            ]
        },
    }
    missing = canary._missing_paths(broken, canary._CALENDAR_REQUIRED_PATHS)
    assert "data.items[0].item.dates[0].systemKey" in missing


def test_static_tours_paths_catch_dropped_ishot() -> None:
    broken = {
        "statusCode": 200,
        "data": {
            "tourPackage": {
                "tours": [
                    {
                        "hotelKey": "1",
                        "SystemKey": "k",
                        "priceUAH": 1,
                        # isHot intentionally absent
                        "isEarly": False,
                        "IsChoiceFarvater": False,
                        "checkIn": {"value": "2026-07-01T00:00:00+03:00"},
                        "nights": 7,
                    }
                ]
            }
        },
    }
    missing = canary._missing_paths(broken, canary._STATIC_TOURS_REQUIRED_PATHS)
    assert "data.tourPackage.tours[0].isHot" in missing
