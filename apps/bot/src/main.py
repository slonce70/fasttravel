"""Bot stub.

Real implementation (aiogram 3 handlers, broadcast publisher) lands in a
follow-up task. For now we keep the container alive so docker-compose stays
green and so health checks of the surrounding stack work.
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

log = structlog.get_logger(service="bot")


async def main() -> None:
    log.info("bot.starting", note="stub — awaiting aiogram implementation")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    log.info("bot.stopped")


if __name__ == "__main__":
    asyncio.run(main())
