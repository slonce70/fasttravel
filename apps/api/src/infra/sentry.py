"""Optional Sentry init — only enabled when SENTRY_DSN is set."""

from __future__ import annotations

from src.config import get_settings


def configure_sentry() -> bool:
    """Initialize Sentry SDK if DSN is configured. Returns True iff enabled."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False

    # Import inside the function so the dependency is optional at import time.
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            AsyncioIntegration(),
        ],
    )
    return True
