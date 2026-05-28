"""Shared validator for Farvater calendar price rows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

REJECT_NON_POSITIVE_PRICE = "non_positive_price"
REJECT_EMPTY_SYSTEM_KEY = "empty_system_key"
REJECT_BAD_DATE = "bad_date"


def validate_price_row(row: dict[str, Any]) -> tuple[bool, str | None]:
    raw_uah = row.get("priceUAH")
    try:
        price_uah = int(raw_uah or 0)
    except (TypeError, ValueError):
        return False, REJECT_NON_POSITIVE_PRICE
    if price_uah <= 0:
        return False, REJECT_NON_POSITIVE_PRICE

    system_key = str(row.get("systemKey") or "").strip()
    if not system_key:
        return False, REJECT_EMPTY_SYSTEM_KEY

    raw_date = row.get("date")
    if raw_date is None or not str(raw_date).strip():
        return False, REJECT_BAD_DATE

    return True, None


def parse_check_in(raw: Any) -> date | None:
    if raw is None:
        return None
    try:
        return datetime.strptime(str(raw), "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None
