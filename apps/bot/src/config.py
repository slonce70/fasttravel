"""Bot configuration.

Single Settings class fed by .env (same convention as api/scheduler).
TELEGRAM_BOT_TOKEN absence is first-class: the bot logs and idles so an
unconfigured dev environment keeps docker-compose green.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Bot identity.
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None
    public_channel_link: str = "https://t.me/testtyhhh"

    # Backend HTTP API. In docker-compose this resolves to the api service;
    # for local pytest runs we fall back to the published port on host.
    api_base_url: str = "http://api:8000"

    # Direct DB access for subscriber filters.
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )

    # Redis is shared with the scheduler/api; we use a dedicated logical DB
    # so FSM state doesn't bump heads with the refresh:queue list.
    redis_url: str = "redis://redis:6379/2"

    # Observability — same conventions as scheduler.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0
    metrics_port: int = 9102

    # Sprint 2.3 — Prometheus AlertManager webhook listener. Port chosen
    # next-after metrics_port; both internal-only in docker-compose.
    alert_webhook_port: int = 9103
    alertmanager_webhook_secret: str | None = None

    # Public Next.js site URL used in deep links / CTA buttons.
    # Intentionally no default: fasttravel.com.ua may point at an
    # unrelated PHP storefront until DNS/Cloudflare frontend deploy is done.
    public_site_url: str | None = None

    @property
    def has_public_site(self) -> bool:
        return bool(self.public_site_url)

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    def assert_prod_secrets(self) -> None:
        """Refuse to boot prod with local defaults or missing Telegram wiring."""
        if not self.is_prod:
            return

        forbidden_markers = ("_change_me", "fasttravel_dev")
        offenders: list[str] = []
        if any(marker in self.database_url for marker in forbidden_markers):
            offenders.append("DATABASE_URL")
        if not self.telegram_bot_token:
            offenders.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_channel_id:
            offenders.append("TELEGRAM_CHANNEL_ID")
        if offenders:
            raise RuntimeError(
                "Refusing to start bot in prod with unsafe or missing settings: "
                + ", ".join(offenders)
                + ". Run infra/scripts/secrets-bootstrap.sh and re-deploy."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
