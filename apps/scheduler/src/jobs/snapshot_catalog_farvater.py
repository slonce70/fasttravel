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
price snapshot. `has_active_prices` decays via the dedicated
`decay_active_prices` job (daily 04:00 Kyiv; hotels without a fresh
price observation for `DECAY_STALE_AFTER_DAYS` days, default 7, flip
back to FALSE).

Cron: daily 03:00 Europe/Kyiv. Concurrency: 3 (matches price job),
sleep 0.5s per request (lighter than price job's 1.0s — no calendar
POST so per-hotel cost is one GET).

Records its execution in `scrape_runs` with source='catalog_only'
so dashboards can distinguish the two passes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from src.clients.farvater_catalog import list_country_hotels
from src.clients.farvater_hotel_page import fetch_hotel_meta
from src.clients.farvater_runtime import CATALOG_COUNTRIES, open_farvater_client
from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.services.hotel_upsert import (
    country_dest_id,
    ensure_operator,
    upsert_hotel,
    upsert_mapping,
)
from src.services.scrape_runs import record_scrape_run

log = get_logger(__name__)


PER_REQUEST_DELAY_S = 0.5
CONCURRENCY = 3
SCRAPE_SOURCE = "catalog_only"
# Same rationale as snapshot_farvater.HOTEL_ERROR_RATE_THRESHOLD: a run
# stays "success" (and stamps the staleness gauge) when at most this
# fraction of hotel pages failed. Any failed country, or a run that saw
# nothing at all, must NOT refresh the gauge — that's exactly the drift
# the StaleCatalog alert exists to catch.
HOTEL_ERROR_RATE_THRESHOLD = 0.05


async def _process_catalog_hotel(
    client: Any,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
    semaphore: asyncio.Semaphore,
) -> int:
    """Fetch a single hotel HTML page and upsert it. Returns 1 on success."""
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await fetch_hotel_meta(client, url_path, iso2)
    if meta is None:
        return 0

    async with async_session_factory() as db:
        hotel_db_id = await upsert_hotel(db, meta, dest_id, operator_id)
        await upsert_mapping(db, hotel_db_id, operator_id, meta)
        await db.commit()
    log.info(
        "farvater.catalog.hotel.done",
        hotel=meta.name[:60],
        hotel_key=meta.hotel_id,
        iso2=iso2,
    )
    return 1


async def _record_run(
    db: Any,
    operator_id: int,
    status: str,
    rows_inserted: int,
    error: str = "",
    started_at: datetime | None = None,
) -> None:
    """Mirror of snapshot_farvater._record_run but tagged with our source."""
    await record_scrape_run(
        db,
        source=SCRAPE_SOURCE,
        status=status,
        rows_inserted=rows_inserted,
        error=error,
        started_at=started_at,
        operator_id=operator_id,
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
    countries_failed = 0
    hotel_errors = 0
    hotels_attempted = 0

    async with async_session_factory() as db:
        operator_id = await ensure_operator(db)
        await db.commit()

    try:
        async with open_farvater_client() as client:
            for country_slug, iso2 in CATALOG_COUNTRIES:
                async with async_session_factory() as db:
                    dest_id = await country_dest_id(db, iso2)
                    await db.commit()

                try:
                    hotel_paths = await list_country_hotels(client, country_slug)
                except Exception as exc:  # noqa: BLE001 — catalog skip is non-fatal
                    countries_failed += 1
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
                    _process_catalog_hotel(client, p, iso2, operator_id, dest_id, semaphore)
                    for p in hotel_paths
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                country_seen = sum(r for r in results if isinstance(r, int))
                country_errors = sum(1 for r in results if isinstance(r, Exception))
                total_seen += country_seen
                hotel_errors += country_errors
                hotels_attempted += len(results)
                log.info(
                    "farvater.catalog.country.done",
                    country=country_slug,
                    hotels=len(hotel_paths),
                    seen=country_seen,
                    errors=country_errors,
                )

        # Honest run status: a pass that listed nothing (all countries
        # failed, or the catalog parser silently found zero hotels) is a
        # failure, not a success. Anything degraded beyond the per-hotel
        # error threshold is partial.
        total_countries = len(CATALOG_COUNTRIES)
        hotel_error_rate = hotel_errors / hotels_attempted if hotels_attempted else 0.0
        if countries_failed >= total_countries or total_seen == 0:
            run_status = "failed"
        elif countries_failed > 0 or hotel_error_rate > HOTEL_ERROR_RATE_THRESHOLD:
            run_status = "partial"
        else:
            run_status = "success"
        run_errors: list[str] = []
        if countries_failed:
            run_errors.append(f"countries_failed={countries_failed}/{total_countries}")
        if hotel_errors:
            run_errors.append(f"hotel_errors={hotel_errors}/{hotels_attempted}")
        if total_seen == 0:
            run_errors.append("no_hotels_seen")

        async with async_session_factory() as db:
            await _record_run(
                db,
                operator_id,
                run_status,
                total_seen,
                error="; ".join(run_errors),
                started_at=started_at,
            )
            await db.commit()
        # Mirror snapshot_farvater: stamp staleness gauge on success only,
        # so the StaleCatalog alert can fire for a job that runs but
        # accomplishes nothing. bootstrap_last_successful_snapshots reads
        # the same status='success' rows after a restart.
        if run_status == "success":
            try:
                import time as _time

                from src.infra.metrics import LAST_SUCCESSFUL_SNAPSHOT

                LAST_SUCCESSFUL_SNAPSHOT.labels(scheduled_job="snapshot_catalog_farvater").set(
                    _time.time()
                )
            except Exception:  # noqa: BLE001
                log.exception("farvater.catalog.metrics_set_failed")
        log.info(
            "farvater.catalog.done",
            seen=total_seen,
            status=run_status,
            countries_failed=countries_failed,
            hotel_errors=hotel_errors,
        )
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
