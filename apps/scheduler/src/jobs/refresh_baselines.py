"""Daily price_baselines materialized view refresh.

Extracted from snapshot_farvater's tail MV-refresh block (Sprint 1F)
because `price_baselines` has NO unique index — it CANNOT be refreshed
CONCURRENTLY. Running it inline with the snapshot meant taking
`AccessExclusiveLock` twice a day during business hours, blocking
every `/search`, `/calendar`, and `/deals` request for the duration
(seconds at MVP scale, growing linearly with priced cohort).

Splitting it into its own off-peak job — 04:15 Kyiv, right after
`decay_active_prices` (04:00) and before `cleanup_partitions` (04:30)
— keeps the locked window outside business hours. The MV is now a legacy /
analysis compatibility surface; active `detect_deals` reads same-hotel
nearby-date stats from `current_prices`, so percentile baselines no longer
drive Telegram deal detection.

`current_prices` and `hotel_calendar_prices` stay in snapshot_farvater
(they have unique indexes → CONCURRENTLY refresh, no lock).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.services.scrape_runs import record_scrape_run

log = get_logger(__name__)


async def _record_run(started_at: datetime, status: str, error: str = "") -> None:
    try:
        async with async_session_factory() as db:
            await record_scrape_run(
                db,
                source="refresh_baselines",
                status=status,
                rows_inserted=0,
                error=error,
                started_at=started_at,
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
