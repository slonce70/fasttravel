"""Typed configuration for the scheduler service.

Mirrors apps/api/src/config.py — same env-file conventions so devs see
one config shape across services. Adds Telegram fields used by the
post_deals job, and a few job-tuning knobs.
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

    # --- Environment ---
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Database (async URL is canonical) ---
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Telegram ---
    # We accept str | None — channel id can be -100... numeric or @slug string.
    # Bot token absence is a first-class state: post_deals skips gracefully.
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None

    # --- Job tuning ---
    # Telegram channel daily post cap (anti-spam contract with subscribers).
    deals_daily_cap: int = 30
    # How many unposted deals to consider per post_deals tick.
    deals_per_post_tick: int = 5
    # Sleep between sendMessage calls to stay under Telegram's 30 msg/sec
    # per-chat soft limit. 2s is conservative and keeps the worker simple
    # (no aiogram throttling middleware needed for MVP).
    telegram_send_delay_seconds: float = 2.0
    # Retention for price_observations partitions (days).
    partition_retention_days: int = 60

    # --- Scheduler / timezone ---
    scheduler_timezone: str = "Europe/Kyiv"

    # --- Sentry (optional) ---
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token) and bool(self.telegram_channel_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — read once per process."""
    return Settings()
