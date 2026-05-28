"""Repair Farvater hotel names already polluted by old title parsing.

The old parser treated any ``Hotel ...`` substring as SEO boilerplate, so
names like ``Antik Butik (ex. Antik Hotel & Garden)`` became ``& Garden)``.
This one-off script refetches suspicious Farvater hotel pages, extracts the
real H1/title with the fixed parser, and updates hotels, mapping names and
photo alts through the normal upsert path.

Run from the scheduler container:

    python scripts/repair_farvater_hotel_names.py [LIMIT] [CONCURRENCY] [RECENT_MINUTES]
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import httpx
from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.jobs.snapshot_farvater import (
    _fetch_hotel_meta,
    _http_client,
)
from src.services.hotel_upsert import country_dest_id, ensure_operator, upsert_hotel, upsert_mapping

log = get_logger(__name__)


_TARGET_SQL = text(
    """
    SELECT h.id, h.canonical_slug, COALESCE(d.country_iso2, UPPER(split_part(h.canonical_slug, '-', 2))) AS country_iso2
    FROM hotels h
    LEFT JOIN hotel_operator_mapping m
      ON m.hotel_id = h.id
     AND m.operator_id = :operator_id
    LEFT JOIN destinations d ON d.id = h.destination_id
    WHERE h.is_active
      AND h.canonical_slug LIKE 'fv-%'
      AND (
        h.name_uk ~ '^[&),. ]'
        OR h.name_en ~ '^[&),. ]'
        OR COALESCE(m.external_name, '') ~ '^[&),. ]'
        OR h.name_uk ~ '[[:space:]][1-5]\\*$'
        OR h.name_en ~ '[[:space:]][1-5]\\*$'
        OR COALESCE(m.external_name, '') ~ '[[:space:]][1-5]\\*$'
        OR h.photos_jsonb::text ~ '"alt"\\s*:\\s*"[&),. ]'
        OR (:recent_minutes > 0 AND h.last_updated >= NOW() - (:recent_minutes || ' minutes')::interval)
      )
    ORDER BY h.has_active_prices DESC, h.id
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class Target:
    hotel_id: int
    slug: str
    country_iso2: str


def _path_from_slug(slug: str, iso2: str) -> str | None:
    parts = slug.split("-", 2)
    if len(parts) != 3 or parts[0] != "fv":
        return None
    return f"/uk/hotel/{iso2.lower()}/{parts[2]}/"


async def _load_targets(limit: int, operator_id: int, recent_minutes: int) -> list[Target]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                _TARGET_SQL,
                {
                    "operator_id": operator_id,
                    "limit": limit,
                    "recent_minutes": recent_minutes,
                },
            )
        ).all()
    return [Target(row.id, row.canonical_slug, row.country_iso2) for row in rows]


async def _repair_target(client: httpx.AsyncClient, target: Target, operator_id: int) -> bool:
    path = _path_from_slug(target.slug, target.country_iso2)
    if not path:
        log.warning("repair_names.bad_slug", hotel_id=target.hotel_id, slug=target.slug)
        return False

    meta = await _fetch_hotel_meta(client, path, target.country_iso2)
    if meta is None:
        return False

    async with async_session_factory() as db:
        dest_id = await country_dest_id(db, meta.country_iso2)
        hotel_id = await upsert_hotel(db, meta, dest_id, operator_id)
        await upsert_mapping(db, hotel_id, operator_id, meta)
        if hotel_id != target.hotel_id:
            await db.execute(
                text(
                    """INSERT INTO hotel_slug_aliases (source_slug, hotel_id, reason)
                       VALUES (:slug, :hotel_id, 'farvater_redirect_duplicate')
                       ON CONFLICT (source_slug) DO UPDATE
                       SET hotel_id = EXCLUDED.hotel_id,
                           reason = EXCLUDED.reason"""
                ),
                {"slug": target.slug, "hotel_id": hotel_id},
            )
            await db.execute(text("DELETE FROM hotels WHERE id = :id"), {"id": target.hotel_id})
        await db.commit()
    return True


async def main(limit: int, concurrency: int, recent_minutes: int) -> None:
    async with async_session_factory() as db:
        operator_id = await ensure_operator(db)
        await db.commit()

    targets = await _load_targets(limit, operator_id, recent_minutes)
    log.info(
        "repair_names.start",
        targets=len(targets),
        concurrency=concurrency,
        recent_minutes=recent_minutes,
    )
    queue: asyncio.Queue[Target] = asyncio.Queue()
    for target in targets:
        queue.put_nowait(target)

    repaired = 0
    failed = 0
    lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        nonlocal repaired, failed
        async with _http_client() as client:
            while True:
                try:
                    target = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    ok = await _repair_target(client, target, operator_id)
                except Exception as exc:
                    log.warning(
                        "repair_names.target_failed",
                        worker_id=worker_id,
                        hotel_id=target.hotel_id,
                        slug=target.slug,
                        error=str(exc),
                    )
                    ok = False
                async with lock:
                    if ok:
                        repaired += 1
                    else:
                        failed += 1
                    done = repaired + failed
                    if done % 50 == 0 or done == len(targets):
                        log.info(
                            "repair_names.progress",
                            done=done,
                            repaired=repaired,
                            failed=failed,
                            remaining=queue.qsize(),
                        )
                queue.task_done()

    await asyncio.gather(*(worker(i + 1) for i in range(max(1, concurrency))))
    log.info("repair_names.done", repaired=repaired, failed=failed)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    recent_minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    asyncio.run(main(limit, concurrency, recent_minutes))
