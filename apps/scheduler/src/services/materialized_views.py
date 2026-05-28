"""Shared materialized-view refresh helpers for scheduler jobs."""

from __future__ import annotations

from asyncpg.exceptions import ObjectNotInPrerequisiteStateError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.infra.db import async_engine
from src.infra.logging import get_logger

log = get_logger(__name__)

PRICE_REFRESH_VIEWS: tuple[str, ...] = (
    "current_prices",
    "hotel_calendar_prices",
)


def _is_unpopulated_view_error(exc: Exception) -> bool:
    return isinstance(exc, DBAPIError) and isinstance(
        exc.orig,
        ObjectNotInPrerequisiteStateError,
    )


async def refresh_materialized_views(
    views: tuple[str, ...],
    *,
    concurrently: bool = True,
    fallback_to_blocking: bool = True,
    log_prefix: str = "materialized_views",
) -> dict[str, str]:
    """Refresh materialized views in order and return per-view mode."""
    results: dict[str, str] = {}
    async with async_engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in views:
            try:
                mode = "CONCURRENTLY " if concurrently else ""
                await ac.execute(text(f"REFRESH MATERIALIZED VIEW {mode}{view}"))
                results[view] = "concurrent" if concurrently else "blocking"
            except Exception as exc:
                if not (concurrently and fallback_to_blocking and _is_unpopulated_view_error(exc)):
                    raise
                log.warning(
                    f"{log_prefix}.fallback_blocking",
                    view=view,
                    reason="mv_not_populated",
                )
                await ac.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
                results[view] = "blocking"
    return results


async def refresh_price_views(
    *,
    fallback_to_blocking: bool = True,
    log_prefix: str = "materialized_views",
) -> dict[str, str]:
    """Refresh price-serving MVs, excluding off-peak price_baselines."""
    return await refresh_materialized_views(
        PRICE_REFRESH_VIEWS,
        concurrently=True,
        fallback_to_blocking=fallback_to_blocking,
        log_prefix=log_prefix,
    )
