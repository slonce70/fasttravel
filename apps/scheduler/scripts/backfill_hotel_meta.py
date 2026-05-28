"""One-off backfill: refetch gallery + JSON-LD for hotels we already have.

Hotels ingested before the gallery/review/JSON-LD extractors landed are
stuck on a single og:image and no review data. This script walks every
active hotel with `photos_jsonb` shorter than 5 entries (or no review_score)
and re-runs `_fetch_hotel_meta + upsert_hotel`.

Run from inside the scheduler container:

    docker exec -w /app ft_scheduler python scripts/backfill_hotel_meta.py [LIMIT]

Throttled to the same `PER_REQUEST_DELAY_S` the regular scraper uses.
Safe to re-run — the upsert is idempotent and the photo column never
shrinks (see `upsert_hotel`).
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.snapshot_farvater import (
    PER_REQUEST_DELAY_S,
    _fetch_hotel_meta,
    _http_client,
)
from src.services.hotel_upsert import country_dest_id, ensure_operator, upsert_hotel, upsert_mapping

log = get_logger(__name__)


_TARGET_SQL = text(
    """
    SELECT h.id, h.canonical_slug, d.country_iso2
    FROM hotels h
    LEFT JOIN destinations d ON d.id = h.destination_id
    WHERE h.is_active
      AND (
        h.photos_jsonb IS NULL
        OR jsonb_array_length(h.photos_jsonb) < 5
        OR h.review_score IS NULL
      )
    ORDER BY h.has_active_prices DESC, h.id
    LIMIT :lim
    """
)


def _path_from_slug(slug: str, iso2: str | None) -> str | None:
    # fv-tr-belport-beach-hotel → /uk/hotel/tr/belport-beach-hotel/
    parts = slug.split("-", 2)
    if len(parts) != 3 or parts[0] != "fv":
        return None
    country = (iso2 or parts[1]).lower()
    return f"/uk/hotel/{country}/{parts[2]}/"


async def main(limit: int) -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(_TARGET_SQL, {"lim": limit})).all()
        operator_id = await ensure_operator(db)
        await db.commit()

    log.info("backfill.start", targets=len(rows))
    fetched = 0
    updated = 0
    async with _http_client() as client:
        for row in rows:
            path = _path_from_slug(row.canonical_slug, row.country_iso2)
            if not path:
                continue
            await asyncio.sleep(PER_REQUEST_DELAY_S)
            meta = await _fetch_hotel_meta(client, path, (row.country_iso2 or "").upper())
            fetched += 1
            if meta is None:
                continue
            async with async_session_factory() as db:
                dest_id = await country_dest_id(db, meta.country_iso2)
                await upsert_hotel(db, meta, dest_id, operator_id)
                await upsert_mapping(db, row.id, operator_id, meta)
                await db.commit()
            updated += 1
            if fetched % 25 == 0:
                log.info(
                    "backfill.progress",
                    fetched=fetched,
                    updated=updated,
                    last_slug=row.canonical_slug,
                )

    log.info("backfill.done", fetched=fetched, updated=updated)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    asyncio.run(main(limit))
