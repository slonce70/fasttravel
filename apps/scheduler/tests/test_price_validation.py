"""Tests for the shared farvater price-row validator.

Why this exists: the May 2026 audit found that snapshot_farvater and
refresh_worker silently accepted `priceUAH=0` and empty `systemKey` from
upstream — both produced phantom rows that corrupted price_baselines and
yielded broken deep_links. The validator centralises the reject rules so
the bug cannot regress in one writer while the other stays patched.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.jobs._price_validation import (
    REJECT_BAD_DATE,
    REJECT_EMPTY_SYSTEM_KEY,
    REJECT_NON_POSITIVE_PRICE,
    parse_check_in,
    validate_price_row,
)

# ── validate_price_row ───────────────────────────────────────────────────


def _row(
    *,
    priceUAH: int | str | None = 12500,
    systemKey: str | None = "abc123",
    date_: str | None = "01.07.2026",
    meal: str = "AI",
    room: str = "Standard",
) -> dict[str, object]:
    """Build a representative calendar `dates[]` element."""
    return {
        "priceUAH": priceUAH,
        "systemKey": systemKey,
        "date": date_,
        "meal": meal,
        "room": room,
        "price": 300,
    }


def test_accepts_well_formed_row() -> None:
    ok, reason = validate_price_row(_row())
    assert ok is True
    assert reason is None


@pytest.mark.parametrize("bad_price", [0, -1, "0", "-100", None])
def test_rejects_zero_or_negative_price(bad_price: object) -> None:
    ok, reason = validate_price_row(_row(priceUAH=bad_price))  # type: ignore[arg-type]
    assert ok is False
    assert reason == REJECT_NON_POSITIVE_PRICE


def test_rejects_unparseable_price() -> None:
    ok, reason = validate_price_row(_row(priceUAH="not a number"))
    assert ok is False
    assert reason == REJECT_NON_POSITIVE_PRICE


@pytest.mark.parametrize("bad_key", ["", "   ", None])
def test_rejects_empty_system_key(bad_key: object) -> None:
    ok, reason = validate_price_row(_row(systemKey=bad_key))  # type: ignore[arg-type]
    assert ok is False
    assert reason == REJECT_EMPTY_SYSTEM_KEY


@pytest.mark.parametrize("bad_date", [None, "", "   "])
def test_rejects_missing_date(bad_date: object) -> None:
    ok, reason = validate_price_row(_row(date_=bad_date))  # type: ignore[arg-type]
    assert ok is False
    assert reason == REJECT_BAD_DATE


def test_reject_reason_precedence_is_stable() -> None:
    """When multiple fields are bad the precedence is: price → key → date.

    Pinning the order means downstream dashboards / log filters that count
    rejects by reason stay accurate as the validator evolves.
    """
    ok, reason = validate_price_row({"priceUAH": 0, "systemKey": "", "date": ""})
    assert ok is False
    assert reason == REJECT_NON_POSITIVE_PRICE


# ── parse_check_in ───────────────────────────────────────────────────────


def test_parses_farvater_date_format() -> None:
    assert parse_check_in("01.07.2026") == date(2026, 7, 1)
    assert parse_check_in("31.12.2026") == date(2026, 12, 31)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "2026-07-01",  # ISO format — farvater uses DD.MM.YYYY
        "07/01/2026",  # US format
        "31.02.2026",  # impossible date
        "not a date",
    ],
)
def test_returns_none_on_unparseable(bad: object) -> None:
    assert parse_check_in(bad) is None
