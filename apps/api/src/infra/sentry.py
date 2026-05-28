"""API Sentry wiring — thin wrapper over shared.infra.sentry.

The actual init lives in `shared.infra.sentry`; this file injects the
FastAPI integration that's API-only (scheduler / bot don't need it).
"""

from __future__ import annotations

from shared.infra.sentry import configure_sentry as _shared_configure
from src.config import get_settings


def configure_sentry() -> bool:
    """Initialize Sentry SDK if DSN is configured. Returns True iff enabled."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    # FastApiIntegration import is deferred so unit tests that don't
    # touch the API surface don't pull sentry-sdk[fastapi] at collect time.
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    return _shared_configure(settings, extra_integrations=[FastApiIntegration()])
