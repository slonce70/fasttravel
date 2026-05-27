"""Bot logging — thin wrapper over shared.infra.logging.

The bot previously had a stripped-down structlog config that didn't
route stdlib logging through structlog (so aiogram's INFO lines came
out in plain-text format while structlog lines came out as JSON).
Using the shared helper fixes that drift.
"""

from __future__ import annotations

from shared.infra.logging import configure_logging as _shared_configure
from shared.infra.logging import get_logger as _shared_get_logger
from src.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Idempotent — subsequent calls are no-ops (matches the previous
    bot behaviour so call sites in handlers don't need to think about
    initialisation order)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _shared_configure(get_settings(), extra_quiet=("aiogram.event",))
    _CONFIGURED = True


def get_logger(name: str | None = None, **bound):  # type: ignore[no-untyped-def]
    """Module-local convenience — accepts bind kwargs the way the old
    bot helper did, so callers don't need to refactor."""
    configure_logging()
    log = _shared_get_logger(name or "bot")
    return log.bind(**bound) if bound else log
