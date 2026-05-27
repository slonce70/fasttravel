"""Shared Sentry init for every Python service.

Audit Sprint #7: api/scheduler/bot each had their own configure_sentry
with a different integration list (the bot's variant had no
SqlalchemyIntegration even though the bot reads/writes Postgres for
subscriber state). This module consolidates that.

Callers pass a `SentrySettings`-shaped object and a list of
service-specific integrations. Asyncio is always included because
every service in this stack runs on asyncio.
"""

from __future__ import annotations

from typing import Any

# Duck-typed settings — anything with `.sentry_dsn` (str|None),
# `.sentry_traces_sample_rate` (float) and `.environment` (str).
# Typed as Any so service Settings classes don't need to inherit a
# Protocol; an actually-missing attribute surfaces at boot time.
_SentrySettings = Any


def configure_sentry(
    settings: _SentrySettings,
    *,
    extra_integrations: list[Any] | None = None,
) -> bool:
    """Initialise Sentry SDK if DSN is configured. Returns True iff enabled.

    Args:
        settings: anything with `.sentry_dsn`, `.sentry_traces_sample_rate`,
            and `.environment` (str).
        extra_integrations: service-specific integrations to add on top
            of the always-on ones (AsyncioIntegration,
            SqlalchemyIntegration). Pass `[FastApiIntegration()]` from
            the API, `[]` from the scheduler / bot.

    The Sentry SDK import is done inside the function so the dependency
    is optional at module-import time (matters for unit tests that don't
    want to pull sentry-sdk into the import graph).
    """
    if not settings.sentry_dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    integrations: list[Any] = [
        AsyncioIntegration(),
        SqlalchemyIntegration(),
        *(extra_integrations or []),
    ]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=integrations,
    )
    return True
