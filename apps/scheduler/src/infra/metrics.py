"""Prometheus metrics for the scheduler service.

The scheduler has no FastAPI surface, so we expose `/metrics` via the
stdlib HTTP server `prometheus_client.start_http_server` ships with.
Prometheus is configured (infra/prometheus/prometheus.yml) to scrape
`scheduler:9101` once a minute.

Three metric families cover the operational questions we actually ask:

* `fasttravel_job_runs_total{scheduled_job, outcome}` — Counter incremented on every
  job invocation tagged success/failure. Backs the "is the scheduler alive"
  dashboard panel and the SLO burn-rate alert.

* `fasttravel_job_duration_seconds{scheduled_job}` — Histogram of wall-clock time per
  job. Buckets cover the realistic range (0.1s health-check style jobs
  through 4h sitemap ingest). Quantile lookups answer "did snapshot_farvater
  start taking longer than usual?".

* `fasttravel_refresh_queue_depth` — Gauge updated on each run by
  `snapshot_hot` / `refresh_worker`. Surfaces the persistent Redis queue
  size so we can alert when it stays near the 200 cap.

* `fasttravel_scheduler_started_unixtime` — Gauge set on exporter boot.
  Alert rules use it as startup grace so hourly jobs do not page before
  they have had a fair chance to run.

The `@track_job_metrics` decorator wraps any APScheduler-registered async
callable and emits the run + duration metrics automatically. Jobs only
need to call into the Gauge directly if they want to publish bespoke
counters.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

from src.infra.logging import get_logger

log = get_logger(__name__)

# Dedicated registry so dev tests can spin up isolated metrics without
# clobbering the process-global default. start_http_server uses the
# global REGISTRY by default; we pass ours in explicitly.
REGISTRY = CollectorRegistry()


JOB_RUNS = Counter(
    "fasttravel_job_runs_total",
    "Total scheduler job invocations, labelled by outcome.",
    labelnames=("scheduled_job", "outcome"),
    registry=REGISTRY,
)


JOB_DURATION = Histogram(
    "fasttravel_job_duration_seconds",
    "Wall-clock duration of scheduler job invocations.",
    labelnames=("scheduled_job",),
    # Buckets span the realistic range from a sub-second metric flush
    # through a multi-hour sitemap ingest. Hand-tuned so the per-job
    # histograms expose meaningful p50/p95 without burning cardinality.
    buckets=(0.1, 0.5, 1, 5, 15, 60, 300, 900, 3600, 14400),
    registry=REGISTRY,
)


REFRESH_QUEUE_DEPTH = Gauge(
    "fasttravel_refresh_queue_depth",
    "Current length of the Redis `refresh:queue` list.",
    registry=REGISTRY,
)


SCHEDULER_STARTED_AT = Gauge(
    "fasttravel_scheduler_started_unixtime",
    "Unix timestamp when the scheduler metrics exporter started.",
    registry=REGISTRY,
)


# Sprint 2.1 — visibility into the price write path. The two operational
# alerts that matter most ("we wrote 0 rows for 3 ticks", "country X
# has 80% scrape failures") both need these counters.
PRICES_WRITTEN = Counter(
    "fasttravel_prices_written_total",
    "price_observations rows written, labelled by source + country.",
    labelnames=("source", "country"),
    registry=REGISTRY,
)


SCRAPE_HOTEL_FAILURES = Counter(
    "fasttravel_scrape_hotel_failures_total",
    "Per-hotel scrape failures (drops + parse errors), with reason label.",
    labelnames=("source", "country", "reason"),
    registry=REGISTRY,
)


PROMOS_INGESTED = Counter(
    "fasttravel_promos_ingested_total",
    "Promo rows inserted into promo_offers, labelled by bucket + country.",
    labelnames=("bucket", "country"),
    registry=REGISTRY,
)


# Per-branch visibility for detect_deals. `detection_method` mirrors the
# DB column (`percentile`, `promo_discount`, `calendar_anomaly`). `reason`
# is the sub-branch: `warm`/`cold` for percentile, `date_dip`/`stay_inversion`
# for calendar_anomaly, `bucket` for promo_discount. Needed to detect
# overfiring (e.g. stay_inversion dominating the channel) without grepping
# the deals table.
DEALS_INSERTED = Counter(
    "fasttravel_deals_inserted_total",
    "New deals inserted by detect_deals, by method + sub-reason.",
    labelnames=("detection_method", "reason"),
    registry=REGISTRY,
)


# Stage 3 (post-audit). Counts (hotel, operator, check_in, nights, meal)
# tuples in price_observations that have >1 distinct room_category in the
# last 24h. These tuples are the ones where current_prices DISTINCT ON
# silently picks one room — making downstream p50/p15 (used by the
# calendar_anomaly detector) wobble whenever the picked room changes
# between snapshots.
#
# We don't fix the schema here (would require uq_price_obs_natural rebuild
# + DISTINCT ON change in current_prices). Instead we surface the
# magnitude. Alert threshold (loose): page when this stays >5 % of the
# total priced-hotel count for 24h+, indicating the deferred fix is
# starting to bite. See ~/.claude/plans/mutable-hopping-barto.md
# Stage 3.
ROOMS_COLLAPSED_LAST_REFRESH = Gauge(
    "fasttravel_rooms_collapsed_last_refresh",
    "Count of (hotel, op, check_in, nights, meal) tuples with >1 room in 24h.",
    registry=REGISTRY,
)


# Number of times the production-tier farvater HTTP client tripped its
# circuit breaker (5×{429,403} in a 15-min window → 1-hour cooldown).
# Sprint 0.5 — paired with the `StaleSnapshot` alert: if the breaker
# trips repeatedly the snapshot gauge will go stale soon after.
FARVATER_BREAKER_TRIPS = Counter(
    "fasttravel_farvater_breaker_trips_total",
    "Times the production farvater HTTP client opened its circuit breaker.",
    registry=REGISTRY,
)


# Wall-clock timestamp (unix seconds) of the last successful run per job.
# Set via .set(time.time()) at the tail of each successful scrape job.
# Used by Prometheus alert rules to fire `StaleSnapshot` and `StaleCatalog`
# when no successful run has been seen for >14h / >36h respectively. A
# job-labelled Gauge (rather than separate metrics per job) keeps the
# alert rule reusable and the cardinality bounded to N scrape jobs.
LAST_SUCCESSFUL_SNAPSHOT = Gauge(
    "fasttravel_last_successful_snapshot_unixtime",
    "Unix timestamp of the last successful run, per scrape job.",
    labelnames=("scheduled_job",),
    registry=REGISTRY,
)


P = ParamSpec("P")
R = TypeVar("R")


def track_job_metrics(
    job_name: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator: increment JOB_RUNS + record JOB_DURATION around an async job.

    Usage:
        @track_job_metrics("snapshot_farvater")
        async def snapshot_farvater(...): ...

    Failures still propagate — the decorator just makes sure the metric
    counter sees the failure outcome before the exception escapes.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            t0 = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
            except asyncio.CancelledError:
                JOB_RUNS.labels(scheduled_job=job_name, outcome="cancelled").inc()
                raise
            except Exception:
                JOB_RUNS.labels(scheduled_job=job_name, outcome="failure").inc()
                raise
            else:
                JOB_RUNS.labels(scheduled_job=job_name, outcome="success").inc()
                return result
            finally:
                JOB_DURATION.labels(scheduled_job=job_name).observe(time.perf_counter() - t0)

        return wrapper

    return decorator


def start_metrics_server(port: int) -> None:
    """Bind a `prometheus_client` HTTP exporter on `port` for scraping.

    Idempotent within a process — the underlying server is started once;
    subsequent calls log and no-op. The scheduler entrypoint calls this
    during boot.
    """
    try:
        SCHEDULER_STARTED_AT.set(time.time())
        start_http_server(port, registry=REGISTRY)
        log.info("scheduler.metrics.started", port=port)
    except OSError as exc:
        # Already-bound socket isn't fatal — most likely a hot-reloaded dev
        # process. Log and continue so the rest of the scheduler boots.
        log.warning("scheduler.metrics.bind_failed", port=port, error=str(exc))


async def bootstrap_last_successful_snapshots() -> None:
    """Seed staleness gauges from scrape_runs after scheduler restart.

    Without this bootstrap, Prometheus sees no time series until each job
    completes in the current process, and absent series do not trip simple
    staleness expressions.
    """
    try:
        from sqlalchemy import text

        from src.infra.db import async_session_factory

        source_to_job = {
            "farvater_scrape": "snapshot_farvater",
            "catalog_only": "snapshot_catalog_farvater",
            "static_tours_sweep": "static_tours_sweep",
        }
        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    text(
                        """SELECT source, EXTRACT(EPOCH FROM MAX(finished_at)) AS ts
                           FROM scrape_runs
                           WHERE status = 'success'
                             AND source = ANY(:sources)
                           GROUP BY source"""
                    ),
                    {"sources": list(source_to_job)},
                )
            ).all()
        for row in rows:
            job = source_to_job.get(row.source)
            if job and row.ts is not None:
                LAST_SUCCESSFUL_SNAPSHOT.labels(scheduled_job=job).set(float(row.ts))
        log.info("scheduler.metrics.bootstrapped", gauges=len(rows))
    except Exception as exc:  # noqa: BLE001
        log.warning("scheduler.metrics.bootstrap_failed", error=str(exc))
