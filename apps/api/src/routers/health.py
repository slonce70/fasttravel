"""Liveness / readiness probe.

GET /health pings Postgres and Redis. Returns 200 with per-component
status; returns 503 if any required dep is down.
"""
from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from src.infra.cache import ping_redis
from src.infra.db import ping_db
from src.infra.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger("health")


class HealthOut(BaseModel):
    status: str
    db: str
    redis: str


@router.get("/health", response_model=HealthOut)
async def health(response: Response) -> HealthOut:
    db_ok = False
    redis_ok = False

    try:
        db_ok = await ping_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("health.db_ping_failed", error=str(exc))

    try:
        redis_ok = await ping_redis()
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_ping_failed", error=str(exc))

    overall = db_ok and redis_ok
    if not overall:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthOut(
        status="ok" if overall else "degraded",
        db="ok" if db_ok else "down",
        redis="ok" if redis_ok else "down",
    )
