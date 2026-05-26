"""Typed configuration loaded from environment / .env.

Pydantic v2 moved settings to the separate `pydantic-settings` package.

Note on list/CSV fields: pydantic-settings tries to parse env-var values
for complex types (list, dict, set) as JSON by default. We override that
in `_cors_origins` by accepting either a plain string ("a,b,c") OR a JSON
array. The stored type is a plain `str` and we expose a parsed `list[str]`
through `cors_origins`.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
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

    # --- Database (async URL is the canonical one) ---
    database_url: str = Field(
        default="postgresql+asyncpg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Stored raw to avoid pydantic-settings' JSON pre-parsing of list fields.
    # Use `.cors_origins` to get the parsed list.
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:3100,http://127.0.0.1:3100",
        alias="cors_origins",
    )

    # --- Sentry (optional — only init when DSN present) ---
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @cached_property
    def cors_origins(self) -> list[str]:
        """Comma-separated list, parsed lazily so env var stays a plain str."""
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    def assert_prod_secrets(self) -> None:
        """Refuse to boot prod with the dev defaults from .env.example.

        Anyone who deploys without running infra/scripts/secrets-bootstrap.sh
        would end up exposing a known-public Postgres password — this guard
        crashes startup loudly instead of letting that ship.
        """
        if not self.is_prod:
            return
        forbidden_markers = ("_change_me", "fasttravel_dev")
        offenders: list[str] = []
        if any(m in self.database_url for m in forbidden_markers):
            offenders.append("DATABASE_URL")
        if any(m in self.database_url_sync for m in forbidden_markers):
            offenders.append("DATABASE_URL_SYNC")
        if offenders:
            raise RuntimeError(
                "Refusing to start in prod with default secrets in "
                + ", ".join(offenders)
                + ". Run infra/scripts/secrets-bootstrap.sh and re-deploy."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — read once per process."""
    return Settings()
