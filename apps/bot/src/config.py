"""Bot configuration.

Single Settings class fed by .env (same convention as api/scheduler).
TELEGRAM_BOT_TOKEN absence is first-class: the bot logs and idles so an
unconfigured dev environment keeps docker-compose green.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    public_channel_link: str = "https://t.me/fasttravel_deals_ua"

    # Backend HTTP API. In docker-compose this resolves to the api service;
    # for local pytest runs we fall back to the published port on host.
    api_base_url: str = "http://api:8000"

    # Redis is shared with the scheduler/api; we use a dedicated logical DB
    # so FSM state doesn't bump heads with the refresh:queue list.
    redis_url: str = "redis://redis:6379/2"

    # Observability — same conventions as scheduler.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0
    metrics_port: int = 9102

    # Public site URL used in deep links / CTA buttons.
    public_site_url: str = "https://fasttravel.com.ua"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
