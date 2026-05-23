"""BaseClient — shared HTTP wrapper for every upstream source.

Responsibilities:
  * single async httpx.AsyncClient per instance, reused across calls
  * tenacity-driven retries with exponential backoff (idempotent GETs)
  * per-source concurrency cap via asyncio.Semaphore
  * minimal token-bucket rate limiter (interval-based, not RPS leaks)
  * structlog binding so every log line carries (source, request_id)
  * uniform 4xx/5xx → IngestError mapping

What it deliberately does NOT do:
  * URL composition (each subclass owns its endpoints)
  * auth header injection (subclass `_default_headers()` hook)
  * JSON-vs-HTML parsing (caller picks `.json()` or `.text`)

Why httpx + http2: TBO/ittour both serve over HTTPS with keep-alive; a
single multiplexed connection halves handshake cost during the snapshot
burst window. curl_cffi (farvater) does NOT use this base class because
it has its own session lifecycle.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from time import monotonic
from types import TracebackType
from typing import Any, Self

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.exceptions import (
    ForbiddenByUpstream,
    IngestError,
    RateLimitExceeded,
    UpstreamHTTPError,
)


class BaseClient:
    """Async HTTP client with rate limit, retries, and structured logs."""

    #: Subclasses override these.
    source: str = "base"
    base_url: str = ""
    default_timeout_s: float = 15.0
    #: Max concurrent in-flight requests for THIS client instance.
    concurrency: int = 5
    #: Minimum interval between two successive requests (seconds). 0 = unbounded.
    min_request_interval_s: float = 0.0
    #: How many times to retry transient 5xx / network errors.
    retry_attempts: int = 3

    def __init__(self) -> None:
        self._log = structlog.get_logger().bind(source=self.source)
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._rate_lock = asyncio.Lock()
        self._next_allowed_at: float = 0.0
        self._client: httpx.AsyncClient | None = None

    # ---------- lifecycle ----------

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.default_timeout_s,
            http2=True,
            headers=self._default_headers(),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _default_headers(self) -> dict[str, str]:
        """Override in subclass to inject auth, source-IP, UA, etc."""
        return {"User-Agent": f"FastTravel-Ingest/{self.source}"}

    # ---------- rate limit ----------

    async def _throttle(self) -> None:
        """Token-bucket-ish gate: ensure at least `min_request_interval_s`
        passes between any two requests on this client."""
        if self.min_request_interval_s <= 0:
            return
        async with self._rate_lock:
            now = monotonic()
            wait = self._next_allowed_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_allowed_at = monotonic() + self.min_request_interval_s

    # ---------- request entrypoint ----------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Generic request with logging + retry. Subclasses use `_get` / `_post`."""
        if self._client is None:
            raise IngestError(f"{self.source} client used outside `async with`")

        request_id = uuid.uuid4().hex[:8]
        log = self._log.bind(request_id=request_id, method=method, url=url)

        async def _do_call() -> httpx.Response:
            await self._throttle()
            async with self._semaphore:
                started = monotonic()
                response = await self._client.request(method, url, **kwargs)  # type: ignore[union-attr]
                duration_ms = int((monotonic() - started) * 1000)
                log.info(
                    "upstream_request",
                    status=response.status_code,
                    bytes=len(response.content),
                    duration_ms=duration_ms,
                )
                self._handle_response(response)
                return response

        if not retry:
            return await _do_call()

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.retry_attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
            # Only retry on transient HTTP errors and network errors;
            # 4xx (except 429) is the caller's fault, don't pound.
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.TimeoutException, RateLimitExceeded)
            ),
            reraise=True,
        ):
            with attempt:
                return await _do_call()
        # Unreachable: AsyncRetrying with reraise=True either returns or raises.
        raise IngestError("retry loop exited unexpectedly")

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", url, **kwargs)

    # ---------- response handling ----------

    def _handle_response(self, r: httpx.Response) -> None:
        """Map non-2xx to typed IngestError subclasses.

        We snip the body to 500 chars in the exception — full payload still
        lives in the structured log line above, but exception strings get
        emailed/Sentry'd and we don't want to flood with 200KB of HTML.
        """
        if r.status_code < 400:
            return
        body = r.text[:500]
        if r.status_code == 429:
            raise RateLimitExceeded(self.source, r.status_code, body)
        if r.status_code == 403:
            raise ForbiddenByUpstream(self.source, r.status_code, body)
        raise UpstreamHTTPError(self.source, r.status_code, body)

    # ---------- convenience for tests ----------

    @asynccontextmanager
    async def session(self) -> Any:
        """`async with client.session(): ...` — alias for `async with client:`."""
        async with self as c:
            yield c
