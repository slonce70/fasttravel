"""Catalog-only farvater.travel crawl.

Split from `snapshot_farvater` so we can run a cheap **HTML-only** pass
across the whole catalog daily without paying for the per-hotel
`low-price-calendar/auto` POST. The price job stays heavyweight and
runs twice a day; this one only refreshes meta + `last_seen_at`.

Pipeline (per country):
  1. GET `/uk/hotelscatalog/strana-{slug}/` → list of hotel URL paths
  2. For each URL path, GET the hotel HTML page (concurrency=3)
  3. Parse name / stars / og:image / description → UPSERT hotels
     (which bumps `last_seen_at = NOW()` via the shared
      `_upsert_hotel` helper)
  4. UPSERT into `hotel_operator_mapping` so the price job can
     resolve mapKey → DB id later.

We deliberately do NOT touch `price_observations`,
`current_prices`, or `has_active_prices` here — those belong to the
price snapshot. `has_active_prices` decays via a separate
cleanup pass at the tail of `snapshot_farvater` (hotels without a
fresh price observation for 7+ days flip back to FALSE).

Cron: daily 03:00 Europe/Kyiv. Concurrency: 3 (matches price job),
sleep 0.5s per request (lighter than price job's 1.0s — no calendar
POST so per-hotel cost is one GET).

Records its execution in `scrape_runs` with source='catalog_only'
so dashboards can distinguish the two passes.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.snapshot_farvater import (
    CATALOG_COUNTRIES,
    USER_AGENT,
    _country_dest_id,
    _ensure_operator,
    _fetch_hotel_meta,
    _http_client,
    _list_country_hotels,
    _upsert_hotel,
    _upsert_mapping,
)

log = get_logger(__name__)


PER_REQUEST_DELAY_S = 0.5
CONCURRENCY = 3
SCRAPE_SOURCE = "catalog_only"


async def _process_catalog_hotel(
    client,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
    semaphore: asyncio.Semaphore,
) -> int:
    """Fetch a single hotel HTML page and upsert it. Returns 1 on success."""
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await _fetch_hotel_meta(client, url_path, iso2)
    if meta is None:
        return 0

    async with async_session_factory() as db:
        hotel_db_id = await _upsert_hotel(db, meta, dest_id)
        await _upsert_mapping(db, hotel_db_id, operator_id, meta)
        await db.commit()
    log.info(
        "farvater.catalog.hotel.done",
        hotel=meta.name[:60],
        hotel_key=meta.hotel_id,
        iso2=iso2,
    )
    return 1


async def _record_run(
    db,
    operator_id: int,
    status: str,
    rows_inserted: int,
    error: str = "",
    started_at: datetime | None = None,
) -> None:
    """Mirror of snapshot_farvater._record_run but tagged with our source."""
    await db.execute(
        text(
            """INSERT INTO scrape_runs
                  (started_at, finished_at, operator_id, source, status,
                   rows_inserted, error_text)
                VALUES (:s, NOW(), :op, :src, :st, :n, :e)"""
        ),
        {
            "s": started_at or datetime.now(UTC),
            "op": operator_id,
            "src": SCRAPE_SOURCE,
            "st": status,
            "n": rows_inserted,
            "e": error[:500],
        },
    )


async def snapshot_catalog_farvater(*, max_per_country: int | None = None) -> int:
    """Top-level entrypoint. Returns total hotels processed.

    Args:
      max_per_country: optional cap for dev / smoke tests; None = all.
    """
    started_at = datetime.now(UTC)
    log.info(
        "farvater.catalog.start",
        countries=len(CATALOG_COUNTRIES),
        concurrency=CONCURRENCY,
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)
    total_seen = 0

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    try:
        async with _http_client() as client:
            for country_slug, iso2 in CATALOG_COUNTRIES:
                async with async_session_factory() as db:
                    dest_id = await _country_dest_id(db, iso2)

                try:
                    hotel_paths = await _list_country_hotels(client, country_slug)
                except Exception as exc:  # noqa: BLE001 — catalog skip is non-fatal
                    log.error(
                        "farvater.catalog.country_failed",
                        country=country_slug,
                        error=str(exc),
                    )
                    continue

                if max_per_country:
                    hotel_paths = hotel_paths[:max_per_country]

                log.info(
                    "farvater.catalog.country.start",
                    country=country_slug,
                    iso2=iso2,
                    hotels=len(hotel_paths),
                )

                tasks = [
                    _process_catalog_hotel(
                        client, p, iso2, operator_id, dest_id, semaphore
                    )
                    for p in hotel_paths
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                country_seen = sum(r for r in results if isinstance(r, int))
                country_errors = sum(1 for r in results if isinstance(r, Exception))
                total_seen += country_seen
                log.info(
                    "farvater.catalog.country.done",
                    country=country_slug,
                    hotels=len(hotel_paths),
                    seen=country_seen,
                    errors=country_errors,
                )

        async with async_session_factory() as db:
            await _record_run(
                db, operator_id, "success", total_seen, started_at=started_at
            )
            await db.commit()
        log.info("farvater.catalog.done", seen=total_seen)
        return total_seen

    except Exception as exc:  # noqa: BLE001 — top-level guard, logged
        async with async_session_factory() as db:
            await _record_run(
                db,
                operator_id,
                "failed",
                total_seen,
                error=str(exc),
                started_at=started_at,
            )
            await db.commit()
        log.error("farvater.catalog.failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(snapshot_catalog_farvater(max_per_country=cap))
