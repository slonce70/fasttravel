"""Typed configuration loaded from environment / .env.

Service-specific fields only — shared environment, db, redis, sentry
fields live on `shared.infra.base_settings.BaseAppSettings`.

Note on list/CSV fields: pydantic-settings tries to parse env-var values
for complex types (list, dict, set) as JSON by default. We override that
in `_cors_origins` by accepting either a plain string ("a,b,c") OR a JSON
array. The stored type is a plain `str` and we expose a parsed `list[str]`
through `cors_origins`.
"""

from __future__ import annotations

from functools import cached_property, lru_cache

from pydantic import Field
from shared.infra.base_settings import DEV_DEFAULT_MARKERS, BaseAppSettings


class Settings(BaseAppSettings):
    # --- Database (sync URL is API-only; Alembic offline mode uses it) ---
    database_url_sync: str = Field(
        default="postgresql+psycopg://fasttravel:fasttravel_dev_change_me@postgres:5432/fasttravel"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    public_site_url: str = "https://fasttravel.com.ua"
    # Stored raw to avoid pydantic-settings' JSON pre-parsing of list fields.
    # Use `.cors_origins` to get the parsed list.
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100",
        alias="cors_origins",
    )

    @cached_property
    def cors_origins(self) -> list[str]:
        """Comma-separated list, parsed lazily so env var stays a plain str."""
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    def _extra_prod_offenders(self) -> list[str]:
        # API-specific: DATABASE_URL_SYNC carries the same secret in a
        # different driver — same dev-default check applies.
        if any(m in self.database_url_sync for m in DEV_DEFAULT_MARKERS):
            return ["DATABASE_URL_SYNC"]
        return []


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — read once per process."""
    return Settings()
