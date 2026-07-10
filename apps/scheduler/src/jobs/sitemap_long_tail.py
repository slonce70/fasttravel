"""Long-tail catalog + price ingest from farvater's sitemap.

Walks farvater's sitemap (9 shards, ~57k URLs across our 11 countries),
upserts hotel meta with gallery + reviews, AND probes the price calendar
inline. Hotels with inventory get `has_active_prices=true` and full
price_observations the same pass — no need to wait for the next
snapshot_farvater tick.

Two usage modes:

1. APScheduler job — registered in `src.main` to run weekly. Self-healing:
   on container restart the next weekly tick picks up where the prior
   run was killed (slug-dedup makes the call idempotent).

2. CLI one-off — `scripts/ingest_sitemap_catalog.py` is a thin wrapper
   that calls `main()` directly. Useful when you want an immediate full
   refresh after extending CATALOG_COUNTRIES.

Tuned for throughput. This long-tail pass is operator-driven and reads
CONCURRENCY / DELAY from env, defaulting to CONCURRENCY=12 / DELAY=0.05s.
For local full-catalog recovery, set FT_SITEMAP_INGEST_DELAY_S=0.

Cloudflare in front of farvater rarely rate-limits at this rate; if you
see 429s or 503s drop CONCURRENCY first, DELAY second.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

from src.clients.farvater_calendar import fetch_calendar
from src.clients.farvater_catalog import list_sitemap_hotels, make_slug
from src.clients.farvater_hotel_page import fetch_hotel_meta
from src.clients.farvater_runtime import (
    CATALOG_COUNTRIES,
    CHECK_IN_OFFSETS_DAYS,
    open_farvater_client,
)
from src.infra.db import async_session_factory
from src.infra.job_lock import try_job_lock
from src.infra.logging import get_logger
from src.services.hotel_upsert import (
    country_dest_id,
    ensure_operator,
    upsert_hotel,
    upsert_mapping,
)
from src.services.materialized_views import refresh_price_views
from src.services.price_insert import insert_prices
from src.services.price_state import mark_priced, mark_unpriced
from src.services.scrape_runs import record_scrape_run

# Transient errors worth retrying. Captures DNS failures (the observed live
# incident — gaierror inside httpx.ConnectError), connection resets, and
# upstream timeouts. Excludes HTTP 4xx/5xx — those are application-level
# and a retry won't help.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.NetworkError,
    socket.gaierror,
    OSError,
)

log = get_logger(__name__)

# Aggressive operator-driven tuning. See module docstring.
CONCURRENCY = int(os.environ.get("FT_SITEMAP_INGEST_CONCURRENCY", "12"))
PER_REQUEST_DELAY_S = float(os.environ.get("FT_SITEMAP_INGEST_DELAY_S", "0.05"))
PER_HOTEL_TIMEOUT_S = float(os.environ.get("FT_SITEMAP_HOTEL_TIMEOUT_S", "90.0"))
# One broad price-calendar request per long-tail hotel. This mirrors
# snapshot_farvater's current one-request product window.
PROBE_OFFSETS = CHECK_IN_OFFSETS_DAYS
SCRAPE_SOURCE = "catalog_sitemap"

# Cross-run mutex. The ingest is registered under three APScheduler job
# ids (weekly Sun 02:00, optional startup one-shot, daily 04:45 fallback)
# plus the CLI wrapper; max_instances=1 only dedupes within one job id,
# so without this lock two full ~1-2h passes can overlap and double the
# load on farvater. The lock TTL is renewed while the run is alive, so
# it survives multi-hour passes yet frees within one TTL after a crash.
_INGEST_LOCK_KEY = "scheduler:sitemap_long_tail:lock"
_INGEST_LOCK_TTL_S = 15 * 60

_ALREADY_INGESTED_SQL = text(
    """SELECT canonical_slug
       FROM hotels
       WHERE canonical_slug = ANY(:s)
         AND last_priced_at IS NOT NULL"""
)


async def _already_ingested(slugs: list[str]) -> set[str]:
    if not slugs:
        return set()
    async with async_session_factory() as db:
        rows = (await db.execute(_ALREADY_INGESTED_SQL, {"s": slugs})).all()
    return {r.canonical_slug for r in rows}


async def _mark_price_probe_complete(hotel_db_id: int, has_active_prices: bool) -> None:
    async with async_session_factory() as db:
        if has_active_prices:
            await mark_priced(db, hotel_db_id)
        else:
            await mark_unpriced(db, hotel_db_id)
        await db.commit()


async def _process_hotel(
    client: Any,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
) -> tuple[int, int]:
    """Fetch meta + probe a few calendar dates. Returns (hotel_seen, price_rows)."""
    await asyncio.sleep(PER_REQUEST_DELAY_S)
    meta = await fetch_hotel_meta(client, url_path, iso2)
    if meta is None:
        return (0, 0)

    # Persist meta first — even if calendar probe fails the catalog row stays.
    async with async_session_factory() as db:
        hotel_db_id = await upsert_hotel(db, meta, dest_id, operator_id)
        await upsert_mapping(db, hotel_db_id, operator_id, meta)
        await db.commit()

    # Probe the full supported check-in window for this hotel.
    all_prices = []
    seen_keys: set[str] = set()
    for offset in PROBE_OFFSETS:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        chunk = await fetch_calendar(client, meta.hotel_id, date.today() + timedelta(days=offset))
        new = [r for r in chunk if r.system_key not in seen_keys]
        all_prices.extend(new)
        seen_keys.update(r.system_key for r in new)

    if all_prices:
        async with async_session_factory() as db:
            inserted = await insert_prices(
                db, hotel_db_id, operator_id, meta, all_prices, country_iso2=iso2
            )
            if inserted > 0:
                await mark_priced(db, hotel_db_id)
            await db.commit()
        log.info(
            "sitemap.hotel.priced",
            hotel=meta.name[:50],
            hotel_key=meta.hotel_id,
            inserted=inserted,
            raw=len(all_prices),
        )
        return (1, inserted)

    log.info("sitemap.hotel.no_inventory", hotel=meta.name[:50], hotel_key=meta.hotel_id)
    await _mark_price_probe_complete(hotel_db_id, has_active_prices=False)
    return (1, 0)


async def _process_hotel_with_timeout(
    client: Any,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int]:
    # Acquire the concurrency slot before starting the per-hotel timeout so a
    # healthy hotel is not timed out merely because it sat behind the semaphore
    # in a large batch. Keep the slot for the whole active hotel-processing
    # window so CONCURRENCY remains the upstream/DB safety boundary.
    async with semaphore:
        try:
            return await asyncio.wait_for(
                _process_hotel(client, url_path, iso2, operator_id, dest_id),
                timeout=PER_HOTEL_TIMEOUT_S,
            )
        except TimeoutError:
            log.warning("sitemap.hotel.timeout", timeout_s=PER_HOTEL_TIMEOUT_S)
            return (0, 0)


async def _refresh_views() -> None:
    await refresh_price_views(log_prefix="sitemap")


async def sitemap_long_tail_ingest(cap: int | None = None) -> int:
    """Callable wrapper so the long-tail ingest can be registered as an
    APScheduler job (weekly cadence) AND invoked from CLI.

    Returns total hotels processed in this run.
    """
    return await main(cap)


async def main(cap: int | None) -> int:
    async with try_job_lock(_INGEST_LOCK_KEY, ttl_s=_INGEST_LOCK_TTL_S) as acquired:
        if not acquired:
            log.info("sitemap.skipped", reason="already_running")
            return 0
        return await _main_locked(cap)


async def _main_locked(cap: int | None) -> int:
    started_at = datetime.now(UTC)
    iso_filter = {iso2 for _, iso2 in CATALOG_COUNTRIES}

    async with async_session_factory() as db:
        operator_id = await ensure_operator(db)
        await db.commit()

    seen_hotels = 0
    inserted_prices = 0

    async with open_farvater_client() as client:
        by_iso = await list_sitemap_hotels(client, iso2_filter=iso_filter)
        total_urls = sum(len(v) for v in by_iso.values())
        log.info(
            "sitemap.discovered",
            countries=len(by_iso),
            total_urls=total_urls,
            by_country={k: len(v) for k, v in by_iso.items()},
        )

        sem = asyncio.Semaphore(CONCURRENCY)

        for iso2, paths in by_iso.items():
            async with async_session_factory() as db:
                dest_id = await country_dest_id(db, iso2)
                await db.commit()

            slugs = [make_slug(iso2, p) for p in paths]
            existing = await _already_ingested(slugs)
            fresh = [p for p, s in zip(paths, slugs, strict=False) if s not in existing]

            if cap is not None and seen_hotels + len(fresh) > cap:
                fresh = fresh[: max(0, cap - seen_hotels)]

            log.info(
                "sitemap.country.start",
                iso2=iso2,
                in_sitemap=len(paths),
                already=len(existing),
                fresh=len(fresh),
            )
            if not fresh:
                continue

            tasks = [
                _process_hotel_with_timeout(client, p, iso2, operator_id, dest_id, sem)
                for p in fresh
            ]

            # Drain in batches of ~200 to keep memory bounded and surface progress.
            batch = 200
            country_priced = 0
            for i in range(0, len(tasks), batch):
                chunk = tasks[i : i + batch]
                results = await asyncio.gather(*chunk, return_exceptions=True)
                for r in results:
                    if isinstance(r, tuple):
                        seen_hotels += r[0]
                        inserted_prices += r[1]
                        if r[1] > 0:
                            country_priced += 1
                    elif isinstance(r, Exception):
                        log.warning("sitemap.hotel.failed", error=str(r)[:200])
                log.info(
                    "sitemap.country.progress",
                    iso2=iso2,
                    processed=i + len(chunk),
                    of=len(fresh),
                    priced_country=country_priced,
                    total_priced_inserted=inserted_prices,
                    total_hotels=seen_hotels,
                )
                if cap is not None and seen_hotels >= cap:
                    break

            # Refresh MVs per-country only when this country changed price
            # rows, so no-inventory cohorts do not add avoidable MV load.
            if country_priced > 0:
                await _refresh_views()
                log.info("sitemap.country.mv_refreshed", iso2=iso2)
            else:
                log.info("sitemap.country.mv_refresh_skipped", iso2=iso2, reason="no_prices")

            if cap is not None and seen_hotels >= cap:
                log.info("sitemap.cap_reached", cap=cap)
                break

    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    log.info(
        "sitemap.done",
        total_hotels=seen_hotels,
        total_priced_rows=inserted_prices,
        elapsed_s=int(elapsed),
    )
    return seen_hotels


async def _record_sitemap_run(
    status: str,
    rows: int = 0,
    error: str = "",
    started_at: datetime | None = None,
    source: str = "sitemap_long_tail",
) -> None:
    """Record a sitemap pass outcome to scrape_runs.

    Independent of `_record_run` in snapshot_farvater because the sitemap
    ingest can fail BEFORE it ever resolves an operator_id (e.g. DNS error
    on the very first request) — so we record with `operator_id IS NULL`
    via a direct INSERT that omits the column.
    """
    try:
        async with async_session_factory() as db:
            await record_scrape_run(
                db,
                source=source,
                status=status,
                rows_inserted=rows,
                error=error,
                started_at=started_at,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Recording to scrape_runs must NEVER crash the scheduler. The
        # DB might itself be the reason this run failed.
        log.exception("sitemap_long_tail.scrape_run_record_failed", error=str(exc))


async def sitemap_long_tail_ingest_resilient(
    cap: int | None = None,
    max_attempts: int = 5,
    base_delay_s: float = 2.0,
    max_delay_s: float = 60.0,
) -> int:
    """Resilient wrapper around `sitemap_long_tail_ingest`.

    Retries on transient network errors (DNS, connect, timeout) with
    exponential backoff. On final failure, records the failure in
    `scrape_runs` and returns 0 — does NOT raise, so a failed run cannot
    crash APScheduler or take down `main()`.

    Used by both the startup one-shot resume and the daily fallback
    CronTrigger so the system self-heals from transient infra issues
    rather than waiting a week for the next Sunday tick.
    """
    started_at = datetime.now(UTC)
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await sitemap_long_tail_ingest(cap)
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            log.warning(
                "sitemap_long_tail.transient_error",
                attempt=attempt,
                max_attempts=max_attempts,
                delay_s=delay,
                error=str(exc)[:200],
            )
            if attempt < max_attempts:
                await asyncio.sleep(delay)
        except Exception as exc:  # noqa: BLE001 — record and swallow
            log.exception("sitemap_long_tail.unexpected_error", error=str(exc))
            # Outer guard: _record_sitemap_run has its own try/except but
            # if a test or runtime-replaced impl raises, we still must NOT
            # let it escape — the scheduler depends on this contract.
            try:
                await _record_sitemap_run("failed", 0, f"unexpected: {exc!s}", started_at)
            except Exception:  # noqa: BLE001
                log.exception("sitemap_long_tail.outer_record_failed")
            return 0
        else:
            log.info(
                "sitemap_long_tail.success",
                attempt=attempt,
                hotels_processed=result,
            )
            return result

    log.error(
        "sitemap_long_tail.exhausted_retries",
        attempts=max_attempts,
        last_error=str(last_exc)[:200],
    )
    try:
        await _record_sitemap_run(
            "failed",
            0,
            f"exhausted_retries after {max_attempts}: {last_exc!s}",
            started_at,
        )
    except Exception:  # noqa: BLE001
        log.exception("sitemap_long_tail.outer_record_failed")
    return 0


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(main(cap))
