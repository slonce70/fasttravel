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


def prod_tier_config(default_concurrency: int = 3) -> ProdTierConfig:
    return ProdTierConfig(
        concurrency=int(os.environ.get("FT_FARVATER_HTTP_CONCURRENCY", str(default_concurrency))),
        min_interval_s=float(
            os.environ.get("FT_FARVATER_HTTP_MIN_INTERVAL_S", str(DEFAULT_MIN_INTERVAL_S))
        ),
        daily_cap=int(os.environ.get("FT_FARVATER_DAILY_CAP", "0")),
        timeout_s=float(os.environ.get("FT_FARVATER_HTTP_TIMEOUT_S", "30.0")),
    )


@asynccontextmanager
async def open_farvater_client(
    *,
    default_concurrency: int = 3,
) -> AsyncIterator[FarvaterProdClient]:
    redis = await get_redis()
    async with open_prod_client(redis, prod_tier_config(default_concurrency)) as client:
        yield client
