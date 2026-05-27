"""Shared pydantic-settings base for every Python service.

Audit Sprint #7: `apps/{api,bot,scheduler}/src/config.py` each
re-implemented the same model_config, environment literal, log_level
literal, and `assert_prod_secrets` skeleton with copy-paste drift
(scheduler checked Telegram creds, api didn't; bot acquired a fourth
required secret after Sprint 2.3). Now every service inherits
`BaseAppSettings`, overrides only what it actually needs, and the
"refuse to start in prod with dev defaults" contract is enforced
identically everywhere.

Usage:

    from shared.infra.base_settings import BaseAppSettings

    class Settings(BaseAppSettings):
        # service-specific fields here
        deals_daily_cap: int = 30

        def _extra_prod_offenders(self) -> list[str]:
            # service-specific required-in-prod env vars
            return ["TELEGRAM_BOT_TOKEN"] if not self.telegram_bot_token else []
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Markers that identify "this is the .env.example dev default and should
# never reach prod" — central so adding a new dev placeholder updates
# every service at once.
DEV_DEFAULT_MARKERS = ("_change_me", "fasttravel_dev")


class BaseAppSettings(BaseSettings):
    """Shared base for every service's `Settings` class.

    Defaults are local-dev-safe; `assert_prod_secrets()` is the gate
    that refuses to boot in prod when any required secret still carries
    a dev marker or is empty.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Common environment ---
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Common DB (async-asyncpg URL is canonical) ---
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )

    # --- Common Redis (logical DB choice differs per service) ---
    redis_url: str = "redis://redis:6379/0"

    # --- Common Sentry (optional) ---
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    def _extra_prod_offenders(self) -> list[str]:
        """Hook for subclasses to add their own required-in-prod env vars.

        Default: nothing extra. Override to enumerate env-var NAMES (str)
        that must be non-empty / non-dev when `environment == 'prod'`.
        """
        return []

    def assert_prod_secrets(self) -> None:
        """Refuse to boot prod with dev defaults / missing required secrets.

        Shared offenders (DATABASE_URL with `_change_me`, etc.) checked
        here; service-specific offenders come from
        `_extra_prod_offenders()`.
        """
        if not self.is_prod:
            return

        offenders: list[str] = []
        if any(m in self.database_url for m in DEV_DEFAULT_MARKERS):
            offenders.append("DATABASE_URL")
        offenders.extend(self._extra_prod_offenders())

        if offenders:
            raise RuntimeError(
                "Refusing to start in prod with unsafe or missing settings: "
                + ", ".join(offenders)
                + ". Run infra/scripts/secrets-bootstrap.sh and re-deploy."
            )


def cached(settings_cls: type[BaseAppSettings]) -> Callable[[], BaseAppSettings]:
    """Decorator-shaped helper: `get_settings = cached(Settings)`.

    Equivalent to writing:
        @lru_cache(maxsize=1)
        def get_settings() -> Settings: return Settings()
    in every service. Useful when no factory customisation is needed.
    """

    @lru_cache(maxsize=1)
    def _factory() -> BaseAppSettings:
        return settings_cls()

    return _factory
