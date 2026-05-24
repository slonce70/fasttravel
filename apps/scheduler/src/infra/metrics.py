"""Prometheus metrics for the scheduler service.

The scheduler has no FastAPI surface, so we expose `/metrics` via the
stdlib HTTP server `prometheus_client.start_http_server` ships with.
Prometheus is configured (infra/prometheus/prometheus.yml) to scrape
`scheduler:9101` once a minute.

Three metric families cover the operational questions we actually ask:

* `fasttravel_job_runs_total{job, outcome}` — Counter incremented on every
  job invocation tagged success/failure. Backs the "is the scheduler alive"
  dashboard panel and the SLO burn-rate alert.

* `fasttravel_job_duration_seconds{job}` — Histogram of wall-clock time per
  job. Buckets cover the realistic range (0.1s health-check style jobs
  through 4h sitemap ingest). Quantile lookups answer "did snapshot_farvater
  start taking longer than usual?".

* `fasttravel_refresh_queue_depth` — Gauge updated on each run by
  `snapshot_hot` / `refresh_worker`. Surfaces the persistent Redis queue
  size so we can alert when it stays near the 200 cap.

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
    labelnames=("job", "outcome"),
    registry=REGISTRY,
)


JOB_DURATION = Histogram(
    "fasttravel_job_duration_seconds",
    "Wall-clock duration of scheduler job invocations.",
    labelnames=("job",),
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


P = ParamSpec("P")
R = TypeVar("R")


def track_job_metrics(job_name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
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
                JOB_RUNS.labels(job=job_name, outcome="cancelled").inc()
                raise
            except Exception:
                JOB_RUNS.labels(job=job_name, outcome="failure").inc()
                raise
            else:
                JOB_RUNS.labels(job=job_name, outcome="success").inc()
                return result
            finally:
                JOB_DURATION.labels(job=job_name).observe(time.perf_counter() - t0)

        return wrapper

    return decorator


def start_metrics_server(port: int) -> None:
    """Bind a `prometheus_client` HTTP exporter on `port` for scraping.

    Idempotent within a process — the underlying server is started once;
    subsequent calls log and no-op. The scheduler entrypoint calls this
    during boot.
    """
    try:
        start_http_server(port, registry=REGISTRY)
        log.info("scheduler.metrics.started", port=port)
    except OSError as exc:
        # Already-bound socket isn't fatal — most likely a hot-reloaded dev
        # process. Log and continue so the rest of the scheduler boots.
        log.warning("scheduler.metrics.bind_failed", port=port, error=str(exc))
