"""Daily search-gate decay job.

Extracted from snapshot_farvater (Sprint 1F) so the gate stays honest
even when the snapshot itself fails. Before this extraction, if the
twice-daily snapshot raised — DNS, Cloudflare 403, anything — the
inline decay would never run, and `has_active_prices=TRUE` rows whose
prices had aged past 7 days would still surface in /search.

The job is intentionally tiny — one UPDATE — so it never times out
even on full table sweeps. Runs at 04:00 Kyiv, before
`refresh_baselines` (04:15) and `cleanup_partitions` (04:30).

Threshold defaults to 7 days — matches the inline behaviour the job
replaced. Configurable via env DECAY_STALE_AFTER_DAYS if a launch needs
to tighten it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from src.infra.db import async_session_factory
from src.infra.logging import get_logger
from src.services import price_state
from src.services.scrape_runs import record_scrape_run

log = get_logger(__name__)


def _stale_after_days() -> int:
    raw = os.getenv("DECAY_STALE_AFTER_DAYS", "7")
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("decay_active_prices.bad_env", raw=raw, fallback=7)
        return 7


async def _record_run(started_at: datetime, status: str, rows: int, error: str = "") -> None:
    """scrape_runs row for one decay pass — same pattern as snapshot_farvater."""
    try:
        async with async_session_factory() as db:
            await record_scrape_run(
                db,
                source="decay_active_prices",
                status=status,
                rows_inserted=rows,
                error=error,
                started_at=started_at,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("decay_active_prices.record_failed", error=str(exc))


async def decay_active_prices() -> int:
    """Demote stale `has_active_prices=TRUE` rows to FALSE.

    Returns rows demoted. Raises on failure — after recording the
    scrape_runs row — so `track_job_metrics` counts outcome="failure"
    instead of masking a broken decay as success. A raising APScheduler
    job does not affect other scheduled jobs.
    """
    started_at = datetime.now(UTC)
    threshold = _stale_after_days()

    try:
        async with async_session_factory() as db:
            demoted = await price_state.decay_active_prices(db, threshold)
            await db.commit()
    except Exception as exc:
        log.exception("decay_active_prices.failed", error=str(exc))
        await _record_run(started_at, "failed", 0, str(exc))
        raise

    await _record_run(started_at, "success", demoted)
    log.info("decay_active_prices.done", demoted=demoted, threshold_days=threshold)
    return demoted
