"""Bot Sentry wiring — thin wrapper over shared.infra.sentry.

Previously the bot wired only AsyncioIntegration, which meant
SqlalchemyIntegration was missing even though the bot reads/writes
the telegram_subscribers / telegram_subscriber_filters tables.
Shared helper now includes both by default.
"""

from __future__ import annotations

from shared.infra.sentry import configure_sentry as _shared_configure
from src.config import get_settings


def configure_sentry() -> bool:
    """Initialize Sentry SDK if DSN is configured. Returns True iff enabled."""
    return _shared_configure(get_settings())
