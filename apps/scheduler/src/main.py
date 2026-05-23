"""Scheduler entrypoint — wires AsyncIOScheduler to all periodic jobs.

Schedule (Europe/Kyiv):
- snapshot_stub        — 06:00 / 18:00 (price ingest placeholder until clients ship)
- refresh_views        — hourly at :05
- detect_deals         — hourly at :10
- post_deals           — every 15 min
- cleanup_partitions   — daily at 03:00

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

    # Snapshot stub — real ingest pipeline lands when ittour/farvater tokens
    # are wired. Runs anyway so the schedule shape is visible in Grafana.
    scheduler.add_job(
        snapshot_stub,
        CronTrigger(hour="6,18", minute=0, timezone=TIMEZONE),
        id="snapshot_stub",
        name="snapshot_stub (06:00 + 18:00 Kyiv)",
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

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("scheduler.stopping")
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())
