"""Daily price_baselines materialized view refresh.

Extracted from snapshot_farvater's tail MV-refresh block (Sprint 1F)
because `price_baselines` has NO unique index — it CANNOT be refreshed
CONCURRENTLY. Running it inline with the snapshot meant taking
`AccessExclusiveLock` twice a day during business hours, blocking
every `/search`, `/calendar`, and `/deals` request for the duration
(seconds at MVP scale, growing linearly with priced cohort).

Splitting it into its own off-peak job — 04:15 Kyiv, right after
`decay_active_prices` (04:00) and before `cleanup_partitions` (04:30)
— keeps the locked window outside business hours. The MV doesn't
need to refresh more than once a day for detect_deals to stay
accurate: the percentile baselines are a 60-day rolling window so a
single late-night refresh is enough.

`current_prices` and `hotel_calendar_prices` stay in snapshot_farvater
(they have unique indexes → CONCURRENTLY refresh, no lock).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger

log = get_logger(__name__)


async def _record_run(started_at: datetime, status: str, error: str = "") -> None:
    try:
        async with async_session_factory() as db:
            await db.execute(
                text(
                    """INSERT INTO scrape_runs
                         (started_at, finished_at, source, status,
                          rows_inserted, error_text)
                       VALUES (:s, NOW(), 'refresh_baselines', :st, 0, :e)"""
                ),
                {"s": started_at, "st": status, "e": error[:500]},
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("refresh_baselines.record_failed", error=str(exc))


async def refresh_baselines() -> int:
    """REFRESH MATERIALIZED VIEW price_baselines (non-CONCURRENT).

    Returns 0 on success (no row count to report — the MV refresh is
    blanket); raises only if the DB itself errors out, never on the
    "view is locked" condition (we ARE the only writer at 04:15).
    """
    started_at = datetime.now(UTC)
    try:
        async with async_session_factory() as db:
            await db.execute(text("REFRESH MATERIALIZED VIEW price_baselines"))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("refresh_baselines.failed", error=str(exc))
        await _record_run(started_at, "failed", str(exc))
        raise

    await _record_run(started_at, "success")
    log.info("refresh_baselines.done")
    return 0
