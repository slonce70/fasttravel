"""Scheduler Sentry wiring — thin wrapper over shared.infra.sentry."""

from __future__ import annotations

from shared.infra.sentry import configure_sentry as _shared_configure
from src.config import get_settings


def configure_sentry() -> bool:
    """Initialize Sentry SDK if DSN is configured. Returns True iff enabled."""
    # Scheduler has no FastAPI surface — shared base already includes
    # AsyncioIntegration + SqlalchemyIntegration. Pass no extras.
    return _shared_configure(get_settings())
