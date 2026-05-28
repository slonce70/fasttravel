"""Refresh online price materialized views.

Order is meaningful: ``hotel_calendar_prices`` SELECTs FROM
``current_prices`` (see migration 001), so the shared helper refreshes
``current_prices`` first to avoid serving a one-cycle-stale calendar.

``price_baselines`` is intentionally excluded here: it has no unique index
and is refreshed by the off-peak ``refresh_baselines`` job.
"""

from __future__ import annotations

from src.infra.logging import get_logger
from src.services.materialized_views import refresh_price_views

log = get_logger(__name__)


async def refresh_views() -> None:
    results = await refresh_price_views(log_prefix="refresh_views")
    log.info("refresh_views.completed", **results)
