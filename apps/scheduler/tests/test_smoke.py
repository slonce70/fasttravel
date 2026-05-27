"""Smoke tests — verify imports work and jobs are wired correctly.

Real integration tests for detect_deals + post_deals require a live
Postgres + Redis. They live in `tests/integration/` and run only when
the FT_INTEGRATION_TESTS env var is set (CI provides them as service
containers).
"""

from __future__ import annotations


def test_jobs_importable():
    """All job entrypoints must import cleanly — catches refactor breakage.

    `src.jobs.__init__` re-exports the functions themselves (not the
    modules), so we import them directly and assert they're callable.
    """
    from src.jobs import (
        cleanup_partitions,
        detect_deals,
        post_deals,
        refresh_views,
        sitemap_long_tail_ingest,
        snapshot_farvater,
        snapshot_hot,
    )

    assert callable(cleanup_partitions)
    assert callable(detect_deals)
    assert callable(post_deals)
    assert callable(refresh_views)
    assert callable(sitemap_long_tail_ingest)
    assert callable(snapshot_farvater)
    assert callable(snapshot_hot)


def test_main_module_importable():
    """The scheduler entrypoint must build the AsyncIOScheduler without errors."""
    from src import main

    assert hasattr(main, "main")


def test_scheduler_registers_weekly_sitemap_ingest_but_not_startup_by_default(
    monkeypatch,
):
    """Long-tail sitemap ingest must not auto-run on every scheduler restart."""
    from src import main

    monkeypatch.delenv("FT_SITEMAP_STARTUP_INGEST_ENABLED", raising=False)
    scheduler = main._build_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "sitemap_long_tail_ingest" in job_ids
    assert "sitemap_long_tail_ingest_startup" not in job_ids


def test_scheduler_registers_startup_sitemap_ingest_when_enabled(monkeypatch):
    """Operator can opt into restart-resume explicitly for manual recovery."""
    from src import main

    monkeypatch.setenv("FT_SITEMAP_STARTUP_INGEST_ENABLED", "1")
    scheduler = main._build_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "sitemap_long_tail_ingest_startup" in job_ids


def test_scheduler_does_not_register_placeholder_jobs():
    """Production scheduler must not report fake heartbeat jobs as ingest."""
    from src import main

    scheduler = main._build_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "snapshot_stub" not in job_ids
