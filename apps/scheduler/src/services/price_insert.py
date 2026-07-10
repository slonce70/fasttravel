"""Farvater price observation insert helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.logging import get_logger
from src.services.hotel_upsert import HotelMeta

log = get_logger(__name__)


@dataclass
class PriceRow:
    hotel_id: int  # farvater hotelKey
    check_in: date
    nights: int
    meal_plan: str
    room_category: str
    price_uah: int
    price_usd: int
    system_key: str
    raw_payload: dict[str, Any]


_DbConflictKey = tuple[date, int, str, str]

# Serializes concurrent price writers (refresh worker vs scheduled snapshots)
# per hotel. The unique index on price_observations includes observed_at, and
# each writer stamps its own datetime.now(UTC), so ON CONFLICT never fires
# across writers — the 12h dedup below is a non-atomic SELECT-then-INSERT.
# The xact-scoped lock is held until the caller commits, so the losing writer
# re-reads the window only after the winner's rows are visible.
_HOTEL_PRICE_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(hashtext('price_obs:' || CAST(:h AS text)))"
)


def _db_conflict_key(row: PriceRow) -> _DbConflictKey:
    return (row.check_in, row.nights, row.meal_plan, row.room_category or "")


def _cheaper_price_row(current: PriceRow, candidate: PriceRow) -> PriceRow:
    if candidate.price_uah < current.price_uah:
        return candidate
    if candidate.price_uah == current.price_uah and candidate.system_key < current.system_key:
        return candidate
    return current


def dedup_intra_batch(rows: list[PriceRow]) -> list[PriceRow]:
    """Collapse rows that would conflict inside one INSERT batch.

    The DB conflict key intentionally excludes price/systemKey. If Farvater
    sends two offers for the same hotel/date/nights/meal/room at the same
    scrape timestamp, keep the cheapest deterministic winner before INSERT so
    counts and metrics reflect what can actually be written.
    """
    winners: dict[_DbConflictKey, PriceRow] = {}
    order: list[_DbConflictKey] = []
    for row in rows:
        key = _db_conflict_key(row)
        if key not in winners:
            winners[key] = row
            order.append(key)
            continue
        winners[key] = _cheaper_price_row(winners[key], row)
    return [winners[key] for key in order]


async def dedup_existing(
    db: AsyncSession, hotel_db_id: int, operator_id: int
) -> set[tuple[object, int, str, str, int]]:
    """Return recent natural keys, including room_category."""
    from src.services.dedup_window import existing_dedup_keys

    return await existing_dedup_keys(db, hotel_id=hotel_db_id, operator_id=operator_id)


async def insert_prices(
    db: AsyncSession,
    hotel_db_id: int,
    operator_id: int,
    hotel: HotelMeta,
    rows: list[PriceRow],
    country_iso2: str | None = None,
) -> int:
    if not rows:
        return 0
    await db.execute(_HOTEL_PRICE_LOCK_SQL, {"h": hotel_db_id})
    existing = await dedup_existing(db, hotel_db_id, operator_id)
    new_rows = [
        r
        for r in rows
        if (r.check_in, r.nights, r.meal_plan, r.room_category or "", r.price_uah) not in existing
    ]
    new_rows = dedup_intra_batch(new_rows)
    if not new_rows:
        return 0

    observed_at = datetime.now(UTC)
    deep_link_base = f"https://farvater.travel{hotel.url_path}"

    payload = [
        {
            "obs": observed_at,
            "h": hotel_db_id,
            "op": operator_id,
            "ci": r.check_in,
            "n": r.nights,
            "m": r.meal_plan,
            "rm": r.room_category,
            "ad": 2,
            "dc": "",
            "puah": r.price_uah,
            "porig": r.price_usd,
            "cur": "USD",
            "fx": (Decimal(r.price_uah) / Decimal(r.price_usd) if r.price_usd else Decimal("41.5")),
            # `?q=<systemKey>` is farvater's internal booking-preselect param.
            "dl": f"{deep_link_base}?q={r.system_key}",
            "raw": json.dumps(r.raw_payload, default=str),
        }
        for r in new_rows
    ]

    await db.execute(
        text("""INSERT INTO price_observations
                  (observed_at, hotel_id, operator_id, check_in, nights,
                   meal_plan, room_category, adults, departure_city,
                   price_uah, price_original, currency, fx_rate_to_uah,
                   deep_link, raw_payload)
                VALUES (:obs, :h, :op, :ci, :n, :m, :rm, :ad, :dc,
                        :puah, :porig, :cur, :fx, :dl, CAST(:raw AS jsonb))
                    ON CONFLICT
                      (hotel_id, operator_id, check_in, nights,
                       meal_plan, room_category, observed_at)
                DO NOTHING"""),
        payload,
    )

    try:
        from src.infra.metrics import PRICES_WRITTEN

        PRICES_WRITTEN.labels(source="farvater_scrape", country=(country_iso2 or "unknown")).inc(
            len(payload)
        )
    except Exception:  # noqa: BLE001
        log.exception("farvater.insert_prices.metrics_failed")

    return len(payload)
