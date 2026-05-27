"""Scheduler logging — thin wrapper over shared.infra.logging."""

from __future__ import annotations

from shared.infra.logging import configure_logging as _shared_configure
from shared.infra.logging import get_logger as _shared_get_logger
from src.config import get_settings


def configure_logging() -> None:
    _shared_configure(
        get_settings(),
        extra_quiet=(
            "apscheduler.scheduler",
            "apscheduler.executors",
            # aiogram itself is fine at INFO; bump if it gets noisy.
        ),
    )


get_logger = _shared_get_logger
