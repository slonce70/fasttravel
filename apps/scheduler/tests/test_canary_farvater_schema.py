"""Tests for the daily farvater schema canary (Sprint 3.7).

The canary's value is in the path-presence assertion logic; the actual
HTTP and DB sides are stubbed out so this runs without docker.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

from src.infra.metrics import CANARY_SCHEMA_FAILURES

# Same trick as test_static_tours_sweep — `from src.jobs import
# canary_farvater_schema` resolves to the FUNCTION, not the module.
canary = importlib.import_module("src.jobs.canary_farvater_schema")


def _drift_counter(endpoint: str, reason: str) -> float:
    return CANARY_SCHEMA_FAILURES.labels(endpoint=endpoint, reason=reason)._value.get()  # noqa: SLF001


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


# ── Prometheus drift signal ─────────────────────────────────────────────
# The canary never raises (JOB_RUNS stays outcome="success"), so the
# fasttravel_canary_schema_failures_total counter is the only metric
# Prometheus can alert on — FarvaterSchemaDrift fires on any increase.


async def test_probe_calendar_mismatch_increments_drift_counter() -> None:
    client = MagicMock()
    client.post_json = AsyncMock(return_value={"statusCode": 200, "data": {}})

    before = _drift_counter("calendar", "schema_mismatch")
    ok, missing = await canary._probe_calendar(client)

    assert not ok
    assert missing
    assert _drift_counter("calendar", "schema_mismatch") == before + 1


async def test_probe_static_tours_fetch_failure_increments_drift_counter() -> None:
    client = MagicMock()
    client.post_json = AsyncMock(side_effect=RuntimeError("cloudflare 403"))

    before = _drift_counter("static_tours", "fetch_failed")
    ok, _missing = await canary._probe_static_tours(client)

    assert not ok
    assert _drift_counter("static_tours", "fetch_failed") == before + 1


async def test_canary_mismatch_returns_nonzero_without_raising(
    monkeypatch,
) -> None:
    """Full-job path: a schema mismatch keeps the never-raises contract
    (return != 0), records a failed scrape_run, and leaves the drift
    counter incremented for Prometheus."""
    monkeypatch.setattr(canary, "_record_run", AsyncMock())
    monkeypatch.setattr(canary, "get_redis", MagicMock(return_value=MagicMock()))

    class _FakeClient:
        post_json = AsyncMock(return_value={"statusCode": 200, "data": {}})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(canary, "FarvaterProdClient", lambda _r: _FakeClient())

    cal_before = _drift_counter("calendar", "schema_mismatch")
    st_before = _drift_counter("static_tours", "schema_mismatch")

    result = await canary.canary_farvater_schema()

    assert result == 2  # both endpoints mismatched
    canary._record_run.assert_awaited_once()
    assert canary._record_run.await_args.args[1] == "failed"
    assert _drift_counter("calendar", "schema_mismatch") == cal_before + 1
    assert _drift_counter("static_tours", "schema_mismatch") == st_before + 1


async def test_canary_internal_error_increments_drift_counter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(canary, "_record_run", AsyncMock())
    monkeypatch.setattr(canary, "get_redis", MagicMock(side_effect=RuntimeError("redis down")))

    before = _drift_counter("all", "internal_error")
    result = await canary.canary_farvater_schema()

    assert result == 1
    assert _drift_counter("all", "internal_error") == before + 1
