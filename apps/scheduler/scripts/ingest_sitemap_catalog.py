"""One-off long-tail catalog ingest from farvater's sitemap.

The daily `snapshot_catalog_farvater` walks `/uk/hotelscatalog/strana-X/`
which exposes only farvater's curated top ~67 hotels per country. The
sitemap holds the long tail — ~420k URLs across 9 shards, of which
~57k belong to our 11 target countries.

Run from inside the scheduler container:

    docker exec -d -w /app ft_scheduler python scripts/ingest_sitemap_catalog.py

Throttled to `PER_REQUEST_DELAY_S` (1s by default). Skips hotels already
ingested (matched on `canonical_slug`) so re-running is cheap. Records
progress to `scrape_runs` with source='catalog_sitemap'.

Expected runtime for 57k new URLs: ~16 hours wall clock with concurrency=3.
Safe to interrupt — only completed hotels persist. On restart, the slug
dedup means previously-fetched hotels are skipped.

Pass an integer arg to cap (`python scripts/ingest_sitemap_catalog.py 500`).
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.snapshot_catalog_farvater import (
    CONCURRENCY,
    PER_REQUEST_DELAY_S,
    SCRAPE_SOURCE as _DAILY_SOURCE,
    _process_catalog_hotel,
    _record_run,
)
from src.jobs.snapshot_farvater import (
    CATALOG_COUNTRIES,
    _country_dest_id,
    _ensure_operator,
    _http_client,
    _list_sitemap_hotels,
    _make_slug,
)

log = get_logger(__name__)

SCRAPE_SOURCE = "catalog_sitemap"


async def _already_ingested(canonical_slugs: list[str]) -> set[str]:
    if not canonical_slugs:
        return set()
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text("SELECT canonical_slug FROM hotels WHERE canonical_slug = ANY(:s)"),
                {"s": canonical_slugs},
            )
        ).all()
    return {r.canonical_slug for r in rows}


async def main(cap: int | None) -> None:
    started_at = datetime.now(UTC)
    iso_filter = {iso2 for _, iso2 in CATALOG_COUNTRIES}

    async with async_session_factory() as db:
        operator_id = await _ensure_operator(db)
        await db.commit()

    total_seen = 0
    try:
        async with _http_client() as client:
            by_iso = await _list_sitemap_hotels(client, iso2_filter=iso_filter)
            total_urls = sum(len(v) for v in by_iso.values())
            log.info("sitemap.discovered", countries=len(by_iso),
                     total_urls=total_urls, by_country={k: len(v) for k, v in by_iso.items()})

            sem = asyncio.Semaphore(CONCURRENCY)

            for iso2, paths in by_iso.items():
                async with async_session_factory() as db:
                    dest_id = await _country_dest_id(db, iso2)

                # Skip hotels we already have. Cheap O(N) batched query.
                slugs = [_make_slug(iso2, p) for p in paths]
                existing = await _already_ingested(slugs)
                fresh = [
                    p for p, s in zip(paths, slugs) if s not in existing
                ]
                if cap is not None and total_seen + len(fresh) > cap:
                    fresh = fresh[: max(0, cap - total_seen)]

                log.info("sitemap.country.start", iso2=iso2,
                         in_sitemap=len(paths), already=len(existing), fresh=len(fresh))
                if not fresh:
                    continue

                tasks = [
                    _process_catalog_hotel(client, p, iso2, operator_id, dest_id, sem)
                    for p in fresh
                ]
                # Drain in batches so a single shard's failures don't tank everything.
                batch = 50
                seen_country = 0
                for i in range(0, len(tasks), batch):
                    chunk = tasks[i:i + batch]
                    results = await asyncio.gather(*chunk, return_exceptions=True)
                    seen_country += sum(r for r in results if isinstance(r, int))
                    total_seen += sum(r for r in results if isinstance(r, int))
                    log.info("sitemap.country.progress", iso2=iso2,
                             processed=i + len(chunk), of=len(fresh),
                             seen_country=seen_country, total=total_seen)
                    if cap is not None and total_seen >= cap:
                        break

                if cap is not None and total_seen >= cap:
                    log.info("sitemap.cap_reached", cap=cap)
                    break

        async with async_session_factory() as db:
            await _record_run(db, operator_id, "success", total_seen, started_at=started_at)
            # Override the run row's source after insert so dashboards split
            # the long-tail ingest from the daily catalog pass.
            await db.execute(
                text(
                    """UPDATE scrape_runs SET source = :src
                       WHERE source = :old AND started_at = :s"""
                ),
                {"src": SCRAPE_SOURCE, "old": _DAILY_SOURCE, "s": started_at},
            )
            await db.commit()
        log.info("sitemap.done", total=total_seen)

    except Exception as exc:
        async with async_session_factory() as db:
            await _record_run(db, operator_id, "failed", total_seen,
                              error=str(exc), started_at=started_at)
            await db.commit()
        log.error("sitemap.failed", error=str(exc))
        raise


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(main(cap))
