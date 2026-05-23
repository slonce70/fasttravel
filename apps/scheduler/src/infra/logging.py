"""structlog setup — mirrors apps/api/src/infra/logging.py.

JSON renderer in prod, pretty console renderer in dev. Standard-library
loggers (apscheduler, sqlalchemy, aiogram) route through the same
processor chain so output is uniformly structured.
"""
from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import Processor

from src.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    is_prod = settings.is_prod

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
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

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
    root.setLevel(getattr(logging, settings.log_level))

    # Quiet down library noise unless explicitly debugging.
    for noisy in ("sqlalchemy.engine", "apscheduler.scheduler", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # aiogram is reasonably quiet at INFO but very chatty at DEBUG.
    logging.getLogger("aiogram").setLevel(logging.INFO)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
