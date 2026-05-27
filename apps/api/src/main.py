"""FastAPI entrypoint.

Lifespan:
    startup  — configure logging, init Sentry (optional)
    shutdown — dispose async DB engine, close Redis pool

Middleware:
    1. CorrelationIdMiddleware  — generate / propagate X-Request-ID into
       structlog contextvars so every log line gets it for free.
    2. CORS                     — restricted to settings.cors_origins.
    3. Prometheus instrumentator — exposes /metrics.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.config import get_settings
from src.infra.cache import close_redis
from src.infra.db import dispose_engine
from src.infra.limiter import limiter
from src.infra.logging import configure_logging, get_logger
from src.infra.middleware import AmpQueryParamMiddleware
from src.infra.sentry import configure_sentry
from src.routers import deals as deals_router
from src.routers import destinations as destinations_router
from src.routers import health as health_router
from src.routers import hotels as hotels_router
from src.routers import promotions as promotions_router
from src.routers import search as search_router
from src.routers import seo as seo_router

log = get_logger("api.main")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a stable correlation id to every log emitted during a request."""

    HEADER = "x-request-id"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get(self.HEADER) or uuid.uuid4().hex
        # Clear ANY contextvars left over from a previous request on this
        # thread, then bind the new ones.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid,
            method=request.method,
            path=request.url.path,
        )
        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers[self.HEADER] = rid
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    # Hard crash on boot if prod is using the default `_change_me` secrets.
    # See Settings.assert_prod_secrets for what we check.
    settings.assert_prod_secrets()
    sentry_enabled = configure_sentry()
    log.info(
        "api.startup",
        environment=settings.environment,
        sentry=sentry_enabled,
    )
    try:
        yield
    finally:
        await dispose_engine()
        await close_redis()
        log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="FastTravel API",
        version="0.1.0",
        description="Read-only API over the FastTravel hotel/price aggregator.",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_prod else None,
    )

    # Wire slowapi: attach the limiter to app.state, register the 429 handler,
    # and install the middleware that decrements the rate-limit bucket before
    # route handlers run. Routers can then use `@limiter.limit(...)`.
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        cast(Callable[[Request, Exception], Response], _rate_limit_exceeded_handler),
    )
    app.add_middleware(SlowAPIMiddleware)

    # Order matters: CORS first so it sees the original request, then
    # correlation id wraps everything in a context.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        # POST allowed for /api/hotels/{id}/refresh; everything else is GET.
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    # Audit #1.3 High — rewrite `?amp;param=…` to `?param=…` before
    # routes see the query string. Replaces the per-router duplicate
    # `amp_param` Query() definitions that polluted OpenAPI.
    app.add_middleware(AmpQueryParamMiddleware)

    # Routers
    app.include_router(health_router.router)
    app.include_router(hotels_router.router)
    app.include_router(search_router.router)
    app.include_router(deals_router.router)
    app.include_router(promotions_router.router)
    app.include_router(destinations_router.router)
    app.include_router(seo_router.router)

    # /metrics — Prometheus scrape target.
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
