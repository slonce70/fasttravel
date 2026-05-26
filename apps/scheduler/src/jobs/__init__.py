"""Periodic jobs registered with APScheduler in src/main.py."""

from src.jobs.canary_farvater_schema import canary_farvater_schema
from src.jobs.cleanup_partitions import cleanup_partitions
from src.jobs.decay_active_prices import decay_active_prices
from src.jobs.detect_deals import detect_deals
from src.jobs.notify_subscribers import notify_subscribers
from src.jobs.post_deals import post_deals
from src.jobs.refresh_baselines import refresh_baselines
from src.jobs.refresh_views import refresh_views
from src.jobs.refresh_worker import refresh_worker_loop
from src.jobs.sitemap_long_tail import (
    sitemap_long_tail_ingest,
    sitemap_long_tail_ingest_resilient,
)
from src.jobs.snapshot_catalog_farvater import snapshot_catalog_farvater
from src.jobs.snapshot_farvater import snapshot_farvater
from src.jobs.snapshot_hot import snapshot_hot
from src.jobs.static_tours_sweep import static_tours_sweep

__all__ = [
    "canary_farvater_schema",
    "cleanup_partitions",
    "decay_active_prices",
    "detect_deals",
    "notify_subscribers",
    "post_deals",
    "refresh_baselines",
    "refresh_views",
    "refresh_worker_loop",
    "sitemap_long_tail_ingest",
    "sitemap_long_tail_ingest_resilient",
    "snapshot_catalog_farvater",
    "snapshot_farvater",
    "snapshot_hot",
    "static_tours_sweep",
]
