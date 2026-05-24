"""Periodic jobs registered with APScheduler in src/main.py."""

from src.jobs.cleanup_partitions import cleanup_partitions
from src.jobs.detect_deals import detect_deals
from src.jobs.post_deals import post_deals
from src.jobs.refresh_views import refresh_views
from src.jobs.refresh_worker import refresh_worker_loop
from src.jobs.notify_subscribers import notify_subscribers
from src.jobs.sitemap_long_tail import sitemap_long_tail_ingest
from src.jobs.snapshot_catalog_farvater import snapshot_catalog_farvater
from src.jobs.snapshot_farvater import snapshot_farvater
from src.jobs.snapshot_hot import snapshot_hot
from src.jobs.snapshot_stub import snapshot_stub

__all__ = [
    "cleanup_partitions",
    "detect_deals",
    "notify_subscribers",
    "post_deals",
    "refresh_views",
    "refresh_worker_loop",
    "sitemap_long_tail_ingest",
    "snapshot_catalog_farvater",
    "snapshot_farvater",
    "snapshot_hot",
    "snapshot_stub",
]
