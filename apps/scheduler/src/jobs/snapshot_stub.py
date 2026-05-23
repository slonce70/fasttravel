"""Placeholder for the price-snapshot ingest job.

Real implementation lands in Week 3 alongside ``apps/ingest`` (see
docs/ARCHITECTURE.md §"Refresh price snapshot"). Until then we run an
empty heartbeat so:

  - the scheduler still has a 06:00 / 18:00 trigger for ops to verify
    the cron path works end-to-end,
  - Grafana dashboards can graph "scheduler ran" without #N/A holes.
"""
from __future__ import annotations

from src.infra.logging import get_logger

log = get_logger(__name__)


async def snapshot_stub() -> None:
    log.info(
        "snapshot.stub.executed",
        note="real ingest pending ittour token / farvater scraper implementation",
        scheduled_for="week 3 (apps/ingest)",
    )
