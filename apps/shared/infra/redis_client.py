"""Shared async Redis singleton.

Audit Sprint #7: api/scheduler/bot each constructed their own Redis
client lazily and worked around the asyncio-vs-sync typing quirk in
`redis.asyncio` differently (api had `_maybe_await_redis`, scheduler
had `cast(Awaitable[int], ...)`). Centralising the factory here means
both quirks live in one place.

Usage:

    from shared.infra.redis_client import get_redis_factory

    get_redis = get_redis_factory(settings.redis_url)
    # ... later in a handler:
    redis = get_redis()
    await redis.set("k", "v")

We expose a *factory* function rather than an exported singleton so
test code can override `redis_url` per fixture without mutating
module state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# redis.asyncio is imported lazily so unit tests that don't touch Redis
# don't pay the import-time cost. The factory closes over the URL so
# a service binds its own logical DB choice at startup.
_Redis = Any  # `redis.asyncio.Redis` — typed as Any to avoid import-time dep


def get_redis_factory(redis_url: str) -> Callable[[], _Redis]:
    """Return a no-arg `() -> Redis` that lazily builds + memoises a
    client for *redis_url*.

    The returned callable is process-singleton: first call builds the
    Redis instance, subsequent calls return the same instance. Tests
    that need a fresh client per case should call
    `get_redis_factory(url)` to get a new factory rather than reusing
    the application-level one.
    """
    _state: dict[str, _Redis] = {}

    def _get() -> _Redis:
        client = _state.get("client")
        if client is None:
            import redis.asyncio as _async_redis

            from_url: Any = _async_redis.from_url
            client = from_url(
                redis_url,
                decode_responses=True,
                # Sensible production defaults — short connect timeout
                # so a Redis blip surfaces fast instead of stalling a
                # request for the default ~30s.
                socket_connect_timeout=3,
                socket_keepalive=True,
                # Bound every reply read so a half-open connection raises
                # TimeoutError instead of hanging the caller forever (kernel
                # TCP keepalive alone takes ~2h to notice). Must stay above
                # the longest blocking-command timeout routed through this
                # client (scheduler refresh_worker BRPOP timeout=5s): redis-py
                # applies socket_timeout to the whole BRPOP wait, so a smaller
                # value would raise spuriously on every idle poll.
                socket_timeout=10,
                # Ping connections idle longer than this before reuse, so a
                # dead pooled connection is replaced instead of failing the
                # next real command.
                health_check_interval=30,
            )
            _state["client"] = client
        return client

    return _get


async def close_redis(client: _Redis | None) -> None:
    """Close a Redis client cleanly — no-op when *client* is None."""
    if client is None:
        return
    try:
        await client.close()
    finally:
        # redis-py 5.x split the connection pool out; close pool too
        # if it exists. Older clients (4.x) just need .close().
        pool = getattr(client, "connection_pool", None)
        if pool is not None:
            disconnect = getattr(pool, "disconnect", None)
            if disconnect is not None:
                try:
                    result = disconnect()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # noqa: BLE001
                    # disconnect() best-effort; never crash shutdown.
                    pass
