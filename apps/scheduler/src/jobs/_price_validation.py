"""Shared validator for farvater calendar price rows.

Two writers parse `low-price-calendar/auto` responses — `snapshot_farvater`
(scheduled, twice daily) and `refresh_worker` (on-demand, BRPOP-driven).
Both used to silently accept garbage from upstream:

  - `priceUAH = 0` rows would land in `price_observations`, then
    `detect_deals` could read them as "amazing bargains" and broadcast
    obviously-fake "deals" to the Telegram channel.
  - empty `systemKey` would still construct a deep_link like
    `https://farvater.travel/uk/hotel/...?q=` which farvater treats as
    "no offer pre-selected" and either 404s or quotes a different price.

The validator centralises the reject rules so both call sites apply the
same predicate and so a metric counter can attribute rejections by
reason.

Reject reasons are short stable strings — they go into log fields and
Prometheus label values, so keep them lowercase, snake_case, and
backwards-compatible once shipped.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Valid reject reasons. Adding new ones is fine; renaming an existing one
# silently breaks downstream metrics labels and log filters.
REJECT_NON_POSITIVE_PRICE = "non_positive_price"
REJECT_EMPTY_SYSTEM_KEY = "empty_system_key"
REJECT_BAD_DATE = "bad_date"


def validate_price_row(row: dict[str, Any]) -> tuple[bool, str | None]:
    """Decide whether a single date-cell from farvater's calendar response
    is safe to persist.

    Returns (True, None) on accept, or (False, reject_reason) on reject.

    Caller is responsible for parsing the date string; this helper only
    checks structural validity. For unparseable dates, callers should
    pass `row["date"]` = invalid sentinel and rely on REJECT_BAD_DATE,
    OR (more typically) parse first and skip on parse failure separately
    — both are tested.
    """
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
    """Parse farvater's `DD.MM.YYYY` date or return None.

    Both writers had this inline as bare `datetime.strptime(...).date()`
    inside a try/except — extracting the helper lets us reject with a
    consistent reason code instead of silently dropping the row.
    """
    if raw is None:
        return None
    try:
        return datetime.strptime(str(raw), "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None
