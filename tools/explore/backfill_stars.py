"""One-shot backfill: populate `hotels.stars` for every existing fv-* row
by re-fetching the farvater hotel page and re-running the same star
extractor used by the live snapshot job.

This is the one-time companion to the regex added in
`apps/scheduler/src/jobs/snapshot_farvater.py` — once the live snapshot
has run a few times it will keep stars current via COALESCE, but the
~652 hotels already in the DB were inserted with `stars=NULL` and need
a single sweep to catch up.

Reconstructs the hotel URL from the canonical slug:
    `fv-eg-pickalbatros-vita-resort-portofino`
        → `/uk/hotel/eg/pickalbatros-vita-resort-portofino/`

Run from inside the scheduler container so it shares the same network +
config + Python deps as the snapshot job:

    docker compose exec -T scheduler python -m tools.explore.backfill_stars

The script is idempotent — it skips hotels that already have stars set,
and the COALESCE in the UPDATE makes re-runs safe.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the scheduler's `src.*` package importable regardless of where this
# file lives. Two supported invocation contexts:
#   * repo host:  `python tools/explore/backfill_stars.py` — needs the
#                 apps/scheduler dir on sys.path.
#   * container:  `python /tmp/backfill_stars.py` — `/app` is already on
#                 sys.path so `src.*` imports work as-is; the path probe
#                 below is a best-effort no-op.
try:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "apps" / "scheduler"
        if candidate.is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break
except Exception:
    pass

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.infra.db import async_session_factory  # noqa: E402
from src.infra.logging import get_logger  # noqa: E402
from src.jobs.snapshot_farvater import (  # noqa: E402
    CONCURRENCY,
    PER_REQUEST_DELAY_S,
    USER_AGENT,
    _fetch_hotel_meta,
)

log = get_logger(__name__)


def _slug_to_url_path(slug: str) -> str | None:
    """`fv-eg-pickalbatros-vita-resort-portofino`
        → `/uk/hotel/eg/pickalbatros-vita-resort-portofino/`

    Returns None if the slug doesn't match the fv-{iso2}-{tail} shape.
    """
    if not slug.startswith("fv-"):
        return None
    rest = slug[3:]
    # iso2 is 2 letters (we never store 3-letter iso codes for farvater)
    if len(rest) < 4 or rest[2] != "-":
        return None
    iso2 = rest[:2]
    tail = rest[3:]
    if not iso2.isalpha() or not tail:
        return None
    return f"/uk/hotel/{iso2}/{tail}/"


async def _load_targets() -> list[tuple[int, str, str]]:
    """Return (hotel_id, canonical_slug, iso2) for every fv-* hotel that
    still has stars=NULL."""
    async with async_session_factory() as db:
        rows = (await db.execute(
            text("""SELECT id, canonical_slug
                    FROM hotels
                    WHERE canonical_slug LIKE 'fv-%'
                      AND stars IS NULL
                    ORDER BY id""")
        )).all()
    out: list[tuple[int, str, str]] = []
    for hid, slug in rows:
        url_path = _slug_to_url_path(slug)
        if not url_path:
            log.warning("backfill.bad_slug", slug=slug)
            continue
        iso2 = slug.split("-", 2)[1].upper()
        out.append((hid, slug, iso2))
    return out


async def _backfill_one(client: httpx.AsyncClient,
                        hotel_db_id: int, slug: str, iso2: str,
                        semaphore: asyncio.Semaphore,
                        counters: dict[str, int]) -> None:
    url_path = _slug_to_url_path(slug)
    assert url_path is not None  # guarded in _load_targets
    async with semaphore:
        await asyncio.sleep(PER_REQUEST_DELAY_S)
        meta = await _fetch_hotel_meta(client, url_path, iso2)
    if meta is None:
        counters["fetch_failed"] += 1
        return
    if meta.stars is None:
        counters["no_stars"] += 1
        return
    async with async_session_factory() as db:
        # COALESCE keeps this safe even if a concurrent snapshot wrote a
        # value between our read and our write.
        await db.execute(
            text("""UPDATE hotels
                    SET stars = COALESCE(stars, :s),
                        last_updated = NOW()
                    WHERE id = :id"""),
            {"s": meta.stars, "id": hotel_db_id},
        )
        await db.commit()
    counters["updated"] += 1
    if counters["updated"] % 25 == 0:
        log.info("backfill.progress", **counters)


async def backfill_stars() -> dict[str, int]:
    targets = await _load_targets()
    log.info("backfill.start", candidates=len(targets),
             concurrency=CONCURRENCY)
    counters = {"updated": 0, "no_stars": 0, "fetch_failed": 0}
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        await asyncio.gather(*[
            _backfill_one(client, hid, slug, iso2, semaphore, counters)
            for hid, slug, iso2 in targets
        ])
    log.info("backfill.done", **counters)
    return counters


if __name__ == "__main__":
    asyncio.run(backfill_stars())
