"""API logging wiring — thin wrapper over shared.infra.logging.

The actual structlog configuration lives in `shared.infra.logging`;
this file just feeds it the API's quiet-list (uvicorn.access — the
HTTP access log is noisy at INFO and adds nothing the FastAPI
instrumentator metrics don't already capture).
"""

from __future__ import annotations

from shared.infra.logging import configure_logging as _shared_configure
from shared.infra.logging import get_logger as _shared_get_logger

from src.config import get_settings


def configure_logging() -> None:
    _shared_configure(get_settings(), extra_quiet=("uvicorn.access",))


# Re-export so existing `from src.infra.logging import get_logger` callers
# keep working without touching every module.
get_logger = _shared_get_logger
