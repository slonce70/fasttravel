"""Refresh the three FastTravel materialized views.

Order is meaningful: ``hotel_calendar_prices`` SELECTs FROM
``current_prices`` (see migration 001), so we refresh ``current_prices``
first to avoid serving a one-cycle-stale calendar.

CONCURRENTLY needs:
  - a unique index on the MV (migration 001 has those), AND
  - the MV to already be populated at least once.

ADR-011 documents that MVs are created ``WITH NO DATA`` — so on a fresh
cluster the very first refresh has to be non-concurrent. We catch the
specific Postgres errcode rather than bare Exception so genuinely
broken SQL still surfaces.
"""

from __future__ import annotations

from asyncpg.exceptions import ObjectNotInPrerequisiteStateError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)

# Order matters — see module docstring.
_VIEWS: tuple[str, ...] = (
    "current_prices",
    "hotel_calendar_prices",
    "price_baselines",
)


async def _refresh_one(view: str) -> str:
    """Refresh a single MV. Returns ``"concurrent"`` or ``"blocking"``."""
    async with async_session_factory() as db:
        try:
            await db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
            await db.commit()
            return "concurrent"
        except DBAPIError as exc:
            # ObjectNotInPrerequisiteStateError == "MV has not been
            # populated", which is the documented first-refresh case
            # (ADR-011). Anything else we let bubble up.
            if not isinstance(exc.orig, ObjectNotInPrerequisiteStateError):
                raise
            await db.rollback()
            log.warning(
                "refresh_views.fallback_blocking",
                view=view,
                reason="mv_not_populated",
                note="ADR-011 first-refresh case; subsequent refreshes will go CONCURRENTLY",
            )

    # Second pass — non-concurrent. New session because the previous one
    # is in an aborted state after the failed COMMIT.
    async with async_session_factory() as db:
        await db.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
        await db.commit()
    return "blocking"


async def refresh_views() -> None:
    results: dict[str, str] = {}
    for view in _VIEWS:
        results[view] = await _refresh_one(view)
    log.info("refresh_views.completed", **results)
