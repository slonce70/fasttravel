"""Ingest-layer configuration.

We deliberately do NOT import `apps.api.src.config` even though the
schema overlaps — each Poetry project is its own venv, and a hard
dependency on a sibling app would break Docker layer caching. The
trade-off is duplication of a handful of fields; the wins are
independent test runs and smaller images.

Every secret defaults to empty string so a developer can `docker compose
up` without touching .env — the clients then raise the typed
`ClientNotConfigured` exception that pipeline.py knows how to skip.
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

    # --- Shared infra (must match apps/api) ---
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )
    redis_url: str = "redis://redis:6379/0"

    # --- ittour API ---
    ittour_api_base: str = "https://api.ittour.com.ua"
    ittour_api_token: str = ""
    # ittour whitelists by IP; some endpoints require us to echo that IP
    # back in a header. Configurable so local dev can use whatever the
    # operator returns for `curl ifconfig.me`.
    ittour_source_ip: str = ""
    ittour_search_poll_timeout_s: int = 30
    ittour_search_poll_interval_s: float = 0.5

    # --- farvater scraper (bootstrap fallback) ---
    farvater_base_url: str = "https://farvater.travel"
    # 0.5 req/sec sustained — hardcoded in the client too, this is the
    # operator-visible knob in case we ever need to dial down further.
    farvater_min_request_interval_s: float = 2.0
    farvater_daily_request_cap: int = 1000
    # 3 consecutive 429/403 → trip the breaker.
    farvater_breaker_threshold: int = 3
    farvater_user_agent: str = "FastTravel-Bootstrap/0.1 (+https://fasttravel.com.ua/about)"

    # --- TBO Holidays ---
    tbo_api_base: str = "https://api.tbotechnology.in/TBOHolidays_HotelAPI"
    tbo_username: str = ""
    tbo_password: str = ""
    # TBO documents 20s as their hard response-time ceiling.
    tbo_request_timeout_s: float = 20.0

    # --- Pipeline knobs ---
    pipeline_per_source_concurrency: int = 5
    # 12h sliding window for the offer fingerprint dedup. Anything longer
    # and we miss legitimate price re-quotes; shorter and we double-write
    # identical observations from the morning/evening snapshot runs.
    dedup_ttl_hours: int = 12


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
