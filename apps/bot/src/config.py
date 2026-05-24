"""Bot-only settings.

Mirrors the scheduler/api shape (pydantic-settings, env-file friendly).
Bot reads from the same `.env` so deploy-time secret rotation is single-source.
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

    # Bot identity. Token absence is a first-class state — the bot logs and
    # exits cleanly so an unconfigured environment can still run the rest
    # of the docker-compose stack.
    telegram_bot_token: str | None = None

    # Channel the /start welcome funnels users to. Either '@slug' or '-100...'.
    telegram_channel_id: str | None = None
    public_channel_link: str = "https://t.me/fasttravel_deals_ua"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
