"""Scheduler entrypoint — wires AsyncIOScheduler to all periodic jobs.

Schedule (Europe/Kyiv):
- snapshot_stub             — 04:00 (price ingest placeholder until clients ship)
- snapshot_catalog_farvater — 03:00 (P1-1: catalog HTML-only daily crawl)
- snapshot_farvater         — 06:00 / 18:00 (full catalog+price snapshot)
- snapshot_hot              — hourly :30 (P1-3: top-N viewed → refresh queue)
- refresh_views             — hourly :05
- detect_deals              — hourly :10
- post_deals                — every 15 min
- cleanup_partitions        — daily at 03:00 (NB: shares slot with catalog;
                              both are idempotent and partman is cheap)

Plus a long-running async task:
- refresh_worker_loop       — drains `refresh:queue` via BRPOP (P1-4)

Single-process for MVP. When the workload grows we split each job into
its own container (or move heavy ingest jobs to a dedicated worker pool).
Until then, APScheduler with a memory job store keeps the moving parts
to a minimum.
"""
from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.infra.logging import get_logger
from src.jobs import (
    cleanup_partitions,
    detect_deals,
    post_deals,
    refresh_views,
    refresh_worker_loop,
    snapshot_catalog_farvater,
    snapshot_farvater,
    snapshot_hot,
    snapshot_stub,
)

log = get_logger(__name__)

TIMEZONE = "Europe/Kyiv"

# Job concurrency is 1 by default — these jobs are idempotent but each
# touches the same MVs / deals table, so serialising avoids lock noise.
_JOB_DEFAULTS = {
    "coalesce": True,        # if app catches up, run once for the missed window
    "max_instances": 1,
    "misfire_grace_time": 60 * 5,
}


def _build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE, job_defaults=_JOB_DEFAULTS)

    # Live farvater.travel ingest — pulls real prices for ~600 hotels across
    # 11 countries twice daily (06:00 + 18:00 Kyiv). Stub remains registered
    # under a separate id so we can A/B against the placeholder logs.
    scheduler.add_job(
        snapshot_farvater,
        CronTrigger(hour="6,18", minute=0, timezone=TIMEZONE),
        id="snapshot_farvater",
        name="snapshot_farvater (06:00 + 18:00 Kyiv)",
    )
    # Catalog-only HTML refresh — runs daily before the price job, keeps
    # `hotels.last_seen_at` fresh across the whole catalog without paying
    # for per-hotel price calendar POSTs.
    scheduler.add_job(
        snapshot_catalog_farvater,
        CronTrigger(hour=3, minute=0, timezone=TIMEZONE),
        id="snapshot_catalog_farvater",
        name="snapshot_catalog_farvater (daily 03:00 Kyiv)",
    )
    scheduler.add_job(
        snapshot_stub,
        CronTrigger(hour=4, minute=0, timezone=TIMEZONE),
        id="snapshot_stub",
        name="snapshot_stub (04:00 Kyiv heartbeat — telemetry only)",
    )

    # Refresh MVs first, then detect deals, then post — chained on the hour.
    scheduler.add_job(
        refresh_views,
        CronTrigger(minute=5, timezone=TIMEZONE),
        id="refresh_views",
        name="refresh_views (hourly :05)",
    )
    scheduler.add_job(
        detect_deals,
        CronTrigger(minute=10, timezone=TIMEZONE),
        id="detect_deals",
        name="detect_deals (hourly :10)",
    )
    # Hot-priority sweep — runs at :30 so it doesn't collide with the
    # MV refresh (:05) or the deal detector (:10). Pushes top-N viewed
    # hotels onto `refresh:queue` for the worker to drain.
    scheduler.add_job(
        snapshot_hot,
        CronTrigger(minute=30, timezone=TIMEZONE),
        id="snapshot_hot",
        name="snapshot_hot (hourly :30)",
    )
    scheduler.add_job(
        post_deals,
        IntervalTrigger(minutes=15, timezone=TIMEZONE),
        id="post_deals",
        name="post_deals (every 15 min)",
    )

    # Daily housekeeping — drop partitions older than retention (pg_partman
    # config set in migration 001 via partman.part_config).
    scheduler.add_job(
        cleanup_partitions,
        CronTrigger(hour=3, minute=0, timezone=TIMEZONE),
        id="cleanup_partitions",
        name="cleanup_partitions (daily 03:00 Kyiv)",
    )

    return scheduler


async def main() -> None:
    scheduler = _build_scheduler()
    scheduler.start()

    jobs = [(j.id, str(j.next_run_time)) for j in scheduler.get_jobs()]
    log.info("scheduler.started", timezone=TIMEZONE, jobs=jobs)

    # Spawn the persistent refresh worker (P1-4). It's not a cron job —
    # it BRPOPs `refresh:queue` continuously so user-triggered refreshes
    # survive an API restart and don't depend on FastAPI's BackgroundTasks.
    worker_task = asyncio.create_task(
        refresh_worker_loop(), name="refresh_worker_loop"
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("scheduler.stopping")
        # Cancel the worker first so an in-flight BRPOP unblocks cleanly
        # before we tear down the scheduler.
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
            if not isinstance(exc, asyncio.CancelledError):
                log.warning("refresh_worker.shutdown_error", error=str(exc))
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())
