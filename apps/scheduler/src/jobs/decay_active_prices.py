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
from typing import Any, cast

from sqlalchemy import text

from src.infra.db import async_session_factory
from src.infra.logging import get_logger

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
            await db.execute(
                text(
                    """INSERT INTO scrape_runs
                         (started_at, finished_at, source, status,
                          rows_inserted, error_text)
                       VALUES (:s, NOW(), 'decay_active_prices', :st, :n, :e)"""
                ),
                {"s": started_at, "st": status, "n": rows, "e": error[:500]},
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("decay_active_prices.record_failed", error=str(exc))


async def decay_active_prices() -> int:
    """Demote stale `has_active_prices=TRUE` rows to FALSE.

    Returns rows demoted. Never raises — the scheduler depends on the
    daily decay running even when the DB itself wobbles.
    """
    started_at = datetime.now(UTC)
    threshold = _stale_after_days()

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(
                    """UPDATE hotels
                       SET has_active_prices = FALSE
                       WHERE has_active_prices = TRUE
                         AND (last_priced_at IS NULL
                              OR last_priced_at < NOW()
                                 - make_interval(days => :d))"""
                ),
                {"d": threshold},
            )
            await db.commit()
            demoted = int(cast(Any, result).rowcount or 0)
    except Exception as exc:  # noqa: BLE001
        log.exception("decay_active_prices.failed", error=str(exc))
        await _record_run(started_at, "failed", 0, str(exc))
        return 0

    await _record_run(started_at, "success", demoted)
    log.info("decay_active_prices.done", demoted=demoted, threshold_days=threshold)
    return demoted
