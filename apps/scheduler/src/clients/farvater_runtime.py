"""Shared Farvater runtime configuration for scheduler jobs."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from src.infra.cache import get_redis
from src.infra.farvater_http import (
    DEFAULT_MIN_INTERVAL_S,
    FarvaterProdClient,
    ProdTierConfig,
    open_prod_client,
)
from src.infra.logging import get_logger

log = get_logger(__name__)

CATALOG_COUNTRIES = [
    ("turkey", "TR"),
    ("egypt", "EG"),
    ("uae", "AE"),
    ("greece", "GR"),
    ("spain", "ES"),
    ("bulgaria", "BG"),
    ("thailand", "TH"),
    ("cyprus", "CY"),
    ("croatia", "HR"),
    ("montenegro", "ME"),
    ("maldives", "MV"),
]

CHECK_IN_OFFSETS_DAYS = [0]


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to *default* on empty/invalid values.

    These vars are read lazily inside every farvater job run, so a bare
    int() would turn one bad .env edit into a ValueError on every tick.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("farvater_runtime.invalid_env", var=name, value=raw, fallback=default)
        return default


def _env_float(name: str, default: float) -> float:
    """Float counterpart of `_env_int` — same fallback-and-warn contract."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("farvater_runtime.invalid_env", var=name, value=raw, fallback=default)
        return default


def prod_tier_config(default_concurrency: int = 3) -> ProdTierConfig:
    return ProdTierConfig(
        concurrency=_env_int("FT_FARVATER_HTTP_CONCURRENCY", default_concurrency),
        min_interval_s=_env_float("FT_FARVATER_HTTP_MIN_INTERVAL_S", DEFAULT_MIN_INTERVAL_S),
        daily_cap=_env_int("FT_FARVATER_DAILY_CAP", 0),
        timeout_s=_env_float("FT_FARVATER_HTTP_TIMEOUT_S", 30.0),
    )


@asynccontextmanager
async def open_farvater_client(
    *,
    default_concurrency: int = 3,
) -> AsyncIterator[FarvaterProdClient]:
    redis = get_redis()
    async with open_prod_client(redis, prod_tier_config(default_concurrency)) as client:
        yield client
