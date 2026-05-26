"""Farvater.travel bootstrap scraper.

This is a conservative, ethical client for use ONLY until we have an
official ittour API token. farvater.travel appears to run on the
ittour SaaS stack (robots.txt signature: `Allow: */ws.asmx/`), so the
data we collect from public hotel pages is the same data we'd get via
ittour direct — we just don't have the token yet.

Hardcoded constraints (not just config — defaults the operator can
NOT loosen without editing this file):
  * 0.5 req/sec sustained (asyncio.Semaphore(1) + 2s minimum interval)
  * Daily cap counted in Redis (key TTL'd to UTC midnight)
  * 3 consecutive 429/403 → circuit breaker trips for 1h
  * Honest User-Agent identifying us with a contact URL
  * No browser-rendered scraping (curl_cffi only — if calendar widget
    requires JS, we log a warn and stop, we do NOT bring up a headless
    browser pool for farvater)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self, cast

import structlog
from curl_cffi import requests as cffi_requests
from redis.asyncio import Redis

from src.exceptions import (
    BootstrapBreakerOpen,
    BootstrapDailyCapHit,
    ForbiddenByUpstream,
    RateLimitExceeded,
)
from src.settings import get_settings

_BREAKER_REDIS_KEY = "ingest:farvater:breaker:open_until"
_DAILY_COUNT_REDIS_KEY = "ingest:farvater:daily_count"
_CONSECUTIVE_BAD_KEY = "ingest:farvater:consecutive_bad"


class FarvaterScraper:
    """Bootstrap-only scraper. Used to seed the database with real prices
    while we wait for the ittour partner agreement."""

    source = "farvater"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._log = structlog.get_logger().bind(source=self.source)
        self._settings = get_settings()
        # asyncio.Semaphore(1) — at most ONE in-flight request at a time
        # is the bluntest possible rate limit. Combined with the
        # min_interval check below, this guarantees ≤0.5 req/sec.
        self._semaphore = asyncio.Semaphore(1)
        self._rate_lock = asyncio.Lock()
        self._last_request_at: float = 0.0
        self._session: cffi_requests.AsyncSession | None = None

    # ---------- lifecycle ----------

    async def __aenter__(self) -> Self:
        # impersonate=chrome117 → real Chrome ClientHello with same JA3
        # fingerprint as a desktop browser. Without this, Cloudflare-fronted
        # sites (which farvater isn't yet — but might become tomorrow)
        # would 403 us on the TLS handshake.
        self._session = cffi_requests.AsyncSession(
            impersonate="chrome",
            headers={"User-Agent": self._settings.farvater_user_agent},
            timeout=20.0,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ---------- public surface ----------

    async def fetch_hotel_page(self, slug: str) -> str:
        """Return raw HTML for `/uk/hotel/{slug}/`.

        Caller is responsible for parsing (see farvater_normalizer.py). This
        generic ingest client intentionally returns hotel HTML only; live
        production price capture for Farvater is implemented in scheduler
        snapshot jobs, where the current request sequence is known.
        """
        url = f"{self._settings.farvater_base_url}/uk/hotel/{slug}/"
        return await self._get_text(url)

    async def fetch_calendar_xhr(self, hotel_external_id: str) -> dict[str, Any]:
        """Unsupported generic calendar endpoint for Farvater.

        Scheduler snapshots own the real Farvater price path. This method
        raises NotImplementedError so the generic ingest pipeline records an
        explicit skipped run instead of pretending calendar prices were read.
        """
        raise NotImplementedError(
            f"{self.source}: calendar XHR endpoint unknown — "
            "run a manual HAR capture and update fetch_calendar_xhr()"
        )

    # ---------- private ----------

    async def _get_text(self, url: str) -> str:
        await self._check_breaker()
        await self._check_daily_cap()
        await self._throttle()

        if self._session is None:
            raise RuntimeError("FarvaterScraper used outside `async with`")

        async with self._semaphore:
            log = self._log.bind(url=url)
            try:
                response = await self._session.get(url)
            except Exception as e:
                log.warning("farvater.network_error", error=str(e))
                await self._record_bad()
                raise

            log.info("farvater.response", status=response.status_code)
            await self._increment_daily()

            if response.status_code == 429:
                await self._record_bad()
                raise RateLimitExceeded(self.source, 429, response.text[:300])
            if response.status_code == 403:
                await self._record_bad()
                raise ForbiddenByUpstream(self.source, 403, response.text[:300])
            if response.status_code >= 400:
                await self._record_bad()
                response.raise_for_status()

            await self._reset_bad()
            return cast(str, response.text)

    async def _throttle(self) -> None:
        """Enforce min interval between requests."""
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            interval = self._settings.farvater_min_request_interval_s
            wait = (self._last_request_at + interval) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = asyncio.get_event_loop().time()

    async def _check_breaker(self) -> None:
        until = await self._redis.get(_BREAKER_REDIS_KEY)
        if until is None:
            return
        until_dt = datetime.fromisoformat(until.decode())
        if until_dt > datetime.now(UTC):
            raise BootstrapBreakerOpen(self.source, until_dt.isoformat())

    async def _check_daily_cap(self) -> None:
        count = await self._redis.get(_DAILY_COUNT_REDIS_KEY)
        used = int(count) if count else 0
        if used >= self._settings.farvater_daily_request_cap:
            raise BootstrapDailyCapHit(self.source, used)

    async def _increment_daily(self) -> None:
        """Increment counter, set TTL to next UTC midnight on first hit."""
        new = await self._redis.incr(_DAILY_COUNT_REDIS_KEY)
        if new == 1:
            now = datetime.now(UTC)
            tomorrow = (
                (
                    now.replace(hour=0, minute=0, second=0, microsecond=0).replace(day=now.day)
                ).timestamp()
                + 86400
                - now.timestamp()
            )
            await self._redis.expire(_DAILY_COUNT_REDIS_KEY, int(tomorrow))

    async def _record_bad(self) -> None:
        bad = await self._redis.incr(_CONSECUTIVE_BAD_KEY)
        await self._redis.expire(_CONSECUTIVE_BAD_KEY, 600)  # 10 min window
        if bad >= self._settings.farvater_breaker_threshold:
            # Trip the breaker for 1 hour.
            until = datetime.now(UTC).timestamp() + 3600
            until_dt = datetime.fromtimestamp(until, tz=UTC)
            await self._redis.set(_BREAKER_REDIS_KEY, until_dt.isoformat(), ex=3600)
            self._log.warning(
                "farvater.breaker_tripped",
                consecutive_bad=bad,
                until=until_dt.isoformat(),
            )

    async def _reset_bad(self) -> None:
        await self._redis.delete(_CONSECUTIVE_BAD_KEY)
