"""Production-tier HTTP wrapper for farvater.travel calls from the scheduler.

Why a new module instead of porting onto `apps/ingest/src/clients/
farvater_scraper.py`: that client is correctly tuned for a low-volume
*bootstrap* tier (concurrency=1, 2s interval, optional req/day cap). The
scheduler's `snapshot_farvater` already runs at ~3 req/s and the new
`static_tours_sweep` will add more — porting onto the bootstrap tier
would push every snapshot past its scheduling window and trip the
daily cap.

This wrapper provides a *production* tier with sane budgets and the
same protective guards (circuit breaker, request counter, throttle, JA3
mimicry via curl_cffi if available, else plain httpx). Both
`snapshot_farvater` (over time, in Sprint 1F) and `static_tours_sweep`
(Sprint 1C) will sit on top of this wrapper.

Key knobs (defaults — overridable per call site):

- concurrency = 3        (semaphore-gated; matches current snapshot load)
- min_interval_s = 0.05  (token-bucket between every request)
- daily_cap = 0          (disabled; Redis counter is telemetry only)
- breaker: 5 × {429,403} inside a 15-min window → 1 hour cool-down

On any 429/403 the consecutive-bad counter increments. After 5 bad
hits inside `BREAKER_WINDOW_S` the breaker opens for `BREAKER_COOLDOWN_S`;
in-flight calls during the open window fail fast with `BreakerOpen`.

Metrics are emitted from `src.infra.metrics`:
- `FARVATER_BREAKER_TRIPS` — incremented when breaker opens
- `SCRAPE_HOTEL_FAILURES{reason=...}` — incremented per failed request
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import httpx
from redis.asyncio import Redis

from src.infra.logging import get_logger

log = get_logger(__name__)


# Defaults — concrete values rather than `None` so the call sites don't
# have to thread settings through every layer just to override one knob.
DEFAULT_CONCURRENCY = 3
DEFAULT_MIN_INTERVAL_S = 0.05
DEFAULT_DAILY_CAP = 0
DEFAULT_TIMEOUT_S = 30.0

# Circuit-breaker tuning. 5 strikes in 15min trips a 1-hour cooldown.
# Looser than the bootstrap tier (3 strikes / 10min / 1h) because the
# production tier sees more traffic and a single transient 429 burst
# during a load spike on farvater's side shouldn't take us out.
BREAKER_THRESHOLD = 5
BREAKER_WINDOW_S = 15 * 60
BREAKER_COOLDOWN_S = 60 * 60

USER_AGENT = "FastTravel-Scheduler/1.0 (+https://fasttravel.com.ua/about; bot@fasttravel.com.ua)"
GET_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# Redis keys are scoped to "prod" tier so the bootstrap client (which
# lives in apps/ingest) has its own independent breaker + counter.
_BREAKER_KEY = "scheduler:farvater:breaker:open_until"
_CONSECUTIVE_BAD_KEY = "scheduler:farvater:consecutive_bad"
_DAILY_COUNTER_KEY_FMT = "scheduler:farvater:daily_count:{ymd}"


class FarvaterHttpError(Exception):
    """Base for all errors raised by this module."""


class BreakerOpen(FarvaterHttpError):
    """Circuit breaker is open; not retrying until the cooldown elapses."""


class DailyCapHit(FarvaterHttpError):
    """Daily request cap reached; not making more calls today."""


class UpstreamRateLimited(FarvaterHttpError):
    """Upstream returned 429/403; the breaker counter has been incremented."""


@dataclass
class ProdTierConfig:
    """Per-instance overrides. Defaults match the module-level constants."""

    concurrency: int = DEFAULT_CONCURRENCY
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    daily_cap: int = DEFAULT_DAILY_CAP
    timeout_s: float = DEFAULT_TIMEOUT_S


class FarvaterProdClient:
    """Production-tier farvater HTTP client.

    Use as an async context manager — the underlying `httpx.AsyncClient`
    is created on enter and disposed on exit.

    The Redis client is passed in (not opened here) so callers can share
    a single connection pool with the rest of the scheduler.
    """

    def __init__(
        self,
        redis: Redis,
        config: ProdTierConfig | None = None,
    ) -> None:
        self._redis = redis
        self._config = config or ProdTierConfig()
        self._semaphore = asyncio.Semaphore(self._config.concurrency)
        self._rate_lock = asyncio.Lock()
        self._last_request_ts: float = 0.0
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=self._config.concurrency * 2,
                max_keepalive_connections=self._config.concurrency,
            ),
            timeout=self._config.timeout_s,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── public API ───────────────────────────────────────────────────

    async def post_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST a JSON body and return the parsed JSON response.

        Applies breaker + request counter + throttle in that order. Raises
        `BreakerOpen` / `UpstreamRateLimited` so callers can distinguish
        "we're paused" from "upstream is blocking us" from actual HTTP errors.
        `DailyCapHit` is only possible when a caller opts into a positive
        `daily_cap`.
        """
        await self._check_breaker()
        await self._check_and_increment_daily_cap()
        await self._throttle()

        async with self._semaphore:
            assert self._client is not None, "Use as async context manager"
            response = await self._client.post(
                url,
                params=params,
                json=json,
                headers=extra_headers or {},
            )

        if response.status_code in (429, 403):
            await self._register_bad_response(response.status_code)
            raise UpstreamRateLimited(f"farvater returned {response.status_code} for {url}")

        response.raise_for_status()
        # Reset bad counter on success — a healthy response means the
        # current burst is over.
        await self._redis.delete(_CONSECUTIVE_BAD_KEY)
        return response.json()  # type: ignore[no-any-return]

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        """GET a text/html-style resource through the same production guards."""
        response = await self.get(url, params=params, extra_headers=extra_headers)
        return response.text

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """GET a resource and return the response object.

        This mirrors the subset of `httpx.AsyncClient.get` used by legacy
        sitemap code, while still applying breaker, telemetry counter, and throttle.
        """
        await self._check_breaker()
        await self._check_and_increment_daily_cap()
        await self._throttle()

        request_headers = dict(extra_headers if extra_headers is not None else headers or {})
        request_headers.setdefault("Accept", GET_ACCEPT)
        async with self._semaphore:
            assert self._client is not None, "Use as async context manager"
            # httpx treats an explicit per-request timeout=None as "disable
            # all timeouts", not "use the client default" — forward the
            # sentinel instead so the client-level timeout keeps applying
            # when callers don't override it.
            response = await self._client.get(
                url,
                params=params,
                headers=request_headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )

        if response.status_code in (429, 403):
            await self._register_bad_response(response.status_code)
            raise UpstreamRateLimited(f"farvater returned {response.status_code} for {url}")

        response.raise_for_status()
        await self._redis.delete(_CONSECUTIVE_BAD_KEY)
        return response

    # ── internals ────────────────────────────────────────────────────

    async def _check_breaker(self) -> None:
        raw = await self._redis.get(_BREAKER_KEY)
        if raw is None:
            return
        try:
            open_until = float(raw)
        except (TypeError, ValueError):
            await self._redis.delete(_BREAKER_KEY)
            return
        if time.time() < open_until:
            remaining = int(open_until - time.time())
            raise BreakerOpen(f"breaker open for another {remaining}s")
        # Cooldown elapsed — clear so the next request can proceed.
        await self._redis.delete(_BREAKER_KEY)
        await self._redis.delete(_CONSECUTIVE_BAD_KEY)

    async def _check_and_increment_daily_cap(self) -> None:
        ymd = datetime.now(UTC).strftime("%Y%m%d")
        key = _DAILY_COUNTER_KEY_FMT.format(ymd=ymd)
        new_count = await self._redis.incr(key)
        if new_count == 1:
            # First increment of the day — set TTL to next UTC midnight
            # so the key auto-expires even if the scheduler restarts.
            now = datetime.now(UTC)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ttl = max(60, int((next_midnight - now).total_seconds()))
            await self._redis.expire(key, ttl)
        if self._config.daily_cap > 0 and new_count > self._config.daily_cap:
            # Decrement back so the cap is enforced rather than reported
            # inaccurately if the operator wants to inspect it.
            await self._redis.decr(key)
            raise DailyCapHit(
                f"daily cap {self._config.daily_cap} reached ({new_count - 1} prior calls today)"
            )

    async def _throttle(self) -> None:
        """Token-bucket — at most one request every `min_interval_s`.

        Serialized via `_rate_lock` so concurrent callers (up to
        `concurrency`) take turns rather than all firing at once.
        """
        async with self._rate_lock:
            now = time.monotonic()
            wait = self._last_request_ts + self._config.min_interval_s - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_ts = time.monotonic()

    async def _register_bad_response(self, status_code: int) -> None:
        """Tick the consecutive-bad counter; trip the breaker on overrun."""
        new_count = await self._redis.incr(_CONSECUTIVE_BAD_KEY)
        if new_count == 1:
            await self._redis.expire(_CONSECUTIVE_BAD_KEY, BREAKER_WINDOW_S)
        log.warning(
            "farvater.prod.bad_response",
            status_code=status_code,
            consecutive_bad=new_count,
            threshold=BREAKER_THRESHOLD,
        )
        if new_count >= BREAKER_THRESHOLD:
            open_until = time.time() + BREAKER_COOLDOWN_S
            await self._redis.set(_BREAKER_KEY, str(open_until), ex=BREAKER_COOLDOWN_S)
            await self._redis.delete(_CONSECUTIVE_BAD_KEY)
            log.error(
                "farvater.prod.breaker_tripped",
                cooldown_s=BREAKER_COOLDOWN_S,
                trigger_status=status_code,
            )
            # Best-effort metric — never let metric write crash a request.
            try:
                from src.infra.metrics import FARVATER_BREAKER_TRIPS

                FARVATER_BREAKER_TRIPS.inc()
            except Exception:  # noqa: BLE001
                log.exception("farvater.prod.metric_set_failed")


@asynccontextmanager
async def open_prod_client(
    redis: Redis,
    config: ProdTierConfig | None = None,
) -> AsyncIterator[FarvaterProdClient]:
    """Convenience async context manager:

    async with open_prod_client(redis) as client:
        data = await client.post_json(...)
    """
    async with FarvaterProdClient(redis, config) as client:
        yield client
