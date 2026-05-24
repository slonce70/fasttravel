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

Tuned for throughput. The daily price snapshot keeps CONCURRENCY=3 /
DELAY=1s because it runs unattended every 12h. This long-tail pass is
operator-driven so it bumps both: CONCURRENCY=12 / DELAY=0.05s.

Cloudflare in front of farvater rarely rate-limits at this rate; if you
see 429s or 503s drop CONCURRENCY first, DELAY second.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.snapshot_farvater import (
    CATALOG_COUNTRIES,
    _country_dest_id,
    _ensure_operator,
    _fetch_calendar,
    _fetch_hotel_meta,
    _http_client,
    _insert_prices,
    _list_sitemap_hotels,
    _make_slug,
    _mark_priced,
    _upsert_hotel,
    _upsert_mapping,
)

log = get_logger(__name__)

# Aggressive operator-driven tuning. See module docstring.
CONCURRENCY = 12
PER_REQUEST_DELAY_S = 0.05
# We probe a *subset* of CHECK_IN_OFFSETS_DAYS during the long-tail pass
# to keep the per-hotel cost down. Hotels we want full coverage on get
# revisited by the regular snapshot_farvater the next morning.
PROBE_OFFSETS = [14, 30, 60]
SCRAPE_SOURCE = "catalog_sitemap"


async def _already_ingested(slugs: list[str]) -> set[str]:
    if not slugs:
        return set()
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text("SELECT canonical_slug FROM hotels WHERE canonical_slug = ANY(:s)"),
                {"s": slugs},
            )
        ).all()
    return {r.canonical_slug for r in rows}


async def _process_hotel(
    client,
    url_path: str,
    iso2: str,
    operator_id: int,
    dest_id: int | None,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int]:
    """Fetch meta + probe a few calendar dates. Returns (hotel_seen, price_rows)."""
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await _fetch_hotel_meta(client, url_path, iso2)
        if meta is None:
            return (0, 0)

        # Persist meta first — even if calendar probe fails the catalog row stays.
        async with async_session_factory() as db:
            hotel_db_id = await _upsert_hotel(db, meta, dest_id)
            await _upsert_mapping(db, hotel_db_id, operator_id, meta)
            await db.commit()

        # Probe a small set of check-in dates. PROBE_OFFSETS skips offsets
        # the daily snapshot already covers densely (3, 45, 75) so we
        # broaden coverage without exact duplication.
        all_prices = []
        seen_keys: set[str] = set()
        for offset in PROBE_OFFSETS:
            await asyncio.sleep(PER_REQUEST_DELAY_S)
            chunk = await _fetch_calendar(
                client, meta.hotel_id, date.today() + timedelta(days=offset)
            )
            new = [r for r in chunk if r.system_key not in seen_keys]
            all_prices.extend(new)
            seen_keys.update(r.system_key for r in new)

    if all_prices:
        async with async_session_factory() as db:
            inserted = await _insert_prices(db, hotel_db_id, operator_id, meta, all_prices)
            if inserted > 0:
                await _mark_priced(db, hotel_db_id)
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
    return (1, 0)


async def _refresh_views() -> None:
    async with async_session_factory() as db:
        for mv in ("current_prices", "hotel_calendar_prices", "price_baselines"):
            try:
                await db.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))
            except Exception as exc:
                log.warning("sitemap.mv_refresh_failed", mv=mv, error=str(exc))
        await db.commit()


async def sitemap_long_tail_ingest(cap: int | None = None) -> int:
    """Callable wrapper so the long-tail ingest can be registered as an
    APScheduler job (weekly cadence) AND invoked from CLI.

    Returns total hotels processed in this run.
    """
    return await main(cap)


async def main(cap: int | None) -> int:
    started_at = datetime.now(UTC)
    iso_filter = {iso2 for _, iso2 in CATALOG_COUNTRIES}

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    seen_hotels = 0
    inserted_prices = 0

    async with _http_client() as client:
        by_iso = await _list_sitemap_hotels(client, iso2_filter=iso_filter)
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
                dest_id = await _country_dest_id(db, iso2)

            slugs = [_make_slug(iso2, p) for p in paths]
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

            tasks = [_process_hotel(client, p, iso2, operator_id, dest_id, sem) for p in fresh]

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

            # Refresh MVs per-country so the UI starts showing the new
            # priced cohort as the run progresses, not only at the end.
            await _refresh_views()
            log.info("sitemap.country.mv_refreshed", iso2=iso2)

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


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(main(cap))
