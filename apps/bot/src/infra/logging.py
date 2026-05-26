"""Single structlog setup for the bot.

Keeps every module's `get_logger(__name__)` identically configured so
log lines from handlers/keyboards/infra all parse the same way upstream.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging() -> None:
    """Idempotent: subsequent calls are no-ops."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    _CONFIGURED = True


def get_logger(name: str | None = None, **bound: Any) -> structlog.stdlib.BoundLogger:
    configure_logging()
    log = structlog.get_logger(name or "bot")
    return log.bind(**bound) if bound else log
