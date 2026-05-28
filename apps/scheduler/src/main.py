"""Scheduler entrypoint — wires AsyncIOScheduler to all periodic jobs.

Schedule (Europe/Kyiv):
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
import os
import signal
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src import jobs as scheduler_jobs
from src.config import get_settings
from src.infra.logging import get_logger
from src.infra.metrics import (
    bootstrap_last_successful_snapshots,
    start_metrics_server,
    track_job_metrics,
)
from src.infra.sentry import configure_sentry

# Decorate every job at registration so the metric labels stay consistent
# and the underlying job modules don't have to import `metrics` themselves.
# `refresh_worker_loop` is excluded: it's a long-running loop, not a job
# invocation, so the run-counter/duration model doesn't fit cleanly.
canary_farvater_schema = track_job_metrics("canary_farvater_schema")(
    scheduler_jobs.canary_farvater_schema
)
cleanup_partitions = track_job_metrics("cleanup_partitions")(scheduler_jobs.cleanup_partitions)
decay_active_prices = track_job_metrics("decay_active_prices")(scheduler_jobs.decay_active_prices)
detect_deals = track_job_metrics("detect_deals")(scheduler_jobs.detect_deals)
refresh_baselines = track_job_metrics("refresh_baselines")(scheduler_jobs.refresh_baselines)
notify_subscribers = track_job_metrics("notify_subscribers")(scheduler_jobs.notify_subscribers)
post_deals = track_job_metrics("post_deals")(scheduler_jobs.post_deals)
refresh_worker_loop = scheduler_jobs.refresh_worker_loop
refresh_views = track_job_metrics("refresh_views")(scheduler_jobs.refresh_views)
sitemap_long_tail_ingest = track_job_metrics("sitemap_long_tail_ingest")(
    scheduler_jobs.sitemap_long_tail_ingest
)
# Resilient wrapper — retries on transient network errors (DNS, connect,
# timeout) with exponential backoff and records failures to scrape_runs.
# Used for the startup one-shot resume and a daily fallback CronTrigger.
sitemap_long_tail_ingest_resilient = track_job_metrics("sitemap_long_tail_ingest_resilient")(
    scheduler_jobs.sitemap_long_tail_ingest_resilient
)
snapshot_catalog_farvater = track_job_metrics("snapshot_catalog_farvater")(
    scheduler_jobs.snapshot_catalog_farvater
)
snapshot_farvater = track_job_metrics("snapshot_farvater")(scheduler_jobs.snapshot_farvater)
snapshot_hot = track_job_metrics("snapshot_hot")(scheduler_jobs.snapshot_hot)
# Sprint 1C — promo-bucket sweep. Behind FT_STATIC_TOURS_SWEEP_ENABLED
# env flag (default off); the job no-ops when disabled.
static_tours_sweep = track_job_metrics("static_tours_sweep")(scheduler_jobs.static_tours_sweep)

log = get_logger(__name__)

TIMEZONE = "Europe/Kyiv"
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}

# Job concurrency is 1 by default — these jobs are idempotent but each
# touches the same MVs / deals table, so serialising avoids lock noise.
_JOB_DEFAULTS = {
    "coalesce": True,  # if app catches up, run once for the missed window
    "max_instances": 1,
    "misfire_grace_time": 60 * 5,
}


def _build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE, job_defaults=_JOB_DEFAULTS)

    # Live farvater.travel ingest — pulls real prices for ~600 hotels across
    # 11 countries twice daily (06:00 + 18:00 Kyiv).
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
    # Sitemap long-tail ingest — weekly Sunday 02:00 Kyiv. Walks farvater's
    # full sitemap (~57k URLs for our 11 countries), upserts meta+gallery+
    # reviews, probes 3 calendar offsets per hotel. Idempotent via slug dedup,
    # so a partial run that gets killed (container restart, deploy) resumes
    # cleanly on the next weekly tick. CONCURRENCY=12, ~1-2h wall clock.
    scheduler.add_job(
        sitemap_long_tail_ingest,
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=TIMEZONE),
        id="sitemap_long_tail_ingest",
        name="sitemap_long_tail_ingest (weekly Sun 02:00 Kyiv)",
    )
    if os.environ.get("FT_SITEMAP_STARTUP_INGEST_ENABLED", "").strip().lower() in TRUE_ENV_VALUES:
        scheduler.add_job(
            sitemap_long_tail_ingest_resilient,
            DateTrigger(
                run_date=datetime.now(UTC) + timedelta(seconds=30),
                timezone=TIMEZONE,
            ),
            id="sitemap_long_tail_ingest_startup",
            name="sitemap_long_tail_ingest (startup one-shot resume, resilient)",
        )
    # Daily fallback at 04:45 so we don't wait a full week to recover if the
    # Sunday run was killed mid-flight or skipped. Idempotent via slug dedup;
    # no local cap: already-ingested slugs are skipped, fresh hotels continue
    # until the supported-country sitemap is exhausted.
    # Slot is 04:45 — after cleanup_partitions (04:30), before any business-hour
    # traffic. Resilient wrapper handles transient DNS/connect failures.
    scheduler.add_job(
        sitemap_long_tail_ingest_resilient,
        CronTrigger(hour=4, minute=45, timezone=TIMEZONE),
        id="sitemap_long_tail_ingest_daily_fallback",
        name="sitemap_long_tail_ingest (daily 04:45 Kyiv fallback, uncapped)",
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
    # Personal Telegram alerts: hourly at :15, right after detect_deals
    # writes any new matches. Slot is intentionally tight — a 5-min lag
    # keeps alerts feeling "live" without overlapping the detector.
    scheduler.add_job(
        notify_subscribers,
        CronTrigger(minute=15, timezone=TIMEZONE),
        id="notify_subscribers",
        name="notify_subscribers (hourly :15)",
        max_instances=1,
        coalesce=True,
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
        max_instances=1,
        coalesce=True,
    )

    # Sprint 1C — promo-bucket sweep. Cheap (~10-50 POSTs/run), every
    # 2 hours at :20 so it doesn't collide with refresh_views (:05),
    # detect_deals (:10), notify_subscribers (:15), or snapshot_hot (:30).
    # No-ops when FT_STATIC_TOURS_SWEEP_ENABLED is unset.
    scheduler.add_job(
        static_tours_sweep,
        CronTrigger(hour="*/2", minute=20, timezone=TIMEZONE),
        id="static_tours_sweep",
        name="static_tours_sweep (every 2h :20 Kyiv)",
    )

    # Sprint 1F off-peak ladder. Each runs once a day, 15 min apart, so
    # one wobble doesn't cascade. Order chosen so each consumer sees the
    # state its predecessor produced:
    #   04:00 decay_active_prices — drop stale `has_active_prices` rows
    #   04:15 refresh_baselines   — non-CONCURRENT MV refresh of price_baselines
    #   04:30 cleanup_partitions  — pg_partman housekeeping
    #   04:45 sitemap_long_tail   — small daily fallback (registered above)
    scheduler.add_job(
        decay_active_prices,
        CronTrigger(hour=4, minute=0, timezone=TIMEZONE),
        id="decay_active_prices",
        name="decay_active_prices (daily 04:00 Kyiv)",
    )
    scheduler.add_job(
        refresh_baselines,
        CronTrigger(hour=4, minute=15, timezone=TIMEZONE),
        id="refresh_baselines",
        name="refresh_baselines (daily 04:15 Kyiv)",
    )
    scheduler.add_job(
        cleanup_partitions,
        CronTrigger(hour=4, minute=30, timezone=TIMEZONE),
        id="cleanup_partitions",
        name="cleanup_partitions (daily 04:30 Kyiv)",
    )
    # Sprint 3.7 — schema canary. Fires once a day at 05:00 Kyiv, after
    # the housekeeping ladder finishes. Cheap (~2 POSTs); never raises.
    scheduler.add_job(
        canary_farvater_schema,
        CronTrigger(hour=5, minute=0, timezone=TIMEZONE),
        id="canary_farvater_schema",
        name="canary_farvater_schema (daily 05:00 Kyiv)",
    )

    return scheduler


async def main() -> None:
    settings = get_settings()
    settings.assert_prod_secrets()

    # Optional observability — Sentry only init's when SENTRY_DSN env is set,
    # Prometheus exporter always boots (Prometheus scrape is opt-in via
    # infra/prometheus/prometheus.yml; nothing breaks if it's unscraped).
    sentry_enabled = configure_sentry()
    start_metrics_server(settings.metrics_port)
    await bootstrap_last_successful_snapshots()
    log.info(
        "scheduler.booting",
        environment=settings.environment,
        sentry=sentry_enabled,
        metrics_port=settings.metrics_port,
    )

    scheduler = _build_scheduler()
    scheduler.start()

    jobs = [(j.id, str(j.next_run_time)) for j in scheduler.get_jobs()]
    log.info("scheduler.started", timezone=TIMEZONE, jobs=jobs)

    # Spawn the persistent refresh worker (P1-4). It's not a cron job —
    # it BRPOPs `refresh:queue` continuously so user-triggered refreshes
    # survive an API restart and don't depend on FastAPI's BackgroundTasks.
    worker_task = asyncio.create_task(refresh_worker_loop(), name="refresh_worker_loop")

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
