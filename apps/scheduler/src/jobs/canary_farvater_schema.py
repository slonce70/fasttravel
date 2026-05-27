"""Daily JSON-schema canary for farvater endpoints.

The Sprint 1B/1C ingest path is entirely parser-driven. If farvater
silently changes the shape of `low-price-calendar/auto` or
`/uk/catalog/static-tours` (renames a field, drops a level, changes a
type), the parser will start logging row rejections and the operator
won't know until they notice "rows written" trending to zero.

This canary fires once a day, sends one minimal probe to each
endpoint, and validates the response shape against a fixed schema
derived from the May 2026 HAR snapshot. Any mismatch logs at ERROR,
increments a Prometheus counter, and writes a `failed` row to
scrape_runs so the SnapshotJobFailed alert family covers it.

Pure shape check — no business-data assertions. A change in
`isHot=true|false` ratios doesn't trigger; an `isHot` field that
disappears entirely does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from src.clients.static_tours import (
    STATIC_TOURS_URL,
    build_request_body,
)
from src.infra.cache import get_redis
from src.infra.db import async_session_factory
from src.infra.farvater_http import FarvaterProdClient
from src.infra.logging import get_logger

log = get_logger(__name__)


# Sample hotelKey used to probe the calendar endpoint. Picked to be a
# well-known hotel that has consistent inventory; if this ever needs
# updating it's because the hotel was delisted, not because of schema
# drift.
SAMPLE_HOTEL_KEY = 15937  # Arena Beach Hotel & Spa (Maldives), per HAR
CALENDAR_URL = "https://farvater.travel/uk/tour/stat/low-price-calendar/auto"
CALENDAR_NIGHTS = [7, 8, 9, 10, 11, 12, 13, 14]


def _missing_paths(obj: Any, paths: list[str]) -> list[str]:
    """Return the list of `paths` not present in `obj`. `paths` are
    dot-separated (e.g. 'data.tourPackage.tours[0].SystemKey').
    Indexed elements are referenced as `name[0]`."""
    missing: list[str] = []
    for path in paths:
        cur: Any = obj
        ok = True
        for part in path.split("."):
            if "[" in part and part.endswith("]"):
                name, idx_s = part[:-1].split("[", 1)
                try:
                    idx = int(idx_s)
                except ValueError:
                    ok = False
                    break
                if name:
                    cur = cur.get(name) if isinstance(cur, dict) else None
                if not isinstance(cur, list) or len(cur) <= idx:
                    ok = False
                    break
                cur = cur[idx]
            else:
                if not isinstance(cur, dict) or part not in cur:
                    ok = False
                    break
                cur = cur[part]
        if not ok:
            missing.append(path)
    return missing


# Minimal "must exist" paths per endpoint. Names match the original HAR
# capture against the Farvater production endpoints (2026-05-25). Don't
# tighten beyond what's actually load-bearing — too tight means false
# alarms on cosmetic upstream changes (e.g. a new field added next to
# an existing one).
_CALENDAR_REQUIRED_PATHS = [
    "statusCode",
    "data",
    "data.items[0]",
    "data.items[0].item",
    "data.items[0].item.night",
    "data.items[0].item.dates[0]",
    "data.items[0].item.dates[0].date",
    "data.items[0].item.dates[0].priceUAH",
    "data.items[0].item.dates[0].systemKey",
]

_STATIC_TOURS_REQUIRED_PATHS = [
    "statusCode",
    "data",
    "data.tourPackage",
    "data.tourPackage.tours[0]",
    "data.tourPackage.tours[0].hotelKey",
    "data.tourPackage.tours[0].SystemKey",
    "data.tourPackage.tours[0].priceUAH",
    "data.tourPackage.tours[0].isHot",
    "data.tourPackage.tours[0].isEarly",
    "data.tourPackage.tours[0].IsChoiceFarvater",
    "data.tourPackage.tours[0].checkIn",
    "data.tourPackage.tours[0].nights",
]


async def _probe_calendar(client: FarvaterProdClient) -> tuple[bool, list[str]]:
    """Returns (ok, missing_paths)."""
    check_in = date.today() + timedelta(days=14)
    try:
        payload = await client.post_json(
            CALENDAR_URL,
            params={
                "hotelKey": SAMPLE_HOTEL_KEY,
                "adults": 2,
                "ages": 0,
                "meals": "all",
                "checkIn": check_in.strftime("%d.%m.%Y"),
            },
            json={"dateShift": 7, "nights": CALENDAR_NIGHTS, "townFroms": "all"},
            extra_headers={
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("canary.calendar.fetch_failed", error=str(exc))
        return False, [f"fetch_failed: {exc!s}"]

    missing = _missing_paths(payload, _CALENDAR_REQUIRED_PATHS)
    if missing:
        log.error("canary.calendar.schema_mismatch", missing=missing)
        return False, missing
    return True, []


async def _probe_static_tours(client: FarvaterProdClient) -> tuple[bool, list[str]]:
    body = build_request_body(
        bucket_slug="gorjashhie-tury",
        country_id=-1,
        page_size=10,
    )
    try:
        payload = await client.post_json(
            STATIC_TOURS_URL,
            json=body,
            extra_headers={
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://farvater.travel/uk/",
                "Origin": "https://farvater.travel",
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("canary.static_tours.fetch_failed", error=str(exc))
        return False, [f"fetch_failed: {exc!s}"]

    missing = _missing_paths(payload, _STATIC_TOURS_REQUIRED_PATHS)
    if missing:
        log.error("canary.static_tours.schema_mismatch", missing=missing)
        return False, missing
    return True, []


async def _record_run(started_at: datetime, status: str, error: str = "") -> None:
    try:
        async with async_session_factory() as db:
            await db.execute(
                text(
                    """INSERT INTO scrape_runs
                         (started_at, finished_at, source, status,
                          rows_inserted, error_text)
                       VALUES (:s, NOW(), 'canary_farvater_schema', :st, 0, :e)"""
                ),
                {"s": started_at, "st": status, "e": error[:500]},
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("canary.record_failed", error=str(exc))


async def canary_farvater_schema() -> int:
    """Returns 0 on success (schemas match) or non-zero on mismatch.

    Never raises — the daily tick must not crash the scheduler.
    """
    started_at = datetime.now(UTC)
    errors: list[str] = []
    try:
        redis = await get_redis()
        async with FarvaterProdClient(redis) as client:
            cal_ok, cal_missing = await _probe_calendar(client)
            if not cal_ok:
                errors.append(f"calendar: {','.join(cal_missing)}")
            st_ok, st_missing = await _probe_static_tours(client)
            if not st_ok:
                errors.append(f"static_tours: {','.join(st_missing)}")
    except Exception as exc:  # noqa: BLE001
        log.exception("canary.failed", error=str(exc))
        await _record_run(started_at, "failed", f"outer: {exc!s}")
        return 1

    if errors:
        await _record_run(started_at, "failed", "; ".join(errors))
        log.error("canary.summary", errors=errors)
        return len(errors)

    await _record_run(started_at, "success")
    log.info("canary.summary", status="ok")
    return 0
