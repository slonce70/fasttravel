"""Scheduler stub.

Real implementation (APScheduler with snapshot_hot, refresh_views,
detect_deals, post_deals jobs) lands in a follow-up task. For now we keep
the container alive so docker-compose stays green.
"""
from __future__ import annotations

import asyncio
import logging
import signal

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

log = structlog.get_logger(service="scheduler")


async def main() -> None:
    log.info("scheduler.starting", note="stub — awaiting APScheduler implementation")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())
