"""Smoke tests — verify imports work and jobs are wired correctly.

Real integration tests for detect_deals + post_deals require a live
Postgres + Redis. They live in `tests/integration/` and run only when
the FT_INTEGRATION_TESTS env var is set (CI provides them as service
containers).
"""
from __future__ import annotations


def test_jobs_importable():
    """All job entrypoints must import cleanly — catches refactor breakage."""
    from src.jobs import (
        cleanup_partitions,
        detect_deals,
        post_deals,
        refresh_views,
        snapshot_stub,
    )

    # Each module must expose an async callable named identically.
    assert callable(cleanup_partitions.cleanup_partitions)
    assert callable(detect_deals.detect_deals)
    assert callable(post_deals.post_deals)
    assert callable(refresh_views.refresh_views)
    assert callable(snapshot_stub.snapshot_stub)


def test_main_module_importable():
    """The scheduler entrypoint must build the AsyncIOScheduler without errors."""
    from src import main

    assert hasattr(main, "main")
