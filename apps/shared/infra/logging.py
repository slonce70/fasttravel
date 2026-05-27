"""Shared structlog configuration for every Python service.

Audit Sprint #7: `apps/{api,bot,scheduler}/src/infra/logging.py` were
three near-identical copies that drifted (the bot's variant only
configured structlog and skipped stdlib logging, so aiogram's INFO
lines never matched the surrounding JSON shape).

This module replaces all three. Callers pass a `LoggingSettings`-shaped
object (anything with `.is_prod`, `.log_level`) — typically the service's
`Settings` instance.

Service-specific log-noise quieting (e.g. `apscheduler.scheduler` is
chatty in the scheduler but not in the bot) is opt-in via the
`extra_quiet` argument so each service stays in control.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog
from structlog.types import Processor

# Duck-typed settings — anything with `.is_prod` (bool) and `.log_level`
# (str matching logging level names). Typed as Any so service Settings
# classes don't need to inherit a Protocol; mypy still catches missing
# attributes via runtime AttributeError at boot.
_LoggingSettings = Any


# Default modules to clamp at WARNING regardless of caller config.
# These are noisy under any configuration we ship and never carry
# action-required signal at INFO.
_DEFAULT_QUIET = ("sqlalchemy.engine",)


def configure_logging(
    settings: _LoggingSettings,
    *,
    extra_quiet: tuple[str, ...] = (),
) -> None:
    """Wire structlog + stdlib logging once per process.

    Args:
        settings: anything with `.is_prod` (bool) and `.log_level` (str
            matching logging level names).
        extra_quiet: tuple of stdlib logger names to clamp at WARNING in
            addition to `_DEFAULT_QUIET`. Pass `('apscheduler.scheduler',
            'apscheduler.executors')` from the scheduler, etc.
    """
    is_prod = bool(settings.is_prod)
    level = getattr(logging, settings.log_level)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_prod:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route std-lib logging through the same renderer so library output
    # (uvicorn, aiogram, apscheduler) matches our shape.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared_processors,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in (*_DEFAULT_QUIET, *extra_quiet):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Module-local convenience — same return type as in every service."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
