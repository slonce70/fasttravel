"""Periodic jobs registered with APScheduler in src/main.py."""
from src.jobs.cleanup_partitions import cleanup_partitions
from src.jobs.detect_deals import detect_deals
from src.jobs.post_deals import post_deals
from src.jobs.refresh_views import refresh_views
from src.jobs.snapshot_stub import snapshot_stub

__all__ = [
    "cleanup_partitions",
    "detect_deals",
    "post_deals",
    "refresh_views",
    "snapshot_stub",
]
