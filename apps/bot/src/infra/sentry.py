"""Optional Sentry init — only enabled when SENTRY_DSN is set.

Mirrors apps/scheduler/src/infra/sentry.py shape. Bot has no FastAPI
or sqlalchemy surface so we wire only asyncio.
"""

from __future__ import annotations

from src.config import get_settings


def configure_sentry() -> bool:
    settings = get_settings()
    if not settings.sentry_dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[AsyncioIntegration()],
    )
    return True
